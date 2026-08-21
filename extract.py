"""Pull the readable text out of an item so it can be summarised.

Three paths, picked from the item's URL:
  video    -> YouTube transcript (auto-captions are fine), free, no API key
  document -> PDF text via pypdf
  news     -> article body via trafilatura
"""
import io
import logging
import re

import config
from collectors import util

log = logging.getLogger("extract")

YT_ID = re.compile(r"(?:v=|youtu\.be/|/shorts/|/embed/)([\w-]{11})")

# Indian fund commentary is frequently part-Hindi; ask for those tracks too.
TRANSCRIPT_LANGS = ["en", "en-IN", "en-GB", "en-US", "hi"]


class NoContent(Exception):
    """Raised when there is nothing substantial to summarise."""


def youtube_id(url):
    m = YT_ID.search(url or "")
    return m.group(1) if m else None


def _proxy_kwargs():
    """Build the proxy config for youtube-transcript-api, if one is configured.

    Returns {} when no proxy is set, which is the normal local case - an office
    IP is usually fine. Cloud hosts nearly always need one.
    """
    if not (config.WEBSHARE_PROXY_USERNAME or config.TRANSCRIPT_PROXY_HTTP
            or config.TRANSCRIPT_PROXY_HTTPS):
        return {}
    try:
        from youtube_transcript_api.proxies import (GenericProxyConfig,
                                                    WebshareProxyConfig)
    except ImportError:
        log.warning("proxy configured but this youtube-transcript-api build "
                    "has no proxy support - ignoring")
        return {}

    if config.WEBSHARE_PROXY_USERNAME:
        return {"proxy_config": WebshareProxyConfig(
            proxy_username=config.WEBSHARE_PROXY_USERNAME,
            proxy_password=config.WEBSHARE_PROXY_PASSWORD)}
    return {"proxy_config": GenericProxyConfig(
        http_url=config.TRANSCRIPT_PROXY_HTTP or None,
        https_url=config.TRANSCRIPT_PROXY_HTTPS or None)}


def from_youtube(url):
    """Fetch the caption track. Works with youtube-transcript-api 1.x (instance
    .fetch) and falls back to the 0.6 static .get_transcript for older installs."""
    import youtube_transcript_api as yta

    vid = youtube_id(url)
    if not vid:
        raise NoContent("not a recognisable YouTube URL")

    # Anything here means "this video has no usable captions" rather than a bug,
    # so it should mark the item skipped, not failed.
    no_captions = tuple(
        getattr(yta, name) for name in
        ("TranscriptsDisabled", "NoTranscriptFound", "VideoUnavailable",
         "VideoUnplayable", "AgeRestricted", "InvalidVideoId",
         "NotTranslatable")
        if hasattr(yta, name))

    try:
        api = yta.YouTubeTranscriptApi(**_proxy_kwargs())
        if hasattr(api, "fetch"):                      # 1.x
            fetched = api.fetch(vid, languages=TRANSCRIPT_LANGS)
            parts = [s.text for s in fetched]
        else:                                          # 0.6.x
            raw = yta.YouTubeTranscriptApi.get_transcript(
                vid, languages=TRANSCRIPT_LANGS)
            parts = [p["text"] for p in raw]
    except no_captions as exc:
        raise NoContent(f"no transcript available ({type(exc).__name__})") from exc
    except Exception as exc:
        # IpBlocked / RequestBlocked show up when YouTube throttles a datacenter
        # IP. Worth surfacing distinctly - it is fixed with a proxy, not a retry.
        name = type(exc).__name__
        if name in ("IpBlocked", "RequestBlocked", "PoTokenRequired"):
            raise NoContent(
                f"YouTube blocked the transcript request ({name}). If this is "
                f"persistent on the cloud host, set a proxy for transcripts."
            ) from exc
        raise

    text = " ".join(p.replace("\n", " ") for p in parts)
    return re.sub(r"\s+", " ", text).strip()


def from_pdf(url):
    from pypdf import PdfReader
    resp = util.fetch(url)
    reader = PdfReader(io.BytesIO(resp.content))
    pages = []
    for page in reader.pages[:60]:          # factsheets get long; 60 is plenty
        try:
            pages.append(page.extract_text() or "")
        except Exception as exc:            # a single broken page must not kill it
            log.debug("pdf page failed: %s", exc)
    text = re.sub(r"\s+", " ", " ".join(pages)).strip()
    if not text:
        raise NoContent("PDF has no extractable text (probably a scan)")
    return text


def from_article(url):
    import trafilatura
    downloaded = trafilatura.fetch_url(url)
    if downloaded is None:
        downloaded = util.fetch(url).text
    text = trafilatura.extract(downloaded, include_comments=False,
                               include_tables=True, favor_precision=True)
    if not text:
        raise NoContent("could not extract an article body")
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def get_text(item):
    """Returns (text, source_kind). Raises NoContent when nothing usable."""
    url = item["url"]
    low = url.lower()

    if youtube_id(url):
        text, kind = from_youtube(url), "transcript"
    elif low.endswith(".pdf") or item["kind"] == "document":
        text, kind = from_pdf(url), "pdf"
    else:
        text, kind = from_article(url), "article"

    if len(text) < config.MIN_SOURCE_CHARS:
        raise NoContent(f"only {len(text)} chars of text - too thin to summarise")

    if len(text) > config.MAX_SOURCE_CHARS:
        # Keep the opening and the closing: intros frame the thesis, closings
        # carry the outlook. The dropped middle is noted for the model.
        half = config.MAX_SOURCE_CHARS // 2
        text = (text[:half] + "\n\n[... middle section omitted for length ...]\n\n"
                + text[-half:])
    return text, kind
