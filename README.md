# Guardian Library

A self-updating research library for the products we're invested in. It watches
fund houses and fund managers across YouTube, news and their own websites, and
files everything on one dashboard — plus an Analysis tab that reads each item
and summarises it, so a 45-minute video can be reviewed in 30 seconds.

Nothing is typed into Google or YouTube by hand. It polls every 30 minutes.

> This is a standalone project. It shares no code, no database and no files with
> `C:\Users\Risha\IndexPortal`.

---

## What it watches

| Source | What it catches | Cost |
|---|---|---|
| `youtube_channel` | Every upload by the fund house's own channel | Free, no API key (uses YouTube's public RSS) |
| `youtube_search` | The manager appearing on CNBC-TV18, ET Now, podcasts | Free tier, ~100 searches/day |
| `news_search` | Press coverage of the fund, house or manager | Free (Google News RSS) |
| `rss` | A fund house blog or podcast feed, a publisher feed | Free |
| `page_watch` | New posts and factsheet PDFs on sites with no feed | Free |

**Not covered:** LinkedIn (no API, scraping breaks constantly) and X/Twitter
(API is paid). X can be added later if it turns out to matter.

---

## Running it locally

```bash
cd C:\Users\Risha\FundLibrary
.venv\Scripts\python.exe app.py
```

Then open <http://localhost:5055>. Or just double-click `Start Portal.bat`.

---

## First-time setup

### How far back it looks

Two windows, deliberately different:

| When | Window | Why |
|---|---|---|
| First time a source is ever polled | **6 months** | builds the library |
| Every refresh after that | **1 month** | a monthly refresh picks up the month just gone |

A fund added later gets its own 6-month backfill on its first poll. Nothing is
ever deleted — the 6-month backlog stays in the library permanently; the window
only controls what gets *ingested*.

Override with `BACKFILL_DAYS` and `INCREMENTAL_DAYS`.

### 1. Load the fund list

Generate the template, fill it in, and import it from the Admin tab:

```bash
.venv\Scripts\python.exe make_template.py
```

Only **Fund Name** is compulsory. Headers are matched loosely — an existing
internal sheet using "Scheme", "AMC", "CIO" or "Site" will import as-is, and
title rows above the header are skipped automatically.

You can also import from the command line:

```bash
.venv\Scripts\python.exe import_funds.py "C:\path\to\your\funds.xlsx" --dry-run
```

Drop `--dry-run` to actually write.

**For the two-tab watchlist** (a managers tab and a houses tab) use
`import_watchlist.py` instead. It merges the overlap between the tabs — the same
house is usually spelled differently on each ("Motilal" vs "Motilal Oswal",
"Mossiac" vs "Mosaic") — and prints every merge and rename so they can be
checked:

```bash
.venv\Scripts\python.exe import_watchlist.py "C:\Claude Wroks\Fund List.xlsx" --dry-run
```

Two things it does that matter for search quality:

- **Short names are expanded.** "Buoyant" alone matches "buoyant markets" and
  "Buoyant Upholstery"; it is searched as "Buoyant Capital". The map is
  `SEARCH_NAME` in `import_watchlist.py` — correct any wrong guess there.
- **All name variants are searched**, not just the tidy one. "SageOne" returns
  11 recent articles where "SageOne Investment Managers" returns 1, so both go
  into the query.

House queries are filtered on distinctive words; a manager's name is trusted as
Google matched it, because the useful articles are often the ones quoting the
manager in the body without naming them in the headline.

**One thing worth doing by hand:** paste each fund house's real YouTube channel
URL into the sheet. Guessed handles 404 — open the channel in a browser and copy
the address bar. Any of these forms work:

```
https://www.youtube.com/@MotilalOswalAMC
@MotilalOswalAMC
UCX5BND8PHnVpCDlI4ckxA7Q
```

### 2. Set the keys

Copy `.env.example` to `.env` and fill in:

- `ADMIN_PASSWORD` — gates the Admin tab. The Library and Analysis tabs are open
  to the whole team.
- `SECRET_KEY` — any long random string.
- `YOUTUBE_API_KEY` — *optional.* Without it, fund houses' own uploads are still
  caught (that path is free RSS); only the keyword search for third-party
  appearances is skipped. Get one at console.cloud.google.com → enable
  "YouTube Data API v3" → Credentials.
- `ANTHROPIC_API_KEY` — *optional.* Powers the Analysis tab. Without it the
  dashboard works fine, the Analysis tab just stays empty.

### 3. Hit "Refresh now" on the Admin tab

After that it runs itself.

---

## Filtering out the marketing

A fund house's channel is mostly promotion — NFO countdowns, festival greetings,
award announcements, 15-second Shorts and conference soundbite cuts. On the test
run, **10 of 15 videos were promo**. The dashboard hides them by default.

Each video is tagged `research` or `promo` using three signals, cheapest first:

