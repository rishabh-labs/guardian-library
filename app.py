"""Fund Library - a self-updating dashboard of fund manager videos, news and
documents for the products we track.

Run locally:   python app.py
Run in cloud:  gunicorn app:app
"""
import logging
import os
import threading
from datetime import timedelta
from functools import wraps

from flask import (Flask, flash, jsonify, redirect, render_template, request,
                   send_from_directory, session, url_for)

import analyse
import classify
import collectors
import config
import db

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("app")

app = Flask(__name__)
app.secret_key = config.SECRET_KEY
# Colleagues should sign in once, not on every browser restart.
app.permanent_session_lifetime = timedelta(days=30)

db.init()

KIND_LABELS = {"video": "Video", "podcast": "Podcast",
               "newsletter": "Newsletter", "document": "Document"}


def bootstrap_if_empty():
    """Seed a brand-new deployment from the fund list shipped with the code.

    Only fires on a genuinely empty database. The published copy ships with the
    collected library already in it, so this is a local convenience - the sheet
    is deliberately not in the repository, which is public.
    """
    if db.list_funds():
        return
    path = config.SEED_XLSX
    if not (path and os.path.exists(path)):
        log.warning("no funds and no seed sheet at %r - portal starts empty", path)
        return
    import import_lists
    import newsletter_sources
    log.info("empty database: seeding from %s", path)
    import_lists.run(path, False)
    newsletter_sources.apply()
    log.info("seeded %d fund(s)", len(db.list_funds()))


def refresh_cycle():
    """Collect, sort research from marketing, then summarise what's left.

    Classification runs before analysis on purpose: promos are excluded from
    summarising, so sorting first is what keeps the API bill down.
    """
    result = collectors.run_all()
    result["classified"] = classify.run_pending()
    if config.AUTO_ANALYSE:
        result["analysis"] = analyse.run_pending()
    return result


# ---------------------------------------------------------------- helpers

def admin_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        if not session.get("admin"):
            return redirect(url_for("login", next=request.path))
        return fn(*a, **kw)
    return wrapper


@app.context_processor
def inject_globals():
    return {"cfg": config}


# Pages anyone may reach without signing in: the sign-in page itself, the
# health check the host polls, and the stylesheet that renders the sign-in page.
PUBLIC_ENDPOINTS = {"login", "healthz", "static"}


@app.before_request
def require_team_password():
    """Gate the whole portal behind the shared team password when one is set.

    Only /admin was protected before, which was right for a laptop and wrong
    for a public URL - the shelves name the products held and exited and carry
    the team's own notes. With VIEWER_PASSWORD unset nothing changes, so local
    use stays frictionless.
    """
    if not config.VIEWER_PASSWORD:
        return None
    if request.endpoint in PUBLIC_ENDPOINTS:
        return None
    if session.get("viewer") or session.get("admin"):
        return None
    return redirect(url_for("login", next=request.full_path))


@app.after_request
def no_store_html(response):
    """Never let a browser cache a rendered page.

    The pages are generated per request from a database that changes on every
    refresh, so a cached copy is always wrong. Without this a stale shelf keeps
    showing filtered-out videos long after the filters changed, which looks
    exactly like the filters having stopped working.
    """
    if response.mimetype == "text/html":
        response.headers["Cache-Control"] = "no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


@app.template_filter("when")
def when(iso):
    """'12 Aug 2026' style, tolerant of a missing date."""
    if not iso:
        return "—"
    from dateutil import parser as dp
    try:
        return dp.parse(iso).strftime("%d %b %Y")
    except (ValueError, TypeError):
        return "—"


# ---------------------------------------------------------------- dashboard

@app.route("/")
def index():
    return shelf("active")


