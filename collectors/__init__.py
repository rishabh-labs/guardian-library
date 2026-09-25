"""Collector registry and the run loop."""
import logging
import traceback
from datetime import datetime, timezone

from dateutil import parser as dateparser

import config
import db
from . import news, newsletters, podcasts, watch, youtube

log = logging.getLogger("collectors")

# kind -> (collector function, human label)
REGISTRY = {
    "youtube_channel": (youtube.collect_channel, "YouTube channel"),
    "youtube_search":  (youtube.collect_search,  "YouTube search"),
    "newsletter_page": (newsletters.collect_newsletter_page,
                        "Newsletter listing page"),
    "newsletter_pattern": (newsletters.collect_newsletter_pattern,
                           "Newsletter URL pattern"),
    "wp_media":        (newsletters.collect_wp_media,
                        "WordPress media library"),
    "page_pdfs":       (newsletters.collect_page_pdfs,
                        "Every PDF a page references"),
    "rss":             (news.collect_rss,         "RSS feed"),
    "podcast_feed":    (podcasts.collect_show_feed, "Podcast feed"),
    "page_watch":      (watch.collect_page,       "Website watch"),
    # Kept so existing rows still resolve, but no longer created by the
    # importers - the library tracks newsletters rather than news.
    "news_search":     (news.collect_news_search, "Google News (house)"),
    "news_person":     (news.collect_news_person, "Google News (person)"),
}

SOURCE_KINDS = list(REGISTRY.keys())


class Skipped(Exception):
    """Source cannot run for a known, non-error reason - e.g. no API key."""


def due(source):
    """False when a quota-costing source was polled too recently.

    Only YouTube keyword searches cost anything: 100 units each against a free
    10,000/day. Channel feeds, newsletters and podcasts are free and keep the
    fast cadence. A source that has never run successfully is always due, so a
    new fund still gets its backfill immediately.
    """
    if source["kind"] != "youtube_search":
        return True
    last = source.get("last_checked")
    if not last:
        return True
    try:
        when = dateparser.parse(last)
    except (ValueError, TypeError):
        return True
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    age_hours = (datetime.now(timezone.utc) - when).total_seconds() / 3600
    return age_hours >= config.SEARCH_MIN_HOURS


def run_source(source):
    """Collect one source. Returns (new_count, status_string)."""
    fn, label = REGISTRY[source["kind"]]
    if source["kind"] == "youtube_search" and not config.YOUTUBE_API_KEY:
        raise Skipped("needs YOUTUBE_API_KEY - not set")
    first_run = not source.get("last_checked")
    items = fn(source)
    new = db.insert_items(items)

    # A page watcher sees the entire existing page on its first visit. Seed it
    # quietly rather than flooding the dashboard with old posts.
    if first_run and source["kind"] == "page_watch" and new:
        conn = db.connect()
        with conn:
            conn.execute("UPDATE items SET seen = 1 WHERE source_id = ?",
                         (source["id"],))
        conn.close()
        return new, f"seeded {new} existing links"

    return new, f"ok - {len(items)} fetched, {new} new"


def run_all():
    """Poll every enabled source of every active fund."""
    run_id = db.start_run()
    sources = db.list_sources(enabled_only=True)
    total_new, ok, fail, skipped = 0, 0, 0, 0
    detail = []

    for src in sources:
        if src["kind"] not in REGISTRY:
            db.mark_source_checked(src["id"], f"unknown kind {src['kind']}")
            fail += 1
            continue
        if not due(src):
            # Polled within the quota window; leave it alone this cycle.
            skipped += 1
            continue
        try:
            new, status = run_source(src)
            total_new += new
            ok += 1
            db.mark_source_checked(src["id"], status)
            if new:
                detail.append(f"{src['fund_name']} / {src['kind']}: +{new}")
        except Skipped as exc:
            # Not a failure - the source is fine, we just can't run it yet.
            # Deliberately does not set last_checked, so the source still gets
            # its full backfill window whenever it does first run.
            skipped += 1
            db.mark_source_status(src["id"], f"skipped: {exc}")
        except Exception as exc:  # a dead feed must not stop the rest
            fail += 1
            msg = f"{type(exc).__name__}: {exc}"
            # Record the error but do NOT mark the source as polled. A source
            # that failed never got its backfill, so treating it as checked
            # would silently downgrade its next run to the 1-month window.
            db.mark_source_status(src["id"], msg)
            detail.append(f"{src['fund_name']} / {src['kind']}: FAIL {msg}")
            # A dead URL or a rate limit is routine here; one line is enough.
            # The stack only matters when debugging a collector, so keep it
            # behind DEBUG rather than dumping it on every run.
            log.warning("%s / %s failed: %s", src["fund_name"], src["kind"],
                        msg[:160])
            log.debug("traceback for source %s:\n%s", src["id"],
                      traceback.format_exc())

    # General podcast shows are scanned once per run, not once per fund: the
    # feeds are shared, and an episode can name more than one tracked house.
    try:
        # First ever scan reaches back the full backfill; later ones only a
        # month, matching how per-source windows behave.
        seen_before = db.count_items(kind="podcast") > 0
        shared = podcasts.run_shared(
            window_days=(config.INCREMENTAL_DAYS if seen_before
                         else config.BACKFILL_DAYS))
        if shared:
            total_new += shared
            detail.append(f"shared podcasts: +{shared}")
    except Exception as exc:
        log.warning("shared podcast scan failed: %s", exc)
        detail.append(f"shared podcasts: FAIL {exc}")

    db.finish_run(run_id, total_new, ok, fail, detail)
    log.info("run complete: %d new, %d ok, %d skipped, %d failed",
             total_new, ok, skipped, fail)
    return {"new_items": total_new, "ok": ok, "skipped": skipped,
            "failed": fail, "detail": detail}
