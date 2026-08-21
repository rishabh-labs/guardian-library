"""Separate genuine fund manager commentary from marketing.

A fund house's YouTube channel is mostly promotion: NFO countdowns, festival
greetings, award announcements and 15-second Shorts. Roughly two-thirds of what
comes in is not research. This module tags each video so the dashboard can
default to hiding it.

Three signals, cheapest first:

1. Title rules      - free, deterministic, catches the obvious cases
2. Video duration   - needs the YouTube key, 1 quota unit per 50 videos
3. Claude, on the   - only for the genuinely ambiguous middle, sent as one
   remaining cases     batch. Runs through providers.py, so with Claude Code
                       signed in locally it costs nothing

Anything still unresolved is left as research rather than hidden. Wrongly
hiding a real manager video is far worse than letting a promo through.
"""
import logging
import re

import config
import db
import language
import providers
import speaker
from collectors import util

log = logging.getLogger("classify")

VIDEOS_API = "https://www.googleapis.com/youtube/v3/videos"

# --- title rules --------------------------------------------------------
# Weights are deliberately blunt: >= +2 is research, <= -2 is promo, and the
# band between them goes to duration and then to the model.

PROMO_RULES = [
    # NFO / scheme launch marketing and its countdown pattern.
    (-4, r"\bnfo\b|new fund offer|scheme (opens|closes)"),
    (-4, r"\b\d+\s*days?\s*(left|to go)\b|closing today|closes tomorrow"
         r"|last day to invest|closes on\b"),
    (-3, r"\binvest now\b|\bsubscribe now\b|\bregister now\b|\bapply now\b"
         r"|download the app|open (an )?account"),
    # Festival and courtesy posts.
    (-4, r"happy (diwali|new year|holi|dussehra|navratri|eid|christmas|onam)"
         r"|festive|greetings|best wishes|\bwishes\b"
         r"|independence day|republic day|women'?s day|teacher'?s day"),
    # Corporate self-congratulation.
    (-3, r"congratulations|felicitat|\baward(s|ed)?\b|\branked\b|\bwinner\b"
         r"|anniversary|years of excellence|milestone|crosses (rs|₹|inr)"),
    # Filler formats.
    (-3, r"#shorts?\b|\bshorts\b|did you know|fun fact|quiz|myth buster"),
    (-2, r"coming soon|stay tuned|watch (the )?full|teaser|glimpse|highlights? reel"),
    (-2, r"\bad\b|advertisement|campaign|brand film|jingle"),
    # Retail product and how-to content. A fund house's own channel carries a
    # lot of this - credit cards, account opening, app walkthroughs - and it is
    # not research however official the channel is.
    (-4, r"credit card|debit card|zero balance|savings account|\bfd\b|"
         r"fixed deposit|net ?banking|\batm\b|\bkyc\b|\bupi\b|loan against|"
         r"personal loan|home loan|insurance policy|open (an )?account|"
         r"how to (open|apply|invest|start|stop|withdraw|redeem|register|link)"),
    # Hindi/Hinglish tutorial phrasing, which is how most of it is titled.
    (-4, r"kaise|kaise kare|kaise kare\b|कैसे|तरीका|पूरी जानकारी|"
         r"\bstep by step\b|full details|complete guide|tutorial"),
    # Stock-tip and target-price channels talking about the AMC as a *stock*,
    # not the AMC's own research.
    # -4 so it outweighs the +2 that words like "analysis" earn: a title such
    # as "SHARE TARGET ANALYSIS | multibagger" is a tip sheet, not research.
    (-4, r"share (price )?target|stock target|target price|buy or sell|"
         r"multibagger|breakout|technical (analysis|picks|view)|intraday|"
         r"share news today|stock in action|\bcmp\b"),
]

# Event soundbite clips. A conference throws off a dozen 40-second cuts titled
# "X reflects on...", "X's key takeaway from...". Handled separately from the
# list above because it also has to cancel the manager-name bonus: the manager
# being named in a soundbite title is the norm, not a sign of substance.
SOUNDBITE = re.compile(
    r"reflects? on|shares? (his|her|their)\b|key takeaway|one (line|word)"
    r"|quick take|\bsnippet\b|\bclip\b|biggest highlight|\bmoments?\b from",
    re.I)

RESEARCH_RULES = [
    # The recurring commentary formats worth never missing.
    (+4, r"market outlook|monthly outlook|market update|monthly update"
         r"|quarterly (update|review|commentary)|annual letter|investor letter"
         r"|newsletter|factsheet|portfolio (update|review|commentary)"
         r"|strategy update|fund update"),
    # Long-form conversation.
    # "conclave" is deliberately absent: a conference produces one real session
    # and a dozen soundbite cuts, so the word predicts promo more than research.
    (+3, r"\binterview\b|in conversation|\bpodcast\b|unscripted|fireside"
         r"|\bepisode\b|part \d+|\bwebinar\b|masterclass|\bAMA\b"),
    # Teaching and analysis.
    (+2, r"\bexplained\b|deep dive|\banalysis\b|\bframework\b|case study"
         r"|how to (evaluate|analyse|analyze|think)|why we|our view|outlook for"),
    # Named roles - a titled manager speaking is usually substance.
    (+2, r"\bfund manager\b|\bCIO\b|\bCEO\b|chief investment"),
]

