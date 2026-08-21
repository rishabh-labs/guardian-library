"""Shared helpers for the collectors."""
import html
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

import requests
from dateutil import parser as dateparser

import config

TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "igshid", "ref", "ref_src", "oc", "hl", "gl", "ceid",
    "_gl", "mc_cid", "mc_eid", "cmpid", "s_kwcid",
}

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": config.USER_AGENT})


def fetch(url, **kw):
    kw.setdefault("timeout", config.HTTP_TIMEOUT)
    resp = SESSION.get(url, **kw)
    resp.raise_for_status()
    return resp


def canonicalise(url):
    """Strip tracking noise so the same article from two feeds dedupes."""
    if not url:
        return ""
    url = url.strip()
    try:
        p = urlparse(url)
    except ValueError:
        return url
    query = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
             if k.lower() not in TRACKING_PARAMS]
    netloc = p.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    if netloc in ("m.youtube.com", "youtu.be"):
        netloc = "youtube.com"
    path = p.path.rstrip("/") or "/"
    return urlunparse((p.scheme.lower(), netloc, path, "",
                       urlencode(query), ""))


def parse_date(value):
    """Return an ISO8601 UTC string, or None."""
    if not value:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = dateparser.parse(str(value))
        except (ValueError, OverflowError, TypeError):
            return None
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def window_days(source):
    """How far back this poll should reach.

    First ever poll of a source gets the full backfill (6 months) to build the
    library. Every poll after that only looks at the last month, so a monthly
    refresh surfaces the month just gone and nothing older comes back.
    """
    if source.get("_window_days"):
        return source["_window_days"]
    return (config.BACKFILL_DAYS if not source.get("last_checked")
            else config.INCREMENTAL_DAYS)


def too_old(published_iso, days=None):
    """Guard against a source dumping its whole back catalogue.

    An item with no date at all is kept: page-scraped links carry no timestamp,
    and dropping them would empty the website watcher entirely.
    """
    if not published_iso:
        return False
    days = config.BACKFILL_DAYS if days is None else days
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    try:
        return dateparser.parse(published_iso) < cutoff
    except (ValueError, OverflowError, TypeError):
        return False


def strip_html(text, limit=400):
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def match_terms_for(fund):
    """Every string that, if present, makes an item relevant to this fund."""
    terms = [fund["fund_name"] if "fund_name" in fund else fund.get("name", "")]
    terms += [t for t in (fund.get("managers") or "").split(",")]
    terms += [t for t in (fund.get("match_terms") or "").split(",")]
    terms.append(fund.get("house", ""))
    return [t.strip().lower() for t in terms if t and t.strip()]


# Words that carry no identity, so they must not be required for a match.
# Without this, "Tata Mutual Fund" fails to match an article saying "Tata MF" -
# which silently dropped the entire Tata feed during testing.
GENERIC_TOKENS = {
    # fund-industry furniture
    "mutual", "fund", "funds", "mf", "amc", "pms", "aif", "scheme", "schemes",
    "asset", "assets", "management", "manager", "managers", "advisor",
    "advisors", "adviser", "advisers", "investment", "investments",
    "investing", "capital", "portfolio", "wealth", "securities", "holdings",
    "financial", "finance", "services", "trust", "trustee",
    # corporate furniture
    "ltd", "limited", "private", "pvt", "llp", "india", "indian", "the",
    "and", "of", "house", "group", "co", "company", "partners", "global",
    # sheet annotations - "Sageone October News Letter" is just SageOne
    "newsletter", "news", "letter", "update", "updates",
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december",
}


# Ordinary English words that are also parts of house names. A name whose only
# distinctive word is one of these cannot be token-matched: "2 Point 2 Capital"
# reduces to {"point"}, which matched every podcast episode using the word.
COMMON_WORDS = {
    "old", "new", "bridge", "point", "value", "growth", "prime", "first",
    "best", "smart", "edge", "core", "alpha", "right", "true", "one", "two",
    "three", "next", "high", "low", "big", "small", "long", "short", "green",
    "blue", "white", "black", "gold", "silver", "star", "sun", "moon", "peak",
    "summit", "vision", "focus", "select", "premier", "united", "national",
}


def term_tokens(term):
    """The distinctive words of a name, as a set.

    "Tata Mutual Fund" -> {"tata"};  "Savi Jain" -> {"savi", "jain"}.
    If a name is entirely generic, keep it whole rather than matching nothing.
    """
    words = re.findall(r"[a-z0-9]+", (term or "").lower())
    distinctive = [w for w in words if w not in GENERIC_TOKENS and len(w) > 1]
    return set(distinctive or words)


def term_phrase(term):
    """Normalised phrase form, for names too generic to token-match."""
    return " ".join(re.findall(r"[a-z0-9]+", (term or "").lower()))


def needs_phrase_match(tokens):
    """True when token matching would be too loose to trust."""
    return bool(tokens) and all(t in COMMON_WORDS for t in tokens)


def is_relevant(text, terms):
    """True when every distinctive word of at least one term appears.

    Requiring *all* tokens of a name keeps "Old Bridge Capital" from matching
    any article containing the word "bridge", while dropping generic words lets
    abbreviated forms through.
    """
    if not terms:
        return True
    blob = (text or "").lower()
    squashed = re.sub(r"[^a-z0-9]+", " ", blob)
    tight = re.sub(r"[^a-z0-9]+", "", blob)

    for term in terms:
        tokens = term_tokens(term)
        if not tokens:
            continue
        if needs_phrase_match(tokens):
            # "old bridge" must appear as a phrase, and "2 point 2 capital"
            # also matches the way it is usually written: "2point2".
            phrase = term_phrase(term)
            if phrase and (phrase in squashed
                           or phrase.replace(" ", "") in tight):
                return True
            continue
        if all(t in blob for t in tokens):
            return True
    return False
