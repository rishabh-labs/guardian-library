"""Podcast coverage.

Two different problems:

1. A fund house runs its own show ("Indian Market in Minutes with Motilal
   Oswal"). That is just an RSS feed attached to that house - the existing
   `rss` source kind handles it.

2. A manager appears as a guest on somebody else's show (Paisa Vaisa, The
   Big Perspective). There is no per-house feed to subscribe to, so instead we
   subscribe to the big Indian finance podcasts once, read every episode, and
   file an episode under whichever tracked house or manager it mentions.

The second is what this module does. Feeds are fetched once per run, not once
per fund, and an episode naming two tracked managers is filed under both.
"""
import logging

import feedparser

import db
from . import util

log = logging.getLogger("podcasts")

ITUNES_LOOKUP = "https://itunes.apple.com/lookup"

# General Indian finance/investing shows that regularly host fund managers.
# Stored as Apple Podcasts ids; the RSS URL is resolved at runtime because
# publishers move hosts and the Apple id is the stable handle.
SHARED_SHOWS = {
    "1239293215": "Paisa Vaisa with Anupam Gupta",
    "1744281210": "Indian Market in Minutes with Motilal Oswal",
    "1462388983": "Equity Sahi Hai",
}

_feed_cache = {}


def feed_url_for(apple_id):
    """Resolve an Apple Podcasts id to its RSS feed URL."""
    if apple_id in _feed_cache:
        return _feed_cache[apple_id]
    try:
        data = util.fetch(ITUNES_LOOKUP,
                          params={"id": apple_id, "entity": "podcast"}).json()
        results = data.get("results") or []
        url = results[0].get("feedUrl") if results else None
    except Exception as exc:
        log.warning("itunes lookup failed for %s: %s", apple_id, exc)
        url = None
    _feed_cache[apple_id] = url
    return url


def _episode_items(entry, fund, source_id=None):
    link = entry.get("link", "")
    published = util.parse_date(entry.get("published") or entry.get("updated"))
    return {
        "fund_id": fund["id"],
        "source_id": source_id,
        "kind": "podcast",
        "title": util.strip_html(entry.get("title", "(untitled)"), 300),
        "url": link,
        "canonical_url": util.canonicalise(link),
        "thumbnail": "",
        "author": util.strip_html(entry.get("itunes_author", "")
                                  or entry.get("author", ""), 120),
        "summary": util.strip_html(entry.get("summary", "")),
        "published_at": published,
    }


def collect_show_feed(source):
    """A podcast the fund house runs itself. Trusted - no relevance filter."""
    feed = feedparser.parse(source["value"])
    if feed.bozo and not feed.entries:
        raise RuntimeError(f"unreadable podcast feed: {feed.bozo_exception}")
    window = util.window_days(source)
    fund = {"id": source["fund_id"]}
    out = []
    for e in feed.entries:
        item = _episode_items(e, fund, source["id"])
        if util.too_old(item["published_at"], window) or not item["canonical_url"]:
            continue
        item["author"] = item["author"] or source.get("label", "")
        out.append(item)
    return out


def run_shared(window_days=None):
    """Scan the general shows and file episodes under whoever they mention.

    Returns the number of newly stored episodes. Runs once per collection
    cycle rather than once per fund - the feeds are the same for everyone.
    """
    funds = db.list_funds(active_only=True)
    if not funds:
        return 0

    # Precompute the match terms for each fund once.
    targets = []
    for f in funds:
        terms = [f["name"], f["house"]]
        terms += [m.strip() for m in (f["managers"] or "").split(",")]
        terms += [t.strip() for t in (f["match_terms"] or "").split(",")]
        targets.append((f, [t for t in terms if t and len(t) > 3]))

    stored = 0
    for apple_id, name in SHARED_SHOWS.items():
        url = feed_url_for(apple_id)
        if not url:
            log.warning("no feed url for %s (%s)", name, apple_id)
            continue
        feed = feedparser.parse(url)
        if not feed.entries:
            log.warning("no episodes in %s", name)
            continue

        rows = []
        for e in feed.entries:
            blob = (f"{e.get('title','')} {e.get('summary','')} "
                    f"{e.get('itunes_subtitle','')}")
            published = util.parse_date(e.get("published") or e.get("updated"))
            if util.too_old(published, window_days):
                continue
            for fund, terms in targets:
                if not util.is_relevant(blob, terms):
                    continue
                item = _episode_items(e, fund)
                if not item["canonical_url"]:
                    continue
                item["author"] = name
                rows.append(item)
        stored += db.insert_items(rows)
        log.info("%s: %d episode(s) matched a tracked house", name, len(rows))
    return stored