# Titles that are only a question or a slogan, with nothing concrete in them.
VAGUE_TITLE = re.compile(
    r"^\s*(what|why|how|did|is|are|do|does|can|should)\b[^?]{0,45}\?\s*$", re.I)


def _rule_score(title, description, managers):
    score, reasons = 0, []
    blob = f"{title} {description}".lower()

    for weight, pattern in PROMO_RULES:
        if re.search(pattern, blob, re.I):
            score += weight
            reasons.append(f"promo phrasing ({pattern.split('|')[0].strip()})")
            break

    for weight, pattern in RESEARCH_RULES:
        if re.search(pattern, blob, re.I):
            score += weight
            reasons.append("research format")
            break

    is_soundbite = bool(SOUNDBITE.search(blob))
    if is_soundbite:
        score -= 3
        reasons.append("event soundbite clip")

    # The manager being named in the title is a strong positive - unless this is
    # a soundbite cut, where their name is just the clip's label.
    if not is_soundbite:
        for name in managers:
            name = name.strip()
            if len(name) > 3 and name.lower() in title.lower():
                score += 3
                reasons.append(f"names {name}")
                break

    # A bare rhetorical question with no substance behind it is usually a teaser.
    if VAGUE_TITLE.match(title):
        score -= 2
        reasons.append("vague one-line title")

    return score, reasons


def _duration_score(seconds):
    if seconds is None:
        return 0, []
    if seconds < 90:
        return -5, [f"{seconds}s - a Short"]
    if seconds < 180:
        return -2, [f"{seconds}s - very brief"]
    if seconds >= 900:
        return +4, [f"{seconds // 60} min - long form"]
    if seconds >= 420:
        return +2, [f"{seconds // 60} min"]
    return 0, []


# --- duration lookup ----------------------------------------------------

def fetch_video_meta(video_ids):
    """{video_id: {seconds, lang, audio_lang}} for up to 50 ids per call.

    Costs 1 quota unit per call regardless of how many parts are requested, so
    pulling snippet alongside contentDetails is free.
    """
    if not config.YOUTUBE_API_KEY or not video_ids:
        return {}
    out = {}
    ids = list(video_ids)
    for chunk_start in range(0, len(ids), 50):
        chunk = ids[chunk_start:chunk_start + 50]
        try:
            data = util.fetch(VIDEOS_API, params={
                "key": config.YOUTUBE_API_KEY,
                "part": "contentDetails,snippet",
                "id": ",".join(chunk)}).json()
        except Exception as exc:
            log.warning("video metadata lookup failed: %s", exc)
            continue
        for item in data.get("items", []):
            sn = item.get("snippet", {})
            out[item["id"]] = {
                "seconds": _parse_iso_duration(
                    item.get("contentDetails", {}).get("duration", "")),
                "lang": sn.get("defaultLanguage"),
                "audio_lang": sn.get("defaultAudioLanguage"),
            }
    return out


def fetch_durations(video_ids):
    """Back-compat wrapper: {video_id: seconds}."""
    return {vid: m["seconds"] for vid, m in fetch_video_meta(video_ids).items()
            if m.get("seconds") is not None}


def _parse_iso_duration(iso):
    """PT1H2M3S -> 3723."""
    m = re.fullmatch(r"P(?:(\d+)D)?T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?",
                     iso or "")
    if not m:
        return None
    days, hours, mins, secs = (int(g or 0) for g in m.groups())
    return days * 86400 + hours * 3600 + mins * 60 + secs


# --- model fallback -----------------------------------------------------

CLASSIFY_TOOL = {
    "name": "classify",
    "description": "Classify this video for a fund research library.",
    "input_schema": {
        "type": "object",
        "properties": {
            "category": {
                "type": "string",
                "enum": ["research", "promo"],
                "description": (
                    "'research' if a fund manager or analyst is discussing "
                    "markets, strategy, portfolio positioning, or teaching an "
                    "investing concept. 'promo' if it is marketing: a scheme "
                    "launch or NFO, a festival greeting, an award or milestone, "
                    "a call to invest, or short filler content."),
            },
            "reason": {"type": "string", "description": "Under 10 words."},
        },
        "required": ["category", "reason"],
    },
}


