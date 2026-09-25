"""Collect fund house newsletters and place each one in a calendar month.

A newsletter is only useful in a library if you can say which month it belongs
to, so every candidate must yield a period (YYYY-MM). Three ways to get one,
in order of reliability:

  1. the title            "Portfolio Updates & Insights - June 2026"
  2. the URL              ".../dspnetra-april-26.pdf"
  3. the date printed
     beside the link      "AUG 06, 2026"

Anything with no determinable month is skipped rather than guessed at.
"""
import logging
import re
from datetime import datetime, timezone
from html import unescape as html_unescape
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from dateutil import parser as dateparser

from . import util
from .watch import (DOC_EXTENSIONS, NAV_WORDS, NOISE, _content_root,
                    _is_meta_strip, _strip_chrome, _title_from_card)

log = logging.getLogger("newsletters")

MONTHS = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
    "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7,
    "august": 8, "aug": 8, "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10, "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}
MONTH_RE = "|".join(sorted(MONTHS, key=len, reverse=True))

# "June 2026", "june-2026", "June, 2026" - a full year, any separator.
PERIOD_WORD_FULL = re.compile(
    rf"\b({MONTH_RE})[\s\-_/,]*((?:19|20)\d{{2}})\b", re.I)
# "jun-26", "aug_26", "april26" - a two-digit year, but NEVER across a space.
# Allowing a space here read the day out of "JUL 27, 2026" as the year 2027.
PERIOD_WORD_SHORT = re.compile(rf"\b({MONTH_RE})[\-_]?(\d{{2}})\b", re.I)
# "2026-06", "2026_06"
PERIOD_ISO = re.compile(r"\b((?:19|20)\d{2})[\-_/](0[1-9]|1[0-2])\b")
# "20260630", "202606" - compact stamps used in factsheet filenames.
PERIOD_COMPACT = re.compile(r"\b((?:19|20)\d{2})(0[1-9]|1[0-2])(?:[0-3]\d)?\b")
# Quarterly letters: "Q2 FY25", "Q3-FY2025"
PERIOD_QTR = re.compile(r"\bQ([1-4])[\s\-_]*FY[\s\-_]*((?:20)?\d{2})\b", re.I)

# Indian fiscal quarters end in Jun / Sep / Dec / Mar.
QUARTER_END_MONTH = {1: 6, 2: 9, 3: 12, 4: 3}

# Regulatory, governance and sales collateral that lives in the same media
# library as the newsletters but is not research.
COMPLIANCE_DOC = re.compile(
    r"polic(y|ies)|\bcsr\b|committee|grievance|redress|disclosure|disclaimer|"
    r"terms|privacy|refund|\bkyc\b|\baml\b|\bsid\b|\bkim\b|\bsai\b|"
    r"application form|\bform\b|distributor|\bpartners?\b|employee|"
    r"code of conduct|action plan|board|director|audit|\bagm\b|notice|"
    r"circular|\bfaq\b|voting|proxy|stewardship|conflict of interest|"
    r"whistle ?blower|fee (calculator|structure)|product deck|pricing|"
    r"onboarding|account opening|mandate|annexure|addendum|"
    # SEBI-mandated monthly complaint filings - dated like a newsletter, and
    # published every month, but they are compliance returns, not research.
    r"complaints?|compliant data|investor charter", re.I)

NEWSLETTER_HINTS = re.compile(
    r"newsletter|investor (update|letter|memo|communication)|"
    r"monthly (update|letter|note|report|round)|factsheet|fact sheet|"
    r"portfolio update|insights|memo|commentary|netra|outlook|"
    r"market (update|note|commentary)|quarterly (update|letter)", re.I)


def _two_digit_year(value):
    n = int(value)
    return n if n > 100 else 2000 + n


