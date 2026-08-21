"""News collectors.

news_search - Google News RSS. Free, no key, no published rate limit. A quoted
query keeps it tight ("Marcellus Investment Managers"), and we still run the
relevance check because Google will happily broaden a query.

rss - any publisher or fund-house feed supplied directly. Trusted, no filter.
"""
from urllib.parse import quote_plus

import feedparser

from . import util

GOOGLE_NEWS = ("https://news.google.com/rss/search?q={q}"
               "&hl=en-IN&gl=IN&ceid=IN:en")


def _entry_to_item(e, source, kind="news"):
    link = e.get("link", "")
    published = util.parse_date(e.get("published") or e.get("updated"))
    author = e.get("source", {}).get("title", "") if isinstance(
        e.get("source"), dict) else e.get("author", "")
    return {
        "fund_id": source["fund_id"],
        "source_id": source["id"],
        "kind": kind,
        "title": util.strip_html(e.get("title", "(untitled)"), 300),
        "url": link,
        "canonical_url": util.canonicalise(link),
        "thumbnail": "",
        "author": author,
        "summary": util.strip_html(e.get("summary", "")),
        "published_at": published,
    }


def collect_news_search(source):
    """source['value'] is the raw query, e.g. '"Rajeev Thakkar" AND (fund OR ...)'.

    Google's AND handling is loose, so results still need filtering. The check
    is token-based rather than exact-phrase: an article saying "Tata MF" is
    about Tata Mutual Fund, and requiring the full phrase dropped that whole
    feed during testing.
    """
    feed = feedparser.parse(GOOGLE_NEWS.format(q=quote_plus(source["value"])))
    terms = util.match_terms_for(source)
    window = util.window_days(source)
    out = []
    for e in feed.entries:
        item = _entry_to_item(e, source)
        if not util.is_relevant(f"{item['title']} {item['summary']}", terms):
            continue
        if util.too_old(item["published_at"], window):
            continue
        if not item["canonical_url"]:
            continue
        out.append(item)
    return out


def collect_news_person(source):
    """News search for a named individual - no relevance re-check.

    A quoted personal name is precise enough on Google's side, and the useful
    articles are exactly the ones that quote the manager in the body without
    repeating the name in the headline or snippet. Filtering on title/snippet
    dropped those, which is the opposite of what a research library wants.
    """
    feed = feedparser.parse(GOOGLE_NEWS.format(q=quote_plus(source["value"])))
    window = util.window_days(source)
    out = []
    for e in feed.entries:
        item = _entry_to_item(e, source)
        if util.too_old(item["published_at"], window):
            continue
        if not item["canonical_url"]:
            continue
        out.append(item)
    return out


def collect_rss(source):
    """A trusted feed - fund house blog, publisher feed, podcast. No filtering."""
    feed = feedparser.parse(source["value"])
    if feed.bozo and not feed.entries:
        raise RuntimeError(f"unreadable feed: {feed.bozo_exception}")
    window = util.window_days(source)
    out = []
    for e in feed.entries:
        item = _entry_to_item(e, source)
        if util.too_old(item["published_at"], window):
            continue
        if not item["canonical_url"]:
            continue
        # A podcast or video feed will carry an enclosure; label it as media.
        for link in e.get("links", []):
            if link.get("type", "").startswith(("audio", "video")):
                item["kind"] = "video"
                break
        out.append(item)
    return out
