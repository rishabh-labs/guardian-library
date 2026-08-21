"""YouTube collectors.

Two mechanisms:

1. channel feeds - every YouTube channel publishes a free Atom feed at
   /feeds/videos.xml?channel_id=UC... No API key, no quota. This is how we catch
   uploads by the fund house's own channel.

2. keyword search - catches the manager turning up on somebody else's channel
   (CNBC-TV18, ET Now, a podcast). Needs a Data API key; skipped without one.
"""
import logging
import re

import feedparser

import config
from . import util

log = logging.getLogger("collectors")

CHANNEL_FEED = "https://www.youtube.com/feeds/videos.xml?channel_id={}"
SEARCH_API = "https://www.googleapis.com/youtube/v3/search"


ID_PATTERNS = (r'"channelId":"(UC[\w-]{22})"',
               r'channel_id=(UC[\w-]{22})',
               r'"externalId":"(UC[\w-]{22})"')


def _scrape_channel_id(url):
    try:
        html = util.fetch(url).text
    except Exception:
        return None
    for pattern in ID_PATTERNS:
        m = re.search(pattern, html)
        if m:
            return m.group(1)
    return None


def _search_channel_id(name):
    """Last resort: ask the Data API which channel this name belongs to."""
    if not config.YOUTUBE_API_KEY:
        return None
    try:
        data = util.fetch(SEARCH_API, params={
            "key": config.YOUTUBE_API_KEY, "part": "snippet", "q": name,
            "type": "channel", "maxResults": 1}).json()
        items = data.get("items", [])
        return items[0]["id"]["channelId"] if items else None
    except Exception:
        return None


def resolve_channel_id(value):
    """Accept a raw channel id, a /channel/ URL, an @handle, a /c/ vanity URL,
    or just the channel's name, and return the UC... id."""
    value = value.strip()

    if re.fullmatch(r"UC[\w-]{22}", value):
        return value
    m = re.search(r"/channel/(UC[\w-]{22})", value)
    if m:
        return m.group(1)

    # A full URL of any other shape - read the id out of the page.
    if value.startswith("http"):
        found = _scrape_channel_id(value)
        if found:
            return found
        handle = value.rstrip("/").rsplit("/", 1)[-1]
    else:
        handle = value

    # Bare handle or name: try the handle URL, then the legacy vanity paths.
    handle = handle.lstrip("@")
    for candidate in (f"https://www.youtube.com/@{handle}",
                      f"https://www.youtube.com/c/{handle}",
                      f"https://www.youtube.com/user/{handle}"):
        found = _scrape_channel_id(candidate)
        if found:
            return found

    found = _search_channel_id(handle)
    if found:
        return found

    raise ValueError(
        f"could not resolve a YouTube channel from {value!r}. Open the channel "
        f"in a browser and paste the URL from the address bar, or paste its "
        f"UC... id directly.")


def collect_channel(source):
    """Uploads from one channel. Trusted source - no relevance filtering."""
    channel_id = resolve_channel_id(source["value"])

    # Cache the resolved id back onto the source so later polls skip the lookup.
    if channel_id != source["value"]:
        import sqlite3
        import db
        conn = db.connect()
        try:
            with conn:
                conn.execute("UPDATE sources SET value = ? WHERE id = ?",
                             (channel_id, source["id"]))
        except sqlite3.IntegrityError:
            # The fund already has this channel under its resolved id - a handle
            # and a UC... id for the same channel were both added. Drop the
            # duplicate rather than failing the poll every cycle.
            with conn:
                conn.execute("DELETE FROM sources WHERE id = ?", (source["id"],))
            log.info("dropped duplicate channel source %s (already tracked as %s)",
                     source["value"], channel_id)
        finally:
            conn.close()

    feed = feedparser.parse(CHANNEL_FEED.format(channel_id))
    window = util.window_days(source)
    out = []
    for e in feed.entries:
        published = util.parse_date(e.get("published"))
        if util.too_old(published, window):
            continue
        thumb = ""
        media = e.get("media_thumbnail") or []
        if media:
            thumb = media[0].get("url", "")
        summary = ""
        if hasattr(e, "media_description"):
            summary = util.strip_html(e.media_description)
        out.append({
            "fund_id": source["fund_id"],
            "source_id": source["id"],
            "kind": "video",
            "title": e.get("title", "(untitled)"),
            "url": e.get("link", ""),
            "canonical_url": util.canonicalise(e.get("link", "")),
            "thumbnail": thumb,
            "author": e.get("author", "") or feed.feed.get("title", ""),
            "summary": summary,
            "published_at": published,
        })
    return out


