"""Page watcher for fund-house sites that publish without a feed.

Most AMC / PMS sites have an "Insights", "Newsletter" or "Downloads" page that
lists posts and monthly factsheet PDFs but exposes no RSS. We diff the set of
links on that page: anything we have not recorded before becomes a new item.
"""
import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from . import util

DOC_EXTENSIONS = (".pdf", ".xlsx", ".xls", ".doc", ".docx", ".ppt", ".pptx")

# Chrome, nav and social links that appear on every page and are never content.
NOISE = (
    "facebook.com", "twitter.com", "x.com", "linkedin.com", "instagram.com",
    "youtube.com/channel", "wa.me", "whatsapp.com", "mailto:", "tel:",
    "javascript:", "#",
)


# "Feb 21 . 5 MIN READ READ MORE" - the strip under a post card, not a title.
MONTHS = r"jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec"
META_PHRASES = re.compile(
    r"(?i)\b(read\s+more|know\s+more|view\s+more|learn\s+more|"
    r"\d+\s*min(ute)?s?\s+read|min(ute)?s?\s+read|read)\b")
META_MONTHS = re.compile(rf"(?i)\b({MONTHS})[a-z]*\b")


def _is_meta_strip(text):
    """True when the anchor text is only dates, read-times and 'read more'.

    Strip the known furniture in order, then anything that is a digit or
    punctuation. If nothing is left, there was never a title here.
    """
    cleaned = META_PHRASES.sub(" ", text)
    cleaned = META_MONTHS.sub(" ", cleaned)
    cleaned = re.sub(r"[\d\W_]+", " ", cleaned)
    return not cleaned.strip()


def _title_from_card(anchor):
    """Walk up a few levels looking for the card's heading."""
    node = anchor
    for _ in range(4):
        node = node.parent
        if node is None:
            return None
        heading = node.find(["h1", "h2", "h3", "h4"])
        if heading:
            text = heading.get_text(" ", strip=True)
            if len(text.split()) >= 3:
                return text
    return None


# Anchor text that is navigation no matter where it sits on the page.
NAV_WORDS = {
    "home", "about", "about us", "contact", "contact us", "careers", "login",
    "sign in", "register", "read more", "learn more", "know more", "view all",
    "see all", "download", "click here", "our team", "team", "products",
    "strategies", "insights", "blog", "media", "faq", "faqs", "privacy policy",
    "terms", "terms of use", "disclaimer", "sitemap", "subscribe", "search",
}


def _looks_like_content(href, text):
    low = href.lower()
    if any(n in low for n in NOISE) or low.startswith("#"):
        return False
    if low.endswith(DOC_EXTENSIONS):
        return True

    stripped = text.strip().lower().rstrip(" .>»→")
    if stripped in NAV_WORDS:
        return False

    # A real post title is a phrase, not a two-word product name. Menu entries
    # like "Kings of Capital" clear a 3-word bar, so require 5.
    if len(text.split()) < 5:
        return False

    # And it should point somewhere deeper than a top-level section page.
    path = urlparse(href).path.strip("/")
    return path.count("/") >= 1 or len(path) > 25


CHROME_TAGS = ("nav", "header", "footer", "aside", "menu", "form")
CHROME_HINTS = ("nav", "menu", "header", "footer", "sidebar", "breadcrumb",
                "cookie", "banner", "topbar", "megamenu", "submenu")


def _strip_chrome(soup):
    """Remove site furniture. Without this a fund house's mega-menu shows up as
    a dozen 'new posts' - every product name in the navigation bar.

    Class names are matched loosely, which on some themes hits a wrapper that
    contains the whole page. `_holds_the_content` is the guard: an element
    carrying most of the page's links is the content, whatever it is called.
    """
    total_links = len(soup.find_all("a", href=True))
    # Budget, not just a per-element check. Stripping nav, then footer, then a
    # sidebar can each look harmless on its own while between them removing
    # every link on the page - which is exactly what happened on two sites.
    budget = [int(total_links * 0.6)]

    def _drop(tag):
        if tag.decomposed:
            return
        count = len(tag.find_all("a", href=True))
        if total_links and count > max(3, total_links * 0.25):
            return                      # this element *is* the content
        if count > budget[0]:
            return                      # would strip too much in aggregate
        budget[0] -= count
        tag.decompose()

    for tag in soup.find_all(CHROME_TAGS):
        _drop(tag)
    for tag in soup.find_all(attrs={"role": ["navigation", "banner",
                                             "contentinfo", "menu"]}):
        _drop(tag)
    # Class/id based chrome, which is how most WordPress themes mark it up.
    # Removing a parent invalidates every descendant still in the list, so skip
    # anything already detached before touching its attributes.
    for tag in soup.find_all(attrs={"class": True}):
        if tag.decomposed:
            continue
        blob = " ".join(tag.get("class") or []).lower()
        if any(h in blob for h in CHROME_HINTS):
            _drop(tag)
    for tag in soup.find_all(attrs={"id": True}):
        if tag.decomposed:
            continue
        if any(h in str(tag.get("id") or "").lower() for h in CHROME_HINTS):
            _drop(tag)
    return soup


def _content_root(soup):
    """Prefer the main content region when the page marks one."""
    for selector in ("main", "article", "[role=main]", "#content", ".content",
                     ".posts", ".blog", ".insights"):
        found = soup.select_one(selector)
        if found and found.find("a", href=True):
            return found
    return soup


def collect_page(source):
    """Returns every content-looking link on the page. The UNIQUE constraint on
    (fund_id, canonical_url) means already-recorded links are dropped at insert,
    so only genuinely new posts surface."""
    base = source["value"]
    html = util.fetch(base).text
    soup = _content_root(_strip_chrome(BeautifulSoup(html, "lxml")))

    # A card usually links to the same post two or three times - once from the
    # image, once from the title, once from a "Feb 21 . 5 MIN READ" strip. Keep
    # the longest anchor text, which is the one that reads as a title.
    best = {}
    for a in soup.find_all("a", href=True):
        href = urljoin(base, a["href"].strip())
        text = a.get_text(" ", strip=True)
        if not text or not href.startswith("http"):
            continue
        # Stay on the fund house's own domain.
        if urlparse(href).netloc.replace("www.", "") != \
                urlparse(base).netloc.replace("www.", ""):
            continue
        # Recover a real title when the anchor is just the card's date strip.
        if _is_meta_strip(text):
            recovered = _title_from_card(a)
            if not recovered:
                continue
            text = recovered

        if not _looks_like_content(href, text):
            continue
        canon = util.canonicalise(href)
        if canon == util.canonicalise(base):
            continue
        if canon not in best or len(text) > len(best[canon][1]):
            best[canon] = (href, text)

    out = []
    for canon, (href, text) in best.items():
        out.append({
            "fund_id": source["fund_id"],
            "source_id": source["id"],
            "kind": "document" if href.lower().endswith(DOC_EXTENSIONS) else "news",
            "title": text[:300],
            "url": href,
            "canonical_url": canon,
            "thumbnail": "",
            "author": source.get("label") or urlparse(base).netloc,
            "summary": "",
            # No reliable date on a scraped link; fetched_at carries the ordering.
            "published_at": None,
        })
    return out