def period_from_text(text):
    """Return 'YYYY-MM' or None."""
    if not text:
        return None

    # Full four-digit years first - they are unambiguous.
    m = PERIOD_WORD_FULL.search(text)
    if m:
        month = MONTHS[m.group(1).lower()]
        return f"{int(m.group(2)):04d}-{month:02d}"

    m = PERIOD_ISO.search(text)
    if m:
        return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}"

    m = PERIOD_COMPACT.search(text)
    if m:
        return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}"

    m = PERIOD_WORD_SHORT.search(text)
    if m:
        year = _two_digit_year(m.group(2))
        # Reject anything implausible - a day number misread as a year.
        if 2015 <= year <= datetime.now(timezone.utc).year + 1:
            return f"{year:04d}-{MONTHS[m.group(1).lower()]:02d}"

    m = PERIOD_QTR.search(text)
    if m:
        quarter, fy = int(m.group(1)), _two_digit_year(m.group(2))
        month = QUARTER_END_MONTH[quarter]
        # FY25 Q1-Q3 fall in calendar 2024; Q4 (Jan-Mar) falls in 2025.
        year = fy - 1 if quarter < 4 else fy
        return f"{year:04d}-{month:02d}"

    return None


DATE_PATTERNS = (
    rf"\b({MONTH_RE})\w*\.?\s+\d{{1,2}},?\s+((?:19|20)\d{{2}})\b",
    rf"\b\d{{1,2}}\s+({MONTH_RE})\w*\.?\s+((?:19|20)\d{{2}})\b",
    r"\b\d{1,2}[/-]\d{1,2}[/-](?:19|20)\d{2}\b",
)


def _parse_printed_date(text):
    """Pull a full date out of a string like 'AUG 06, 2026 . 9 MIN READ'."""
    if not text:
        return None
    for pattern in DATE_PATTERNS:
        m = re.search(pattern, text, re.I)
        if m:
            try:
                dt = dateparser.parse(m.group(0), dayfirst=True)
                if dt:
                    return dt.replace(tzinfo=timezone.utc)
            except (ValueError, OverflowError, TypeError):
                continue
    return None


def _date_near(anchor):
    """Find a printed date in the card around this link."""
    node = anchor
    for _ in range(4):
        node = node.parent
        if node is None:
            return None
        found = _parse_printed_date(node.get_text(" ", strip=True)[:400])
        if found:
            return found
    return None


def _source_filters(source):
    """Compiled (include, exclude) patterns for a source, or (None, None)."""
    def _compile(raw):
        raw = (source.get(raw) or "").strip()
        if not raw:
            return None
        try:
            return re.compile(raw, re.I)
        except re.error as exc:
            log.warning("bad regex on source %s: %s", source.get("id"), exc)
            return None
    return _compile("include_re"), _compile("exclude_re")


def _passes_filters(text, include_re, exclude_re):
    """A house often publishes several document families side by side; these
    keep a source to the one that was actually asked for."""
    if include_re and not include_re.search(text):
        return False
    if exclude_re and exclude_re.search(text):
        return False
    return True


def _title_from_slug(url):
    """'/sageone-investor-memo-jan-2026/' -> 'Sageone Investor Memo Jan 2026'."""
    slug = urlparse(url).path.rstrip("/").rsplit("/", 1)[-1]
    slug = re.sub(r"\.(pdf|xlsx?|docx?|pptx?)$", "", slug, flags=re.I)
    # %20 must be matched as a literal escape, not as a character class -
    # "[-_%20]" also matches the digits 2 and 0, which split "2026" into "6".
    words = re.split(r"(?:%20|[-_\s]+)+", slug)
    title = " ".join(w for w in words if w).strip()
    return title.title()[:300] if len(title) > 3 else ""


def period_to_date(period):
    """First of the month, as an ISO timestamp."""
    year, month = (int(p) for p in period.split("-"))
    return datetime(year, month, 1, tzinfo=timezone.utc).isoformat(
        timespec="seconds")


