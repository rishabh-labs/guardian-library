"""SQLite layer. Plain sqlite3 - the data model is small and an ORM would only
add deployment weight."""
import html
import json
import os
import sqlite3
from datetime import datetime, timezone

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS funds (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL UNIQUE,   -- product name, e.g. "Marcellus CCP"
    house         TEXT NOT NULL DEFAULT '',
    managers      TEXT NOT NULL DEFAULT '',  -- comma separated
    category      TEXT NOT NULL DEFAULT '',  -- PMS / AIF / MF
    match_terms   TEXT NOT NULL DEFAULT '',  -- extra keywords for relevance check
    active        INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sources (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    fund_id       INTEGER NOT NULL REFERENCES funds(id) ON DELETE CASCADE,
    kind          TEXT NOT NULL,   -- youtube_channel | youtube_search | news_search | rss | page_watch
    value         TEXT NOT NULL,   -- channel id, query string, feed url or page url
    label         TEXT NOT NULL DEFAULT '',
    enabled       INTEGER NOT NULL DEFAULT 1,
    last_checked  TEXT,
    last_status   TEXT NOT NULL DEFAULT '',
    UNIQUE(fund_id, kind, value)
);

CREATE TABLE IF NOT EXISTS items (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    fund_id       INTEGER NOT NULL REFERENCES funds(id) ON DELETE CASCADE,
    source_id     INTEGER REFERENCES sources(id) ON DELETE SET NULL,
    kind          TEXT NOT NULL,   -- video | news | document
    title         TEXT NOT NULL,
    url           TEXT NOT NULL,
    canonical_url TEXT NOT NULL,   -- url stripped of tracking params, used for dedupe
    thumbnail     TEXT NOT NULL DEFAULT '',
    author        TEXT NOT NULL DEFAULT '',
    summary       TEXT NOT NULL DEFAULT '',
    published_at  TEXT,
    fetched_at    TEXT NOT NULL,
    seen          INTEGER NOT NULL DEFAULT 0,
    starred       INTEGER NOT NULL DEFAULT 0,
    duration_secs INTEGER,          -- videos only; NULL when unknown
    content_type  TEXT NOT NULL DEFAULT 'unclassified',  -- research | promo
    classify_why  TEXT NOT NULL DEFAULT '',
    UNIQUE(fund_id, canonical_url)
);

CREATE INDEX IF NOT EXISTS idx_items_published ON items(published_at DESC);
CREATE INDEX IF NOT EXISTS idx_items_fund ON items(fund_id);
CREATE INDEX IF NOT EXISTS idx_items_kind ON items(kind);

CREATE TABLE IF NOT EXISTS analyses (
    item_id       INTEGER PRIMARY KEY REFERENCES items(id) ON DELETE CASCADE,
    status        TEXT NOT NULL,   -- pending | done | skipped | failed
    source_kind   TEXT NOT NULL DEFAULT '',  -- transcript | article | pdf
    source_chars  INTEGER NOT NULL DEFAULT 0,
    headline      TEXT NOT NULL DEFAULT '',
    summary       TEXT NOT NULL DEFAULT '',
    highlights    TEXT NOT NULL DEFAULT '[]',  -- json array of strings
    portfolio_actions TEXT NOT NULL DEFAULT '[]',
    outlook       TEXT NOT NULL DEFAULT '',
    numbers       TEXT NOT NULL DEFAULT '[]',
    model         TEXT NOT NULL DEFAULT '',
    error         TEXT NOT NULL DEFAULT '',
    created_at    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_analyses_status ON analyses(status);

CREATE TABLE IF NOT EXISTS insights (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id       INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    author        TEXT NOT NULL,
    body          TEXT NOT NULL,
    created_at    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_insights_item ON insights(item_id);

CREATE TABLE IF NOT EXISTS runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at    TEXT NOT NULL,
    finished_at   TEXT,
    new_items     INTEGER NOT NULL DEFAULT 0,
    sources_ok    INTEGER NOT NULL DEFAULT 0,
    sources_fail  INTEGER NOT NULL DEFAULT 0,
    detail        TEXT NOT NULL DEFAULT ''
);
"""


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect():
    os.makedirs(config.DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


# Columns added after the first release. Applied on every start so an existing
# database picks them up without a manual migration step.
LATER_COLUMNS = [
    ("items", "duration_secs", "INTEGER"),
    ("items", "content_type", "TEXT NOT NULL DEFAULT 'unclassified'"),
    ("items", "classify_why", "TEXT NOT NULL DEFAULT ''"),
    # 'YYYY-MM' for newsletters, so they can be grouped by month.
    ("items", "period", "TEXT NOT NULL DEFAULT ''"),
    # ISO language code ('en', 'hi', 'te', ...) or '' when undetermined.
    ("items", "language", "TEXT NOT NULL DEFAULT ''"),
    ("items", "language_why", "TEXT NOT NULL DEFAULT ''"),
    # Optional regexes narrowing what a source accepts. A house often publishes
    # several document families side by side (factsheet, distributor variants,
    # a different product); these pick out the one that matters.
    ("sources", "include_re", "TEXT NOT NULL DEFAULT ''"),
    ("sources", "exclude_re", "TEXT NOT NULL DEFAULT ''"),
    # Keep a single document per month for sources that publish the same
    # factsheet several times over (one per distributor).
    ("sources", "one_per_period", "INTEGER NOT NULL DEFAULT 0"),
    # Which shelf a tracked entity belongs to: a strategy we hold ('active'),
    # one we have exited ('inactive'), or a manager followed for learning
    # rather than exposure ('knowledge').
    ("funds", "bucket", "TEXT NOT NULL DEFAULT 'active'"),
    # Is the fund manager actually in this video, or is someone else talking
    # about the fund? 'manager' | 'third_party' | '' when not yet judged.
    ("items", "speaker", "TEXT NOT NULL DEFAULT ''"),
    ("items", "speaker_why", "TEXT NOT NULL DEFAULT ''"),
]

# Indexes over later-added columns. These cannot live in SCHEMA: executescript
# runs it in one go, so the index would be created before the ALTER that adds
# the column it indexes.
LATER_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_items_content_type ON items(content_type)",
    "CREATE INDEX IF NOT EXISTS idx_items_period ON items(period)",
    "CREATE INDEX IF NOT EXISTS idx_items_language ON items(language)",
    "CREATE INDEX IF NOT EXISTS idx_items_speaker ON items(speaker)",
    "CREATE INDEX IF NOT EXISTS idx_funds_bucket ON funds(bucket)",
]


def init():
    conn = connect()
    with conn:
        conn.executescript(SCHEMA)
        for table, column, decl in LATER_COLUMNS:
            existing = {r["name"] for r in
                        conn.execute(f"PRAGMA table_info({table})")}
            if column not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
        for statement in LATER_INDEXES:
            conn.execute(statement)
    conn.close()


# ---------------------------------------------------------------- funds

def list_funds(active_only=False, bucket=None):
    conn = connect()
    q = "SELECT * FROM funds WHERE 1=1"
    args = []
    if active_only:
        q += " AND active = 1"
    if bucket:
        q += " AND bucket = ?"
        args.append(bucket)
    q += " ORDER BY house, name"
    rows = conn.execute(q, args).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_fund(fund_id):
    conn = connect()
    row = conn.execute("SELECT * FROM funds WHERE id = ?", (fund_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def upsert_fund(name, house="", managers="", category="", match_terms="",
                active=1, fund_id=None, bucket=None):
    conn = connect()
    with conn:
        if fund_id:
            conn.execute(
                """UPDATE funds SET name=?, house=?, managers=?, category=?,
                   match_terms=?, active=? WHERE id=?""",
                (name, house, managers, category, match_terms, active, fund_id))
            if bucket:
                conn.execute("UPDATE funds SET bucket=? WHERE id=?",
                             (bucket, fund_id))
            return fund_id
        cur = conn.execute(
            """INSERT INTO funds (name, house, managers, category, match_terms,
               active, bucket, created_at) VALUES (?,?,?,?,?,?,?,?)
               ON CONFLICT(name) DO UPDATE SET
                 house=excluded.house, managers=excluded.managers,
                 category=excluded.category, match_terms=excluded.match_terms,
                 bucket=excluded.bucket""",
            (name, house, managers, category, match_terms, active,
             bucket or "active", now_iso()))
        if cur.lastrowid:
            return cur.lastrowid
        row = conn.execute("SELECT id FROM funds WHERE name=?", (name,)).fetchone()
        return row["id"]
    conn.close()


def delete_fund(fund_id):
    conn = connect()
    with conn:
        conn.execute("DELETE FROM funds WHERE id = ?", (fund_id,))
    conn.close()


# ---------------------------------------------------------------- sources

def list_sources(fund_id=None, enabled_only=False):
    conn = connect()
    q = ("SELECT s.*, f.name AS fund_name, f.managers, f.match_terms, f.house "
         "FROM sources s JOIN funds f ON f.id = s.fund_id WHERE 1=1")
    args = []
    if fund_id:
        q += " AND s.fund_id = ?"
        args.append(fund_id)
    if enabled_only:
        q += " AND s.enabled = 1 AND f.active = 1"
    q += " ORDER BY f.name, s.kind"
    rows = conn.execute(q, args).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_source(fund_id, kind, value, label="", include_re="", exclude_re="",
               one_per_period=0):
    conn = connect()
    with conn:
        conn.execute(
            """INSERT INTO sources (fund_id, kind, value, label,
                                    include_re, exclude_re, one_per_period)
               VALUES (?,?,?,?,?,?,?)
               ON CONFLICT(fund_id, kind, value) DO UPDATE SET
                 label = excluded.label,
                 include_re = excluded.include_re,
                 exclude_re = excluded.exclude_re,
                 one_per_period = excluded.one_per_period""",
            (fund_id, kind, value.strip(), label, include_re, exclude_re,
             int(one_per_period)))
    conn.close()


def delete_source(source_id):
    conn = connect()
    with conn:
        conn.execute("DELETE FROM sources WHERE id = ?", (source_id,))
    conn.close()


def toggle_source(source_id):
    conn = connect()
    with conn:
        conn.execute(
            "UPDATE sources SET enabled = 1 - enabled WHERE id = ?", (source_id,))
    conn.close()


def mark_source_status(source_id, status):
    """Record a status WITHOUT marking the source as polled.

    Used when a source couldn't run at all (e.g. no API key yet). Setting
    last_checked would make its first real poll use the 1-month incremental
    window instead of the 6-month backfill it never got.
    """
    conn = connect()
    with conn:
        conn.execute("UPDATE sources SET last_status = ? WHERE id = ?",
                     (status[:200], source_id))
    conn.close()


def mark_source_checked(source_id, status):
    conn = connect()
    with conn:
        conn.execute(
            "UPDATE sources SET last_checked = ?, last_status = ? WHERE id = ?",
            (now_iso(), status[:200], source_id))
    conn.close()


# ---------------------------------------------------------------- items

def insert_items(rows):
    """rows: list of dicts. Returns count of genuinely new rows.

    Feed text arrives HTML-escaped - YouTube's Atom feed sends
    "Isn&#39;t" - and Jinja escapes again on the way out, so the entity would
    show up literally on the page. Decode once here, at the one point every
    collector funnels through.
    """
    if not rows:
        return 0
    for r in rows:
        for field in ("title", "author", "summary"):
            if r.get(field):
                r[field] = html.unescape(r[field])
    conn = connect()
    new = 0
    with conn:
        for r in rows:
            cur = conn.execute(
                """INSERT OR IGNORE INTO items
                   (fund_id, source_id, kind, title, url, canonical_url,
                    thumbnail, author, summary, published_at, fetched_at,
                    period)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (r["fund_id"], r.get("source_id"), r["kind"], r["title"],
                 r["url"], r["canonical_url"], r.get("thumbnail", ""),
                 r.get("author", ""), r.get("summary", ""),
                 r.get("published_at"), now_iso(), r.get("period", "")))
            new += cur.rowcount
    conn.close()
    return new


def get_item(item_id):
    conn = connect()
    row = conn.execute(
        """SELECT i.*, f.name AS fund_name, f.house, f.managers
           FROM items i JOIN funds f ON f.id = i.fund_id
           WHERE i.id = ?""", (item_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def query_items(fund_id=None, kind=None, search=None, unseen_only=False,
                starred_only=False, include_promo=True, min_duration=None,
                english_only=False, manager_only=False, bucket=None,
                limit=100, offset=0):
    conn = connect()
    # Two strategies of one house usually share a channel, so a single webinar
    # is stored once per fund and the shelf showed it twice. Collapse anything
    # from the same house, in the same month, of exactly the same length and
    # under the same title into one card.
    #
    # The title is part of the key because length alone is not unique: two
    # different Nilesh Shah interviews published the same day both ran 1528
    # seconds, and keying on house/month/length merged them into one. Rows with
    # no known duration key on their own id so they never collapse at all.
    DUPE_KEY = ("CASE WHEN i.duration_secs > 0 THEN "
                "f.house || '|' || substr(COALESCE(i.published_at, ''), 1, 7) "
                "|| '|' || i.duration_secs || '|' || lower(i.title) "
                "ELSE 'id:' || i.id END")
    q = ("SELECT i.*, f.name AS fund_name, f.house, f.category, f.bucket, "
         f"{DUPE_KEY} AS dupe_key "
         "FROM items i JOIN funds f ON f.id = i.fund_id WHERE 1=1")
    args = []
    if bucket:
        q += " AND f.bucket = ?"
        args.append(bucket)
    if manager_only:
        # Keep the manager's own content; drop other people's videos about the
        # fund. Unjudged rows ('') are kept so a classifier gap never empties
        # the shelf.
        q += " AND (i.speaker != 'third_party' OR i.starred = 1)"
    if not include_promo:
        # Starred items always show - an explicit human call beats the classifier.
        q += " AND (i.content_type != 'promo' OR i.starred = 1)"
    if min_duration:
        # Videos only: podcasts are judged on content, not runtime. A video with
        # no known duration is kept rather than hidden - a failed metadata
        # lookup shouldn't silently drop a real video.
        q += (" AND (i.kind != 'video' OR i.duration_secs IS NULL"
              "      OR i.duration_secs >= ? OR i.starred = 1)")
        args.append(min_duration)
    if english_only:
        q += " AND (i.language IN ('', 'en') OR i.starred = 1)"
    if fund_id:
        q += " AND i.fund_id = ?"
        args.append(fund_id)
    if kind:
        # Accepts a single kind or a list, so the video shelf can show videos
        # and podcasts together.
        kinds = [kind] if isinstance(kind, str) else list(kind)
        q += f" AND i.kind IN ({','.join('?' * len(kinds))})"
        args.extend(kinds)
    if search:
        q += " AND (i.title LIKE ? OR i.summary LIKE ? OR f.name LIKE ?)"
        like = f"%{search}%"
        args += [like, like, like]
    if unseen_only:
        q += " AND i.seen = 0"
    if starred_only:
        q += " AND i.starred = 1"
    # Keep one row per duplicate group. The lowest fund_id wins so the card is
    # always attributed to the same strategy rather than flipping between
    # them; also_count says how many other strategies carry the same video.
    q = (f"SELECT * FROM (SELECT *, "
         "ROW_NUMBER() OVER (PARTITION BY dupe_key ORDER BY fund_id, id) AS rn, "
         "COUNT(*) OVER (PARTITION BY dupe_key) - 1 AS also_count, "
         "group_concat(fund_name, ', ') OVER (PARTITION BY dupe_key) AS also_funds "
         f"FROM ({q})) WHERE rn = 1"
         " ORDER BY COALESCE(published_at, fetched_at) DESC LIMIT ? OFFSET ?")
    args += [limit, offset]
    rows = conn.execute(q, args).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def count_items(**kw):
    kw.pop("limit", None)
    kw.pop("offset", None)
    return len(query_items(limit=100000, **kw))


def promo_count(fund_id=None, bucket=None):
    """How many items the promo filter is currently holding back."""
    conn = connect()
    q = ("SELECT COUNT(*) c FROM items i JOIN funds f ON f.id = i.fund_id "
         "WHERE i.content_type = 'promo' AND i.starred = 0")
    args = []
    if fund_id:
        q += " AND i.fund_id = ?"
        args.append(fund_id)
    if bucket:
        q += " AND f.bucket = ?"
        args.append(bucket)
    row = conn.execute(q, args).fetchone()
    conn.close()
    return row["c"]


def shelf_hidden_counts(fund_id=None, min_duration=None, english_only=False,
                        manager_only=False, bucket=None):
    """What each shelf filter is holding back, so the UI can say so.

    Counted independently: an item can be both short and non-English, so these
    do not sum to the total hidden.
    """
    conn = connect()
    base = ("FROM items i JOIN funds f ON f.id = i.fund_id "
            "WHERE i.kind IN ('video','podcast') AND i.starred = 0 "
            "AND i.content_type != 'promo'")
    args = []
    if fund_id:
        base += " AND i.fund_id = ?"
        args.append(fund_id)
    if bucket:
        base += " AND f.bucket = ?"
        args.append(bucket)

    short = 0
    if min_duration:
        short = conn.execute(
            f"SELECT COUNT(*) c {base} AND i.kind = 'video' "
            f"AND i.duration_secs IS NOT NULL AND i.duration_secs < ?",
            args + [min_duration]).fetchone()["c"]

    other_lang = 0
    if english_only:
        other_lang = conn.execute(
            f"SELECT COUNT(*) c {base} AND i.language NOT IN ('', 'en')",
            args).fetchone()["c"]

    unknown = conn.execute(
        f"SELECT COUNT(*) c {base} AND i.kind = 'video' AND i.duration_secs IS NULL",
        args).fetchone()["c"]
    third_party = 0
    if manager_only:
        third_party = conn.execute(
            f"SELECT COUNT(*) c {base} AND i.speaker = 'third_party'",
            args).fetchone()["c"]

    conn.close()
    return {"short": short, "other_language": other_lang,
            "unknown_duration": unknown, "third_party": third_party}


def bucket_counts():
    """How many items each shelf would show, for the nav badges."""
    import config
    out = {}
    for key, _label, _desc in config.BUCKETS:
        out[key] = len(query_items(
            kind=["video", "podcast"], bucket=key, include_promo=False,
            min_duration=config.MIN_VIDEO_SECONDS,
            english_only=config.ENGLISH_ONLY,
            manager_only=config.MANAGER_ONLY, limit=100000))
    return out


def query_newsletters_by_house(period=None, search=None, house=None):
    """Newsletters grouped by fund house rather than by month.

    Houses, not strategies: a house publishes one factsheet whether we hold one
    of its funds or three, so the shelf is organised the way the documents are.
    """
    conn = connect()
    q = ("SELECT i.*, f.name AS fund_name, f.house, f.bucket "
         "FROM items i JOIN funds f ON f.id = i.fund_id "
         "WHERE i.kind IN ('newsletter','document')")
    args = []
    if period:
        q += " AND i.period = ?"
        args.append(period)
    if house:
        q += " AND f.house = ?"
        args.append(house)
    if search:
        q += " AND (i.title LIKE ? OR f.name LIKE ? OR f.house LIKE ?)"
        args += [f"%{search}%"] * 3
    q += " ORDER BY f.house, i.period DESC, i.title"
    rows = [dict(r) for r in conn.execute(q, args).fetchall()]
    conn.close()

    grouped = {}
    for r in rows:
        grouped.setdefault(r["house"] or r["fund_name"], []).append(r)
    return grouped, len(rows)


def newsletter_houses():
    conn = connect()
    rows = conn.execute(
        "SELECT DISTINCT f.house FROM items i JOIN funds f ON f.id = i.fund_id "
        "WHERE i.kind IN ('newsletter','document') AND f.house != '' "
        "ORDER BY f.house").fetchall()
    conn.close()
    return [r["house"] for r in rows]


def language_breakdown():
    """Languages present on the video shelf, for the Admin page."""
    conn = connect()
    rows = conn.execute(
        "SELECT language, COUNT(*) c FROM items "
        "WHERE kind IN ('video','podcast') GROUP BY language ORDER BY c DESC"
    ).fetchall()
    conn.close()
    return {(r["language"] or "unknown"): r["c"] for r in rows}


def set_content_type(item_id, content_type, why=""):
    conn = connect()
    with conn:
        conn.execute(
            "UPDATE items SET content_type = ?, classify_why = ? WHERE id = ?",
            (content_type, why[:300], item_id))
    conn.close()


def set_flag(item_id, field, value):
    assert field in ("seen", "starred")
    conn = connect()
    with conn:
        conn.execute(f"UPDATE items SET {field} = ? WHERE id = ?", (value, item_id))
    conn.close()


def mark_all_seen(fund_id=None):
    conn = connect()
    with conn:
        if fund_id:
            conn.execute("UPDATE items SET seen = 1 WHERE fund_id = ?", (fund_id,))
        else:
            conn.execute("UPDATE items SET seen = 1")
    conn.close()


def unseen_counts():
    conn = connect()
    rows = conn.execute(
        "SELECT fund_id, COUNT(*) c FROM items WHERE seen = 0 GROUP BY fund_id"
    ).fetchall()
    conn.close()
    return {r["fund_id"]: r["c"] for r in rows}


# ---------------------------------------------------------------- analyses

def get_analysis(item_id):
    conn = connect()
    row = conn.execute("SELECT * FROM analyses WHERE item_id = ?",
                       (item_id,)).fetchone()
    conn.close()
    if not row:
        return None
    a = dict(row)
    for field in ("highlights", "portfolio_actions", "numbers"):
        try:
            a[field] = json.loads(a[field] or "[]")
        except json.JSONDecodeError:
            a[field] = []
    return a


def save_analysis(item_id, status, **kw):
    conn = connect()
    with conn:
        conn.execute(
            """INSERT INTO analyses (item_id, status, source_kind, source_chars,
                 headline, summary, highlights, portfolio_actions, outlook,
                 numbers, model, error, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(item_id) DO UPDATE SET
                 status=excluded.status, source_kind=excluded.source_kind,
                 source_chars=excluded.source_chars, headline=excluded.headline,
                 summary=excluded.summary, highlights=excluded.highlights,
                 portfolio_actions=excluded.portfolio_actions,
                 outlook=excluded.outlook, numbers=excluded.numbers,
                 model=excluded.model, error=excluded.error,
                 created_at=excluded.created_at""",
            (item_id, status, kw.get("source_kind", ""),
             kw.get("source_chars", 0), kw.get("headline", ""),
             kw.get("summary", ""),
             json.dumps(kw.get("highlights", [])),
             json.dumps(kw.get("portfolio_actions", [])),
             kw.get("outlook", ""), json.dumps(kw.get("numbers", [])),
             kw.get("model", ""), str(kw.get("error", ""))[:1000], now_iso()))
    conn.close()


def items_needing_analysis(limit=25):
    """New items with no analysis row yet, newest first.

    Promos are excluded - there is no point paying to summarise an NFO
    countdown, and the Analysis tab should read as research only.
    """
    conn = connect()
    rows = conn.execute(
        """SELECT i.*, f.name AS fund_name FROM items i
           JOIN funds f ON f.id = i.fund_id
           LEFT JOIN analyses a ON a.item_id = i.id
           WHERE a.item_id IS NULL AND i.content_type != 'promo'
           ORDER BY COALESCE(i.published_at, i.fetched_at) DESC
           LIMIT ?""", (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def query_newsletters(fund_id=None, period=None, search=None, limit=2000):
    """Newsletters, newest month first."""
    conn = connect()
    q = ("SELECT i.*, f.name AS fund_name, f.house "
         "FROM items i JOIN funds f ON f.id = i.fund_id "
         "WHERE i.kind IN ('newsletter','document')")
    args = []
    if fund_id:
        q += " AND i.fund_id = ?"
        args.append(fund_id)
    if period:
        q += " AND i.period = ?"
        args.append(period)
    if search:
        q += " AND (i.title LIKE ? OR f.name LIKE ?)"
        args += [f"%{search}%"] * 2
    q += " ORDER BY i.period DESC, f.name, i.title LIMIT ?"
    args.append(limit)
    rows = conn.execute(q, args).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def newsletter_periods():
    conn = connect()
    rows = conn.execute(
        "SELECT DISTINCT period FROM items "
        "WHERE kind IN ('newsletter','document') AND period != '' "
        "ORDER BY period DESC").fetchall()
    conn.close()
    return [r["period"] for r in rows]


def analysed_item_ids():
    """Item ids that already have a completed summary."""
    conn = connect()
    rows = conn.execute(
        "SELECT item_id FROM analyses WHERE status = 'done'").fetchall()
    conn.close()
    return {r["item_id"] for r in rows}


def summaries_by_item(item_ids=None):
    """{item_id: {headline, summary, highlights}} for completed summaries."""
    conn = connect()
    q = ("SELECT item_id, headline, summary, highlights, portfolio_actions "
         "FROM analyses WHERE status = 'done'")
    args = []
    if item_ids:
        ids = list(item_ids)
        q += f" AND item_id IN ({','.join('?' * len(ids))})"
        args = ids
    rows = conn.execute(q, args).fetchall()
    conn.close()
    out = {}
    for r in rows:
        d = dict(r)
        for field in ("highlights", "portfolio_actions"):
            try:
                d[field] = json.loads(d[field] or "[]")
            except json.JSONDecodeError:
                d[field] = []
        out[r["item_id"]] = d
    return out


def recent_newsletter_summaries(limit=6):
    """Newest summarised newsletters, for the front page panel."""
    conn = connect()
    rows = conn.execute(
        """SELECT a.headline, a.summary, i.id, i.title, i.url, i.period,
                  f.name AS fund_name
           FROM analyses a
           JOIN items i ON i.id = a.item_id
           JOIN funds f ON f.id = i.fund_id
           WHERE a.status = 'done' AND i.kind IN ('newsletter','document')
           ORDER BY i.period DESC, a.created_at DESC
           LIMIT ?""", (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def newsletter_counts():
    """Front-page panel figures.

    The archive total is deliberately not the headline: older newsletters are
    kept for reference and are not meant to be summarised in bulk. What matters
    is the latest month and how much of it is still unread.
    """
    conn = connect()
    total = conn.execute(
        "SELECT COUNT(*) c FROM items WHERE kind IN ('newsletter','document')"
    ).fetchone()["c"]
    done = conn.execute(
        """SELECT COUNT(*) c FROM analyses a JOIN items i ON i.id = a.item_id
           WHERE a.status = 'done' AND i.kind IN ('newsletter','document')"""
    ).fetchone()["c"]
    latest = conn.execute(
        "SELECT MAX(period) p FROM items WHERE kind IN ('newsletter','document')"
    ).fetchone()["p"]

    this_month = pending = 0
    if latest:
        this_month = conn.execute(
            "SELECT COUNT(*) c FROM items WHERE kind IN ('newsletter','document') "
            "AND period = ?", (latest,)).fetchone()["c"]
        pending = conn.execute(
            """SELECT COUNT(*) c FROM items i
               LEFT JOIN analyses a ON a.item_id = i.id AND a.status = 'done'
               WHERE i.kind IN ('newsletter','document') AND i.period = ?
                 AND a.item_id IS NULL""", (latest,)).fetchone()["c"]
    conn.close()
    return {"total": total, "summarised": done, "latest_period": latest,
            "this_month": this_month, "pending_this_month": pending}


def query_analyses(fund_id=None, kind=None, search=None, limit=50, offset=0):
    conn = connect()
    q = ("SELECT a.*, i.title, i.url, i.kind, i.thumbnail, i.author, "
         "       i.published_at, i.fetched_at, i.starred, i.seen, "
         "       f.name AS fund_name, f.house "
         "FROM analyses a "
         "JOIN items i ON i.id = a.item_id "
         "JOIN funds f ON f.id = i.fund_id "
         "WHERE a.status = 'done'")
    args = []
    if fund_id:
        q += " AND i.fund_id = ?"
        args.append(fund_id)
    if kind:
        q += " AND i.kind = ?"
        args.append(kind)
    if search:
        q += (" AND (i.title LIKE ? OR a.summary LIKE ? OR a.highlights LIKE ? "
              "OR f.name LIKE ?)")
        like = f"%{search}%"
        args += [like, like, like, like]
    q += (" ORDER BY COALESCE(i.published_at, i.fetched_at) DESC "
          "LIMIT ? OFFSET ?")
    args += [limit, offset]
    rows = conn.execute(q, args).fetchall()
    conn.close()
    out = []
    for r in rows:
        a = dict(r)
        for field in ("highlights", "portfolio_actions", "numbers"):
            try:
                a[field] = json.loads(a[field] or "[]")
            except json.JSONDecodeError:
                a[field] = []
        out.append(a)
    return out


def analysis_stats():
    conn = connect()
    rows = conn.execute(
        "SELECT status, COUNT(*) c FROM analyses GROUP BY status").fetchall()
    conn.close()
    return {r["status"]: r["c"] for r in rows}


# ---------------------------------------------------------------- insights

def add_insight(item_id, author, body):
    """Record what someone took away from an item.

    The team is small and everyone is named, so a typed name is enough - this
    is a shared notebook, not an access-controlled system.
    """
    author = (author or "").strip()[:80] or "Anonymous"
    body = (body or "").strip()[:4000]
    if not body:
        return None
    conn = connect()
    with conn:
        cur = conn.execute(
            "INSERT INTO insights (item_id, author, body, created_at) "
            "VALUES (?,?,?,?)", (item_id, author, body, now_iso()))
        new_id = cur.lastrowid
    conn.close()
    return new_id


def delete_insight(insight_id):
    conn = connect()
    with conn:
        conn.execute("DELETE FROM insights WHERE id = ?", (insight_id,))
    conn.close()


def insights_for(item_ids):
    """{item_id: [insight, ...]} oldest first, so a thread reads top to bottom."""
    ids = [i for i in (item_ids or []) if i]
    if not ids:
        return {}
    conn = connect()
    rows = conn.execute(
        f"SELECT * FROM insights WHERE item_id IN ({','.join('?' * len(ids))}) "
        f"ORDER BY created_at", ids).fetchall()
    conn.close()
    out = {}
    for r in rows:
        out.setdefault(r["item_id"], []).append(dict(r))
    return out


def insight_counts():
    conn = connect()
    rows = conn.execute(
        "SELECT item_id, COUNT(*) c FROM insights GROUP BY item_id").fetchall()
    conn.close()
    return {r["item_id"]: r["c"] for r in rows}


def recent_insights(limit=8):
    """Newest notes across the whole library, for the landing shelf."""
    conn = connect()
    rows = conn.execute(
        """SELECT n.*, i.title, i.url, i.kind, f.name AS fund_name
           FROM insights n
           JOIN items i ON i.id = n.item_id
           JOIN funds f ON f.id = i.fund_id
           ORDER BY n.created_at DESC LIMIT ?""", (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def total_insights():
    conn = connect()
    n = conn.execute("SELECT COUNT(*) c FROM insights").fetchone()["c"]
    conn.close()
    return n


# ---------------------------------------------------------------- runs

def start_run():
    conn = connect()
    with conn:
        cur = conn.execute("INSERT INTO runs (started_at) VALUES (?)", (now_iso(),))
        rid = cur.lastrowid
    conn.close()
    return rid


def finish_run(run_id, new_items, ok, fail, detail=""):
    conn = connect()
    with conn:
        conn.execute(
            """UPDATE runs SET finished_at=?, new_items=?, sources_ok=?,
               sources_fail=?, detail=? WHERE id=?""",
            (now_iso(), new_items, ok, fail, json.dumps(detail)[:4000], run_id))
    conn.close()


def last_run():
    conn = connect()
    row = conn.execute(
        "SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    return dict(row) if row else None