# A person's name alone is not enough: "Sameer Shah" returns a Pashto singer,
# "Arun Kumar" returns politicians. A genuine fund-manager appearance essentially
# always mentions something financial in its title, description or channel name.
FINANCE_HINTS = re.compile(
    r"market|stock|share|equit|fund|invest|portfolio|econom|sector|valuation|"
    r"earning|nifty|sensex|\bipo\b|\bpms\b|\bamc\b|mutual|capital|financ|"
    r"money|wealth|business|rupee|\brbi\b|inflation|\bgdp\b|returns|"
    r"midcap|smallcap|largecap|bond|yield|budget|banking|\bnfo\b|"
    r"compound|allocation|asset|trade|profit|revenue|dividend|"
    r"निवेश|बाज़ार|बाजार|शेयर|म्यूचुअल", re.I)


# A name match plus a finance word is still not enough: "INTERNATIONAL
# MARKETING by SRINIVASAN, R." is an audiobook, and a chemicals executive can
# share a name with a fund manager. Require the item to place the person in a
# markets context - the words below, or the fund house itself.
INDUSTRY_HINTS = re.compile(
    r"\bfunds?\b|\bpms\b|\baif\b|\bamc\b|mutual|portfolio|investor|"
    r"investing|investment|equit|\bstocks?\b|nifty|sensex|\bcio\b|"
    r"asset manage|midcap|smallcap|largecap|small cap|mid cap|large cap|"
    r"valuation|\bnav\b|flexicap|flexi cap|\bsip\b|\bmarkets?\b|"
    r"\bsectors?\b|wealth|compounder|allocation|\bipo\b|\bnfo\b|\brbi\b|earnings|"
    # Hindi finance vocabulary, so a Hindi interview by the manager is
    # judged on its subject rather than dropped for being non-Latin.
    r"निवेश|बाज़ार|बाजार|शेयर|म्यूचुअल|पोर्टफोलियो|सेक्टर", re.I)


def in_markets_context(blob, source):
    """True when the text is about this person's day job, not just their name."""
    house = (source.get("house") or "").strip().lower()
    if house and house in blob.lower():
        return True
    return bool(INDUSTRY_HINTS.search(blob))


def collect_search(source):
    """Keyword search across all of YouTube. Costs 100 quota units per call
    against a 10,000/day free allowance."""
    if not config.YOUTUBE_API_KEY:
        raise RuntimeError("no YOUTUBE_API_KEY set - keyword search skipped")

    params = {
        "key": config.YOUTUBE_API_KEY,
        "part": "snippet",
        "q": source["value"],
        "type": "video",
        "order": "date",
        "maxResults": 25,
        "relevanceLanguage": "en",
    }
    data = util.fetch(SEARCH_API, params=params).json()
    terms = util.match_terms_for(source)
    window = util.window_days(source)
    out = []
    for it in data.get("items", []):
        sn = it["snippet"]
        vid = it["id"].get("videoId")
        if not vid:
            continue
        blob = f"{sn.get('title','')} {sn.get('description','')} {sn.get('channelTitle','')}"
        if not util.is_relevant(blob, terms):
            continue
        # The name matched, but is this even about finance?
        if not FINANCE_HINTS.search(blob):
            continue
        # ...and is it about *this* person's work, not a namesake?
        if not in_markets_context(blob, source):
            continue
        published = util.parse_date(sn.get("publishedAt"))
        if util.too_old(published, window):
            continue
        out.append({
            "fund_id": source["fund_id"],
            "source_id": source["id"],
            "kind": "video",
            "title": sn.get("title", "(untitled)"),
            "url": f"https://www.youtube.com/watch?v={vid}",
            "canonical_url": util.canonicalise(
                f"https://www.youtube.com/watch?v={vid}"),
            "thumbnail": sn.get("thumbnails", {}).get("high", {}).get("url", ""),
            "author": sn.get("channelTitle", ""),
            "summary": util.strip_html(sn.get("description", "")),
            "published_at": published,
        })
    return out