def collect_newsletter_page(source):
    """Scrape a fund house's newsletter listing page."""
    base = source["value"]
    html = util.fetch(base).text
    soup = _content_root(_strip_chrome(BeautifulSoup(html, "lxml")))
    window = util.window_days(source)
    base_host = urlparse(base).netloc.replace("www.", "")

    best = {}
    for a in soup.find_all("a", href=True):
        href = urljoin(base, a["href"].strip())
        text = a.get_text(" ", strip=True)
        low = href.lower()
        if not href.startswith("http") or any(n in low for n in NOISE):
            continue
        # Newsletters occasionally sit on a CDN, so allow off-host documents.
        if urlparse(href).netloc.replace("www.", "") != base_host and \
                not low.endswith(DOC_EXTENSIONS):
            continue
        if href.rstrip("/") == base.rstrip("/"):
            continue

        is_doc = low.endswith(DOC_EXTENSIONS)

        # Listing pages often link the newsletter from its thumbnail image, so
        # the anchor carries no text at all. The month is still in the URL, so
        # recover a title from the card heading or the URL slug rather than
        # dropping a perfectly identifiable newsletter.
        if not text:
            text = _title_from_card(a) or ""
            if not text and (is_doc or period_from_text(href)):
                text = _title_from_slug(href)
            if not text:
                continue

        # The anchor is often the card's date strip rather than its title.
        # Recover the heading, but keep the strip for date extraction below.
        date_text = text
        if _is_meta_strip(text):
            recovered = _title_from_card(a)
            if not recovered and not is_doc:
                continue
            text = recovered or text

        # No "must contain the word newsletter" gate here. The page was chosen
        # as a newsletter source, so anything on it that can be dated counts -
        # requiring the word dropped every ValueQuest post ("The New Space
        # Race") despite their dates being right there on the page.
        if COMPLIANCE_DOC.search(text):
            continue
        # "View All" / "Read More" sit inside dated cards, so they pick up a
        # date from their neighbours and would otherwise be stored as posts.
        if text.strip().lower().rstrip(" .>»→") in NAV_WORDS:
            continue

        # The month named in the title wins. "Factsheet June 2026" belongs to
        # June even though it was published on 16 July - the period is the month
        # the newsletter covers, not the day it went out. Fall back to the
        # printed date only when the title and URL say nothing.
        published = None
        period = period_from_text(text) or period_from_text(href)
        if period:
            published = period_to_date(period)
        else:
            dt = _date_near(a) or (_parse_printed_date(date_text)
                                   if date_text is not text else None)
            if dt:
                period = f"{dt.year:04d}-{dt.month:02d}"
                published = dt.isoformat(timespec="seconds")

        if not period:
            continue                      # can't place it in a month - skip
        if util.too_old(published, window):
            continue

        canon = util.canonicalise(href)
        title = text or href.rsplit("/", 1)[-1]
        if canon not in best or len(title) > len(best[canon]["title"]):
            best[canon] = {
                "fund_id": source["fund_id"],
                "source_id": source["id"],
                "kind": "newsletter",
                "title": title[:300],
                "url": href,
                "canonical_url": canon,
                "thumbnail": "",
                "author": source.get("label") or base_host,
                "summary": "",
                "published_at": published,
                "period": period,
            }
    return list(best.values())