@app.get("/shelf/<bucket>")
def shelf(bucket):
    if bucket not in {b[0] for b in config.BUCKETS}:
        return redirect(url_for("index"))
    fund_id = request.args.get("fund", type=int)
    # The main library is the video/podcast shelf; newsletters have their own tab.
    kind = ["video", "podcast"]
    search = (request.args.get("q") or "").strip() or None
    unseen = request.args.get("unseen") == "1"
    starred = request.args.get("starred") == "1"
    # Promos are hidden unless asked for. Nothing is deleted - the toggle just
    # stops marketing crowding out the research.
    show_promo = request.args.get("promo") == "1" or not config.HIDE_PROMO
    # One toggle relaxes both shelf filters — short videos and other languages
    # are the same kind of "show me everything" request.
    show_all = request.args.get("all") == "1"
    # Our own videos are curated, so none of the shelf filters apply to them.
    # The 10-minute minimum exists to drop scraped clips; applied here it would
    # hide two thirds of what the team actually made, most of which is short
    # by design.
    unfiltered = bucket == "inhouse"
    min_duration = None if (show_all or unfiltered) else config.MIN_VIDEO_SECONDS
    english_only = config.ENGLISH_ONLY and not show_all and not unfiltered
    page = max(request.args.get("page", 1, type=int), 1)
    per_page = 60

    items = db.query_items(fund_id=fund_id, kind=kind, search=search,
                           unseen_only=unseen, starred_only=starred,
                           include_promo=show_promo,
                           min_duration=min_duration,
                           english_only=english_only,
                           manager_only=(config.MANAGER_ONLY and not show_all
                                         and not unfiltered),
                           bucket=bucket,
                           limit=per_page + 1, offset=(page - 1) * per_page)
    has_next = len(items) > per_page
    items = items[:per_page]

    return render_template(
        "library.html",
        items=items,
        funds=db.list_funds(bucket=bucket),
        bucket=bucket,
        buckets=config.BUCKETS,
        bucket_counts=db.bucket_counts(),
        unseen_counts=db.unseen_counts(),
        kind_labels=KIND_LABELS,
        last_run=db.last_run(),
        promo_hidden=db.promo_count(fund_id=fund_id, bucket=bucket),
        show_promo=show_promo,
        show_all=show_all,
        shelf_hidden=db.shelf_hidden_counts(
            fund_id=fund_id, bucket=bucket,
            min_duration=config.MIN_VIDEO_SECONDS,
            english_only=config.ENGLISH_ONLY,
            manager_only=config.MANAGER_ONLY),
        min_minutes=config.MIN_VIDEO_SECONDS // 60,
        # Newsletter summaries surface on the front page too, so the month's
        # reading is visible without switching tabs.
        nl_summaries=db.recent_newsletter_summaries(6),
        nl_counts=db.newsletter_counts(),
        insights=db.insights_for([i['id'] for i in items]),
        recent_insights=db.recent_insights(6),
        total_insights=db.total_insights(),
        # Kept as strings so they can be splatted straight back into url_for.
        filters={"fund": fund_id, "q": search or "",
                 "unseen": "1" if unseen else "", "starred": "1" if starred else "",
                 "promo": "1" if request.args.get("promo") == "1" else "",
                 "all": "1" if show_all else ""},
        page=page, has_next=has_next,
    )


@app.post("/item/<int:item_id>/<field>")
def flag(item_id, field):
    if field not in ("seen", "starred"):
        return jsonify(error="bad field"), 400
    value = 1 if request.json.get("value") else 0
    db.set_flag(item_id, field, value)
    return jsonify(ok=True)


@app.post("/item/<int:item_id>/reclassify")
def reclassify(item_id):
    """Manual override when the classifier gets one wrong."""
    target = request.json.get("content_type")
    if target not in ("research", "promo"):
        return jsonify(error="bad content_type"), 400
    db.set_content_type(item_id, target, "set by hand")
    return jsonify(ok=True, content_type=target)


@app.post("/item/<int:item_id>/insight")
def add_insight(item_id):
    """Anyone can add what they took from an item; everyone can read it."""
    data = request.json or {}
    body = (data.get("body") or "").strip()
    if not body:
        return jsonify(error="write something first"), 400
    if not db.get_item(item_id):
        return jsonify(error="no such item"), 404
    db.add_insight(item_id, data.get("author", ""), body)
    return jsonify(ok=True, insights=db.insights_for([item_id]).get(item_id, []))


@app.get("/item/<int:item_id>/insights")
def list_insights(item_id):
    return jsonify(insights=db.insights_for([item_id]).get(item_id, []))


@app.post("/insight/<int:insight_id>/delete")
def remove_insight(insight_id):
    db.delete_insight(insight_id)
    return jsonify(ok=True)


@app.post("/mark-all-seen")
def mark_all_seen():
    db.mark_all_seen(request.form.get("fund", type=int))
    return redirect(request.referrer or url_for("index"))


# ---------------------------------------------------------------- analysis