1. **Title rules** — free and deterministic. Catches NFO countdowns, greetings,
   awards, "Did you know?", and the "X reflects on…" soundbite pattern.
2. **Duration** — needs `YOUTUBE_API_KEY`, costs 1 quota unit per 50 videos.
   This is the single most decisive signal: under 90 seconds is a Short,
   over 15 minutes is real commentary. **Worth setting the key for this alone.**
3. **Claude** — only for the genuinely ambiguous middle, and only if a key is
   set. Runs on Haiku, so it's negligible cost.

A fourth net catches what the title can't: if a video's transcript comes back
under ~1,200 characters, it's a slogan or a title card, and it's retagged promo.

**When in doubt it keeps the video.** Wrongly hiding a real manager video costs
far more than letting a promo through.

Nothing is ever deleted:

- `N promotional item(s) hidden — Show them` sits above the grid.
- Starring an item always shows it, whatever the classifier decided.
- Every card has a **Mark promo** / **Not promo** button, and hovering the tag
  shows the reason it was classified that way.
- Promos are excluded from summarising, which is what keeps the API bill down.

Set `HIDE_PROMO=0` to show everything by default.

`test_classify.py` is a regression test over 25 labelled titles (13 real ones
from the live run, 12 synthetic patterns from other houses). Run it after
touching the rules:

```bash
.venv\Scripts\python.exe test_classify.py
```

## The Analysis tab

For each new item it pulls the underlying text — YouTube captions, the article
body, or the PDF — and asks Claude for a headline, a short summary, key
highlights, any portfolio actions mentioned, figures quoted, and the stated
outlook.

The prompt is deliberately conservative: it reports only what the source
actually says, never infers a holding or a number, and flags when a manager is
being vague rather than dressing it up as insight.

Two guards on cost:

- Items under ~1,200 characters of text are skipped (a Short or a news blurb
  isn't worth a call). Roughly two-thirds of a fund house's YouTube output is
  Shorts, so this matters.
- At most 25 items are summarised per run (`MAX_ANALYSES_PER_RUN`).

Rough cost at typical volumes: a few US dollars a month. A 34,000-character
video transcript is about 9,000 input tokens.

Set `AUTO_ANALYSE=0` to summarise only on demand via the "Re-summarise" button.

---

## Deploying to the cloud

`render.yaml` is a one-click Render blueprint. Push this folder to a private
GitHub repo, then on render.com choose **New → Blueprint** and point it at the
repo.

Two things matter:

- The persistent disk is mounted at `/data` and `DATA_DIR` points at it, so the
  database survives redeploys. Without a disk you lose everything on each deploy.
- Set `ADMIN_PASSWORD`, `YOUTUBE_API_KEY` and `ANTHROPIC_API_KEY` in the Render
  dashboard, not in the repo.

Any host that reads a `Procfile` (Railway, Fly, Heroku) works the same way.

### The transcript IP block — expect this one

YouTube rate-limits caption requests per IP and blocks most cloud-provider IP
ranges outright. This is not theoretical: it triggered on this machine during
development after a few dozen transcript fetches in quick succession.

Symptom: `IpBlocked` / `RequestBlocked` on videos that play fine in a browser.

- It affects **video summaries only**. Collection keeps running, and news and
  newsletter summaries are unaffected — those don't touch YouTube.
- Items are marked *skipped* with the reason, not *failed*, and the "Re-summarise"
  button retries them once the block clears.
- A local office IP usually recovers within the hour. A cloud host generally
  needs a residential proxy permanently.

Set either `WEBSHARE_PROXY_USERNAME` / `WEBSHARE_PROXY_PASSWORD`, or a generic
`TRANSCRIPT_PROXY_HTTPS`. See `.env.example`. Webshare's residential tier is
about $7/month and is what the transcript library recommends.

---

## Layout

```
app.py              Flask routes, scheduler
config.py           all settings, env-var overridable
db.py               SQLite schema and queries
collectors/
  __init__.py       registry + run loop
  youtube.py        channel feeds, keyword search, handle resolution
  news.py           Google News search, generic RSS
  watch.py          website diffing for sites with no feed
  util.py           URL canonicalisation, date parsing, relevance
extract.py          transcript / article / PDF text extraction
analyse.py          Claude summarisation
import_funds.py     Excel importer
make_template.py    generates funds_template.xlsx
smoke_test.py       live end-to-end check
templates/          base, library, analysis, admin, login
```

## Housekeeping

- `BACKFILL_DAYS` (default 90) stops a newly added source dumping years of back
  catalogue onto the dashboard.
- A `page_watch` source is seeded silently on its first visit — the whole page
  is recorded but marked read, so only genuinely new posts surface afterwards.
- A dead feed never stops the run; the failure is recorded against that source
  and shown in the Admin tab.
- Resolved YouTube channel ids are cached back onto the source, so the handle
  lookup happens once rather than every poll.