def collect_wp_media(source):
    """Read newsletters straight out of a WordPress media library.

    Many fund house sites render their factsheet listing with JavaScript, so
    the HTML we receive contains only site chrome. Those same sites are almost
    always WordPress, and WordPress exposes every uploaded file through
    /wp-json/wp/v2/media - which needs no browser and no JavaScript.

    source['value'] is the site root, e.g. https://www.buoyantcap.com
    """
    base = source["value"].rstrip("/")
    if "/wp-json" in base:
        base = base.split("/wp-json")[0]
    window = util.window_days(source)

    entries = []
    for page in range(1, 6):                 # up to 500 files, newest first
        try:
            batch = util.fetch(f"{base}/wp-json/wp/v2/media", params={
                "per_page": 100, "page": page, "orderby": "date",
                "order": "desc", "mime_type": "application/pdf"}).json()
        except Exception:
            # A page past the end returns 400 rather than an empty list, so
            # this is the normal way the walk finishes.
            break
        if not isinstance(batch, list) or not batch:
            break
        entries.extend(batch)
        # Deliberately no "stop when the page is short" check. WordPress
        # applies mime_type AFTER paginating, so a full page of 100 uploads
        # can yield 92 PDFs - and treating that as the end meant only ever
        # reading the first page. Buoyant's July factsheet sat on page two,
        # invisible, for exactly this reason.

    if not entries:
        raise RuntimeError("no PDFs returned by the WordPress media API")

    include_re, exclude_re = _source_filters(source)

    out = []
    seen = set()
    for m in entries:
        url = m.get("source_url") or ""
        if not url.lower().endswith(DOC_EXTENSIONS):
            continue
        filename_only = urlparse(url).path.rsplit("/", 1)[-1]
        if not _passes_filters(filename_only, include_re, exclude_re):
            continue
        title = html_unescape((m.get("title") or {}).get("rendered", "")).strip()
        title = title or _title_from_slug(url)

        if COMPLIANCE_DOC.search(title):
            continue                      # policies, forms, board papers

        # Only the title and the FILENAME may supply the month - never the rest
        # of the URL. WordPress stores uploads under /YYYY/MM/, so using the
        # full path stamped every policy document with the month it happened to
        # be uploaded, which swept the whole site into the library.
        filename = urlparse(url).path.rsplit("/", 1)[-1]
        period = (period_from_text(title) or period_from_text(filename)
                  or period_from_month_only(filename)
                  or period_from_month_only(title))
        if not period:
            continue
        published = period_to_date(period)
        if util.too_old(published, window):
            continue
        if not url_ok(url):
            continue                     # still listed, already deleted

        # The same newsletter is often uploaded more than once (a re-cut PDF,
        # a copy per distributor). One row per title per month.
        key = (period, re.sub(r"[^a-z0-9]+", "", title.lower())[:60])
        if key in seen:
            continue
        seen.add(key)

        out.append({
            "fund_id": source["fund_id"],
            "source_id": source["id"],
            "kind": "newsletter",
            "title": title[:300],
            "url": url,
            "canonical_url": util.canonicalise(url),
            "thumbnail": "",
            "author": source.get("label") or urlparse(base).netloc,
            "summary": "",
            "published_at": published,
            "period": period,
        })

    if source.get("one_per_period"):
        out = _one_per_period(out)
    return out


def period_from_month_only(text):
    """'...-August.pdf' -> this year's August, or last year's if that is ahead.

    A house that names a factsheet by the month alone means the current one.
    Without this the document falls through to the upload folder in its URL,
    which is when it was posted, not what it covers - that is how an August
    factsheet ended up filed under September.
    """
    from datetime import date
    # Only when the text names no year at all. "Offshore-Newsletter-July-2025"
    # says 2025; guessing the current year there filed a 2025 letter under
    # 2026.
    if re.search(r"(19|20)\d{2}", text or ""):
        return ""
    m = re.search(r"\b(January|February|March|April|May|June|July|August"
                  r"|September|October|November|December)\b", text or "", re.I)
    if not m:
        return ""
    month = MONTH_NUMBERS.get(m.group(1).lower())
    if not month:
        return ""
    today = date.today()
    year = today.year if month <= today.month else today.year - 1
    return f"{year}-{month:02d}"


def url_ok(url, _cache={}):
    """True when the document is actually downloadable.

    A media library keeps listing files that have been deleted from the
    server: nine of Fident's nineteen entries were 404s. Checking costs one
    HEAD per document and is the difference between a library and a list of
    broken links.
    """
    if url in _cache:
        return _cache[url]
    ok = False
    try:
        r = util.SESSION.head(url, timeout=20, allow_redirects=True)             if hasattr(util, "SESSION") else None
        if r is None or r.status_code >= 400:
            import requests
            r = requests.get(url, timeout=25, stream=True,
                             headers={"User-Agent": config.USER_AGENT})
            r.close()
        ok = r.status_code < 400
    except Exception:
        ok = False
    _cache[url] = ok
    return ok


MONTH_NUMBERS = {m.lower(): i for i, m in enumerate(
    ["", "january", "february", "march", "april", "may", "june", "july",
     "august", "september", "october", "november", "december"])}


PDF_URL = re.compile(r'''https?://[^"'\s<>]+?\.pdf''', re.I)