def pending_ambiguous(limit=60):
    """Videos the rules left at 'unclear - kept', oldest first."""
    conn = db.connect()
    rows = conn.execute(
        """SELECT id, title, author, summary AS description FROM items
           WHERE kind IN ('video', 'podcast')
             AND classify_why LIKE '%unclear - kept%'
           ORDER BY id LIMIT ?""", (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def resolve_ambiguous(rows, limit=None):
    """Ask Claude about the videos the rules could not call.

    Sent as one batch, and only for genuinely ambiguous items - the rules
    settle the large majority on their own. Runs through whichever provider is
    configured, so on a machine with Claude Code signed in this costs nothing.

    rows: [{"id": int, "title": str, "author": str, "description": str}]
    Returns the number of verdicts applied.
    """
    rows = [r for r in rows if r.get("title")]
    if not rows:
        return 0
    if limit:
        rows = rows[:limit]

    ok, why = providers.available()
    if not ok:
        log.info("no classifier available (%s) - ambiguous items kept", why)
        return 0

    by_n = {i: r for i, r in enumerate(rows, start=1)}
    records = [{"n": n, "title": r["title"], "author": r.get("author", ""),
                "description": r.get("description", "")}
               for n, r in by_n.items()]
    try:
        verdicts = providers.classify_batch(records)
    except Exception as exc:
        log.warning("batch classification failed: %s", exc)
        return 0

    applied = 0
    for n, (category, reason) in verdicts.items():
        row = by_n.get(n)
        if not row:
            continue
        db.set_content_type(row["id"], category, f"model: {reason}")
        applied += 1
    log.info("classified %d ambiguous item(s) as promo/research", applied)
    return applied


# --- entry point --------------------------------------------------------

def classify_video(title, description="", author="", managers=(),
                   duration=None, allow_model=True):
    """Returns (content_type, why)."""
    score, reasons = _rule_score(title, description, managers)
    d_score, d_reasons = _duration_score(duration)
    score += d_score
    reasons += d_reasons

    if score >= 2:
        return "research", "; ".join(reasons) or "no promo markers"
    if score <= -2:
        return "promo", "; ".join(reasons)

    # Ambiguous. Keep it for now and mark it so resolve_ambiguous() can pick it
    # up; a batched call settles all of them at once rather than one at a time.
    return "research", "; ".join(reasons + ["unclear - kept"]) or "unclear - kept"


def run_pending(limit=200):
    """Classify every video and podcast that hasn't been looked at yet.

    Also records duration and language, which the shelf filters on.
    """
    conn = db.connect()
    rows = conn.execute(
        """SELECT i.id, i.kind, i.title, i.summary, i.author, i.url,
                  i.duration_secs, f.managers, s.kind AS source_kind
           FROM items i
           JOIN funds f ON f.id = i.fund_id
           LEFT JOIN sources s ON s.id = i.source_id
           WHERE i.kind IN ('video','podcast')
             AND (i.content_type = 'unclassified' OR i.language = ''
                  OR i.speaker = '')
           LIMIT ?""", (limit,)).fetchall()
    conn.close()
    if not rows:
        return {"research": 0, "promo": 0}

    # One batched metadata lookup covers duration and declared language.
    import extract
    wanted = set()
    for r in rows:
        vid = extract.youtube_id(r["url"])
        if vid:
            wanted.add(vid)
    meta = fetch_video_meta(wanted)

    counts = {"research": 0, "promo": 0}
    conn = db.connect()
    with conn:
        for r in rows:
            vid = extract.youtube_id(r["url"])
            m = meta.get(vid, {})
            secs = r["duration_secs"] or m.get("seconds")

            lang, lang_why = language.detect(
                r["title"], r["summary"] or "", r["author"] or "",
                tag=m.get("lang"), audio_tag=m.get("audio_lang"))

            managers = [m2 for m2 in (r["managers"] or "").split(",")
                        if m2.strip()]
            ctype, why = classify_video(
                r["title"], r["summary"] or "", r["author"] or "",
                managers, secs)
            counts[ctype] += 1

            # A video reaching us from the house's own channel is theirs by
            # definition; anything found by searching has to prove a manager
            # is actually in it rather than merely being discussed.
            own_channel = r["source_kind"] == "youtube_channel"
            who, who_why = speaker.detect(
                r["title"], r["summary"] or "", r["author"] or "",
                managers=managers, from_own_channel=own_channel)

            conn.execute(
                """UPDATE items SET content_type = ?, classify_why = ?,
                   duration_secs = ?, language = ?, language_why = ?,
                   speaker = ?, speaker_why = ?
                   WHERE id = ?""",
                (ctype, why[:300], secs, lang, lang_why[:200],
                 who, who_why[:200], r["id"]))
    conn.close()
    log.info("classified: %s", counts)

    # Whatever the rules could not call gets settled in a single batch.
    settled = resolve_ambiguous(pending_ambiguous())
    if settled:
        counts["reclassified"] = settled

    return counts