@app.get("/newsletters")
def newsletters():
    """The newsletter library, grouped by fund house."""
    period = request.args.get("period") or None
    search = (request.args.get("q") or "").strip() or None

    house = request.args.get("house") or None

    # Newsletters are not split across the three video shelves: a house
    # publishes one factsheet regardless of which of its strategies we hold.
    grouped, total = db.query_newsletters_by_house(
        period=period, search=search, house=house)
    houses = sorted(grouped)
    ids = [r["id"] for rows in grouped.values() for r in rows]

    return render_template(
        "newsletters.html",
        grouped=grouped, houses=houses,
        all_houses=db.newsletter_houses(),
        all_periods=db.newsletter_periods(),
        analysed=db.analysed_item_ids(),
        summaries=db.summaries_by_item(ids),
        insights=db.insights_for(ids),
        configured=analyse.configured()[0],
        filters={"house": house or "", "period": period or "", "q": search or ""},
        total=total,
    )


@app.get("/analysis")
def analysis():
    fund_id = request.args.get("fund", type=int)
    search = (request.args.get("q") or "").strip() or None
    page = max(request.args.get("page", 1, type=int), 1)
    per_page = 25

    rows = db.query_analyses(fund_id=fund_id, search=search,
                             limit=per_page + 1, offset=(page - 1) * per_page)
    has_next = len(rows) > per_page

    return render_template(
        "analysis.html",
        analyses=rows[:per_page],
        funds=db.list_funds(),
        stats=db.analysis_stats(),
        configured=analyse.configured()[0],
        model=config.ANALYSIS_MODEL,
        filters={"fund": fund_id, "q": search or ""},
        page=page, has_next=has_next,
    )


@app.post("/item/<int:item_id>/analyse")
def analyse_one(item_id):
    """Summarise a single item on demand, e.g. after a failed first attempt."""
    ok, why = analyse.configured()
    if not ok:
        return jsonify(error=why), 400
    item = db.get_item(item_id)
    if not item:
        return jsonify(error="no such item"), 404
    status = analyse.analyse_item(item)
    return jsonify(ok=True, status=status,
                   analysis=db.get_analysis(item_id))


@app.get("/item/<int:item_id>/analysis")
def analysis_json(item_id):
    a = db.get_analysis(item_id)
    return jsonify(a or {"status": "none"})


# ---------------------------------------------------------------- admin

@app.route("/login", methods=["GET", "POST"])
def login():
    """One page, two passwords.

    The team password opens the library read-only; the admin password also
    unlocks Admin. Colleagues only ever need the first one.
    """
    if request.method == "POST":
        session.permanent = True
        given = request.form.get("password", "")
        nxt = request.args.get("next")
        if given == config.ADMIN_PASSWORD:
            session["admin"] = True
            session["viewer"] = True
            return redirect(nxt or url_for("admin"))
        if config.VIEWER_PASSWORD and given == config.VIEWER_PASSWORD:
            session["viewer"] = True
            return redirect(nxt or url_for("index"))
        flash("Wrong password.", "error")
    return render_template("login.html")


@app.get("/logout")
def logout():
    session.pop("admin", None)
    session.pop("viewer", None)
    return redirect(url_for("index"))


@app.get("/admin")
@admin_required
def admin():
    funds = db.list_funds()
    inhouse_count = len(db.query_items(bucket="inhouse", limit=999))
    by_fund = {f["id"]: [] for f in funds}
    for s in db.list_sources():
        by_fund.setdefault(s["fund_id"], []).append(s)
    return render_template("admin.html", funds=funds, sources=by_fund,
                           source_kinds=collectors.SOURCE_KINDS,
                           last_run=db.last_run(),
                           inhouse_count=inhouse_count,
                           has_yt_key=bool(config.YOUTUBE_API_KEY))


@app.post("/admin/fund")
@admin_required
def save_fund():
    f = request.form
    db.upsert_fund(
        name=f["name"].strip(), house=f.get("house", "").strip(),
        managers=f.get("managers", "").strip(),
        category=f.get("category", "").strip(),
        match_terms=f.get("match_terms", "").strip(),
        active=1 if f.get("active") else 0,
        fund_id=f.get("fund_id", type=int) or None)
    flash(f"Saved {f['name']}.", "ok")
    return redirect(url_for("admin"))


@app.post("/admin/fund/<int:fund_id>/delete")
@admin_required
def remove_fund(fund_id):
    db.delete_fund(fund_id)
    flash("Fund and its sources removed.", "ok")
    return redirect(url_for("admin"))