def collect_page_pdfs(source):
    """Every PDF a page references, including ones only JavaScript renders.

    Some listing pages hold their documents in embedded JSON rather than in
    <a href> tags, so a link-walking scraper sees almost nothing: Buoyant's
    factsheet page carries 79 PDFs but only three anchors. Reading the raw
    HTML for URLs finds them all, at the cost of also finding whatever else
    the page links to - which is what the include/exclude filters are for.

    Prefer this over collect_wp_media when the page has a fuller archive than
    the media library's recent uploads.
    """
    base = source["value"]
    html = util.fetch(base).text
    window = util.window_days(source)
    include_re, exclude_re = _source_filters(source)

    # A page that builds its list from embedded JSON writes the URLs escaped:
    # "https:\/\/host\/file.pdf". Unescaping first is what lets one regex
    # cover both the plain anchors and the JSON payload - without it Buoyant's
    # July and August factsheets were in the HTML and still invisible.
    html = html.replace(r"\/", "/")

    urls, seen = [], set()
    for match in re.finditer(PDF_URL, html):
        url = match.group(0)
        if url not in seen:
            seen.add(url)
            urls.append(url)

    out = []
    for url in urls:
        filename = urlparse(url).path.rsplit("/", 1)[-1]
        if not _passes_filters(filename, include_re, exclude_re):
            continue

        title = _title_from_slug(url)
        if COMPLIANCE_DOC.search(title):
            continue

        # The filename only - a WordPress upload path carries a /YYYY/MM/ that
        # says when the file was uploaded, not which month it covers.
        period = period_from_text(filename) or period_from_month_only(filename)
        if not period:
            continue
        published = period_to_date(period)
        if util.too_old(published, window):
            continue
        if not url_ok(url):
            continue                     # listed but deleted from the server

        out.append({
            "fund_id": source["fund_id"],
            "source_id": source["id"],
            "kind": "newsletter",
            "title": title[:300],
            "url": url,
            "canonical_url": util.canonicalise(url),
            "thumbnail": "",
            "author": source.get("label") or urlparse(base).netloc,
            "summary": "",
            "published_at": published,
            "period": period,
        })

    if source.get("one_per_period"):
        out = _one_per_period(out)
    return out


def _one_per_period(items):
    """Collapse a month's duplicates down to one document.

    Houses publish the same monthly factsheet once per distributor
    ("...-2026-08.pdf" and "...-Axis-2026-08.pdf"). The plain file is the one
    to keep, but it is sometimes published later than a distributor's copy, so
    prefer the shortest filename rather than requiring the plain one to exist.
    """
    best = {}
    for item in items:
        key = item["period"]
        name = urlparse(item["url"]).path.rsplit("/", 1)[-1]
        if key not in best or len(name) < len(best[key][0]):
            best[key] = (name, item)
    return [entry for _, entry in best.values()]


def collect_newsletter_pattern(source):
    """Build monthly URLs from a template and keep the ones that exist.

    Template placeholders: {month} april, {mon} apr, {mm} 04,
                           {yyyy} 2026, {yy} 26
    Useful where a house publishes at a stable path but has no listing page.
    """
    template = source["value"]
    window = util.window_days(source)
    months_back = max(1, window // 30)
    now = datetime.now(timezone.utc)
    # Explicit list: deriving this from MONTHS by name length silently dropped
    # "may", so every May lookup raised KeyError.
    names = {1: "january", 2: "february", 3: "march", 4: "april", 5: "may",
             6: "june", 7: "july", 8: "august", 9: "september",
             10: "october", 11: "november", 12: "december"}

    out = []
    for back in range(months_back + 1):
        month = now.month - back
        year = now.year
        while month <= 0:
            month += 12
            year -= 1
        url = template.format(
            month=names[month], mon=names[month][:3], mm=f"{month:02d}",
            yyyy=year, yy=f"{year % 100:02d}")
        try:
            resp = util.SESSION.head(url, timeout=util.HTTP_TIMEOUT if hasattr(
                util, "HTTP_TIMEOUT") else 20, allow_redirects=True)
        except Exception:
            continue
        if resp.status_code != 200:
            continue
        period = f"{year:04d}-{month:02d}"
        out.append({
            "fund_id": source["fund_id"],
            "source_id": source["id"],
            "kind": "newsletter",
            "title": f"{source.get('label') or 'Newsletter'} — "
                     f"{names[month].title()} {year}",
            "url": url,
            "canonical_url": util.canonicalise(url),
            "thumbnail": "",
            "author": source.get("label") or urlparse(url).netloc,
            "summary": "",
            "published_at": period_to_date(period),
            "period": period,
        })
    return out
