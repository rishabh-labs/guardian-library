"""Configuration. Everything overridable by environment variable so the same
code runs locally and on the cloud host without edits."""
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _load_dotenv():
    """Read a local .env if present. Real environment variables always win, so
    the cloud host's settings are never overridden by a stray committed file."""
    path = os.path.join(BASE_DIR, ".env")
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip("'\""))


_load_dotenv()

# On Render/Railway point DATA_DIR at the mounted persistent disk (e.g. /data)
# so the database survives redeploys.
DATA_DIR = os.environ.get("DATA_DIR", os.path.join(BASE_DIR, "data"))
DB_PATH = os.path.join(DATA_DIR, "library.db")

# YouTube Data API key. Optional: without it, channel uploads still work (they
# come from free RSS feeds) but keyword searches for manager appearances on
# third-party channels are skipped.
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "")

# Password for /admin. Set ADMIN_PASSWORD in the cloud environment.
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "changeme")

# Shared read-only password for the team. Set this before the portal goes on
# the public internet: the library shows which products are held and which were
# exited, and carries the team's own written insights - none of which should be
# readable by anyone who guesses the URL. Empty means no gate, which is fine on
# a laptop and wrong on a server.
VIEWER_PASSWORD = os.environ.get("VIEWER_PASSWORD", "")

# Fund list used to seed a fresh deployment whose database is still empty.
SEED_XLSX = os.environ.get(
    "SEED_XLSX", os.path.join(os.path.dirname(os.path.abspath(__file__)), "Lists.xlsx"))

SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-in-production")

# How often the background collector runs, in minutes.
POLL_MINUTES = int(os.environ.get("POLL_MINUTES", "30"))

# Run the in-process scheduler. Turn off if you drive collection by cron instead.
ENABLE_SCHEDULER = os.environ.get("ENABLE_SCHEDULER", "1") == "1"

# Two different windows, by design:
#   BACKFILL_DAYS    - how far back to reach the FIRST time a source is polled,
#                      i.e. when building the library. 6 months.
#   INCREMENTAL_DAYS - how far back on every refresh after that. 1 month, so a
#                      monthly refresh picks up the month just gone and nothing
#                      older gets re-surfaced.
# A source added later gets its own 6-month backfill on its first poll, which is
# what you want when a new fund is added mid-year.
BACKFILL_DAYS = int(os.environ.get("BACKFILL_DAYS", "180"))
INCREMENTAL_DAYS = int(os.environ.get("INCREMENTAL_DAYS", "30"))

# --- YouTube quota budget -----------------------------------------------
# A keyword search costs 100 units against a free allowance of 10,000/day.
# Channel feeds and newsletters are free, so only the searches need rationing.
#
# Running every source on every 30-minute cycle meant 24 searches x 48 cycles a
# day = 115,200 units, which exhausted the day's quota within about two hours
# and left every later poll returning 429. Searches now run at most once a day;
# the free sources keep their fast cadence.
SEARCH_MIN_HOURS = int(os.environ.get("SEARCH_MIN_HOURS", "20"))

# How many pages of search results to walk. Newest-first, so this only matters
# while filling the six-month backfill; paging stops early once results fall
# outside the window. Worst case 3 x 100 units per manager, so a full
# 24-manager backfill fits inside one day of free quota with room to spare.
SEARCH_MAX_PAGES = int(os.environ.get("SEARCH_MAX_PAGES", "3"))


# --- Analysis tab -------------------------------------------------------
# Claude API key. Without it the dashboard still works; the Analysis tab just
# shows "not configured" instead of summaries.
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANALYSIS_MODEL = os.environ.get("ANALYSIS_MODEL", "claude-sonnet-5")

# Promo-vs-research sorting is a small judgement call on a title and blurb, so
# it runs on a cheaper model than the summaries and only on ambiguous cases.
CLASSIFY_MODEL = os.environ.get("CLASSIFY_MODEL", "claude-haiku-4-5-20251001")

# Hide promotional videos from the Library by default. The "Show promotional"
# toggle reveals them; nothing is ever deleted.
HIDE_PROMO = os.environ.get("HIDE_PROMO", "1") == "1"

# --- Video shelf filters -------------------------------------------------
# Anything shorter than this is a clip, not a discussion. Applies to videos
# only - podcast episodes are judged on their own merits.
MIN_VIDEO_SECONDS = int(os.environ.get("MIN_VIDEO_SECONDS", "600"))   # 10 min

# Keep the shelf to one language. Hindi, Telugu and the rest are still
# collected and still in the database - just hidden behind the toggle.
ENGLISH_ONLY = os.environ.get("ENGLISH_ONLY", "1") == "1"

# Keep only videos the fund manager is actually in. A reviewer's take on a
# fund we hold is a different thing from the manager's own commentary, and
# only the second is worth watching closely.
MANAGER_ONLY = os.environ.get("MANAGER_ONLY", "1") == "1"

# The three video shelves, in nav order.
BUCKETS = [
    ("active", "Active Strategies", "Products we hold"),
    ("inactive", "Inactive Strategies", "Products we have exited"),
    ("knowledge", "Knowledge Centre", "Managers we follow to learn from"),
]

# Off by default: nothing is summarised automatically. A newsletter is
# summarised only when you open it and ask, so the API bill is a function of
# what you actually read rather than what gets collected.
AUTO_ANALYSE = os.environ.get("AUTO_ANALYSE", "0") == "1"

# Only used if AUTO_ANALYSE is switched on.
MAX_ANALYSES_PER_RUN = int(os.environ.get("MAX_ANALYSES_PER_RUN", "25"))

# Item kinds that may be summarised. Videos are excluded: transcripts are long,
# so they cost far more per item than a newsletter does.
ANALYSABLE_KINDS = {"newsletter", "document"}

# Transcripts of long videos get truncated to keep cost predictable.
MAX_SOURCE_CHARS = int(os.environ.get("MAX_SOURCE_CHARS", "120000"))

# Skip summarising thin content (a 200-char news blurb isn't worth a call).
MIN_SOURCE_CHARS = int(os.environ.get("MIN_SOURCE_CHARS", "1200"))

# --- YouTube transcript proxy -------------------------------------------
# YouTube rate-limits transcript requests per IP and blocks most cloud-provider
# IP ranges outright. Symptom is IpBlocked / RequestBlocked on videos that play
# fine in a browser. Only transcripts are affected - collection keeps working.
#
# Two ways to fix it, both optional:
#   1. Webshare residential proxies (what the library recommends):
#        WEBSHARE_PROXY_USERNAME / WEBSHARE_PROXY_PASSWORD
#   2. Any generic HTTP proxy:
#        TRANSCRIPT_PROXY_HTTP / TRANSCRIPT_PROXY_HTTPS
WEBSHARE_PROXY_USERNAME = os.environ.get("WEBSHARE_PROXY_USERNAME", "")
WEBSHARE_PROXY_PASSWORD = os.environ.get("WEBSHARE_PROXY_PASSWORD", "")
TRANSCRIPT_PROXY_HTTP = os.environ.get("TRANSCRIPT_PROXY_HTTP", "")
TRANSCRIPT_PROXY_HTTPS = os.environ.get("TRANSCRIPT_PROXY_HTTPS", "")

HTTP_TIMEOUT = 20
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