@app.post("/admin/source")
@admin_required
def save_source():
    f = request.form
    db.add_source(f.get("fund_id", type=int), f["kind"], f["value"],
                  f.get("label", "").strip())
    flash("Source added.", "ok")
    return redirect(url_for("admin"))


@app.post("/admin/source/<int:source_id>/<action>")
@admin_required
def source_action(source_id, action):
    if action == "delete":
        db.delete_source(source_id)
    elif action == "toggle":
        db.toggle_source(source_id)
    return redirect(url_for("admin"))


@app.post("/admin/refresh")
@admin_required
def refresh_now():
    result = refresh_cycle()
    msg = (f"Refresh done — {result['new_items']} new item(s), "
           f"{result['ok']} source(s) ok, {result['failed']} failed.")
    reclassified = (result.get("classified") or {}).get("reclassified")
    if reclassified:
        msg += f" {reclassified} ambiguous video(s) sorted by Claude."
    if result.get("analysis"):
        a = result["analysis"]
        msg += (f" Analysis: {a['done']} summarised, {a['skipped']} skipped, "
                f"{a['failed']} failed.")
    flash(msg, "ok")
    return redirect(url_for("admin"))


@app.post("/admin/import")
@admin_required
def import_excel():
    """Upload the fund list spreadsheet; funds and their sources are wired up
    automatically from whatever columns it contains."""
    import os
    import tempfile

    import import_funds

    upload = request.files.get("file")
    if not upload or not upload.filename:
        flash("Choose an .xlsx file first.", "error")
        return redirect(url_for("admin"))

    fd, tmp = tempfile.mkstemp(suffix=".xlsx")
    os.close(fd)
    try:
        upload.save(tmp)
        count = import_funds.run(tmp, sheet=request.form.get("sheet") or None)
        flash(f"Imported {count} fund(s) from {upload.filename}. "
              f"Review the sources below, then hit Refresh now.", "ok")
    except Exception as exc:
        flash(f"Import failed — {type(exc).__name__}: {exc}", "error")
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    return redirect(url_for("admin"))


# ---------------------------------------------------------------- our videos

@app.get("/media/<path:filename>")
def media(filename):
    """Stream one of our own videos straight off the disk.

    send_from_directory answers Range requests, which is what lets a browser
    seek and start playing before the whole file arrives - without it a 255 MB
    video downloads in full before anything appears. The file is never copied
    or uploaded anywhere; it is read from MEDIA_DIR on each request, and the
    team password gate in before_request applies here like everywhere else.
    """
    return send_from_directory(config.MEDIA_DIR, filename, conditional=True)


@app.get("/watch/<int:item_id>")
def watch(item_id):
    """Player page for an in-house video, so it is watched inside the portal
    rather than dumped into the browser as a bare file."""
    item = db.get_item(item_id)
    if not item or not str(item["url"]).startswith("/media/"):
        return redirect(url_for("index"))
    db.set_flag(item_id, "seen", 1)
    return render_template(
        "watch.html", item=item,
        insights=db.insights_for([item_id]).get(item_id, []),
        last_run=db.last_run(), bucket="inhouse")


@app.post("/admin/scan-media")
@admin_required
def scan_media():
    """Pick up anything newly dropped into the media folder."""
    import import_media
    try:
        before = len(db.query_items(bucket="inhouse", limit=999))
        import_media.run()
        after = len(db.query_items(bucket="inhouse", limit=999))
        flash(f"Media folder scanned — {after} video(s) on the shelf, "
              f"{after - before} new.", "ok")
    except Exception as exc:
        flash(f"Scan failed: {type(exc).__name__}: {exc}", "error")
    return redirect(url_for("admin"))


@app.get("/healthz")
def healthz():
    return jsonify(ok=True, last_run=db.last_run())


# ---------------------------------------------------------------- scheduler

def start_scheduler():
    from apscheduler.schedulers.background import BackgroundScheduler
    sched = BackgroundScheduler(daemon=True, timezone="UTC")
    sched.add_job(refresh_cycle, "interval",
                  minutes=config.POLL_MINUTES, id="poll",
                  max_instances=1, coalesce=True)
    sched.start()
    log.info("scheduler started, polling every %d min", config.POLL_MINUTES)
    # Kick off one pass immediately so a fresh deploy has content.
    threading.Thread(target=refresh_cycle, daemon=True).start()


bootstrap_if_empty()

if config.ENABLE_SCHEDULER:
    start_scheduler()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(__import__("os").environ.get("PORT", 5055)),
            debug=False)
