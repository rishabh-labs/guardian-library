# Putting Guardian Library on the internet

> **Live at https://rishabh-labs.github.io/guardian-library/** - GitHub Actions
> collects every morning at 07:30 IST and republishes the site. Free, permanent,
> and independent of any laptop being switched on.
>
> **No password.** The published site is open to anyone with the link, by
> choice (2026-09-24). The repository is public, which is what GitHub Pages
> requires on a free account.
>
> **Not on the published copy:** the 31 in-house videos and Insights. Both need
> a running server - the videos are 165-451 MB each against GitHub's 100 MB
> per-file limit. Run the portal locally (Share Portal.bat) for those.

## Visibility: decided

The published site is **public**. On GitHub Free and Pro a Pages site is
readable by anyone with the link even when the repo behind it is private
(private Pages is an Enterprise feature). That was raised and accepted on
2026-08-21: the videos and factsheets are public material anyway, and the shelf
labels are the only thing that reveals the shape of the book.

The repository itself stays private - it holds `Lists.xlsx`.

Two things follow from the decision, both already in place:

- Every published page carries `noindex, nofollow, noarchive`, and the site
  serves a `robots.txt` that disallows everything. Readable by link, not
  findable by search - a fund house cannot stumble on it by googling its name.
- If you later want it genuinely private, publish the same `site/` folder to
  Cloudflare Pages and turn on Access with an email policy. Free for up to 50
  users, and nothing about the build changes.

## The scheduled job

`.github/workflows/collect.yml` runs daily at 02:00 UTC (07:30 IST) and can be
triggered by hand from the **Actions** tab with **Run workflow** - that is the
fetch-now button. Each run:

1. collects videos and newsletters (no failure stops the rest),
2. rebuilds the static site,
3. commits `data/library.db` back to the repo,
4. publishes to Pages.

Step 3 matters: the database holds `last_checked` for every source. Without it
each run would think it had never polled, redo the six-month backfill, and
exhaust the YouTube quota within a day or two.

Set one repository secret, under Settings -> Secrets and variables -> Actions:

| Secret | Value |
|---|---|
| `YOUTUBE_API_KEY` | the key from your local `.env` |

Then Settings -> Pages -> Source -> **GitHub Actions**.

A run takes two or three minutes. A private repo gets 2,000 free Actions minutes
a month, so a daily run uses about 3% of the allowance.

## What the published copy cannot do

Insights, starring, mark-as-read and Summarise all write to the database, and a
static page has nowhere to write to. They are left out of the build rather than
shipped as buttons that quietly do nothing. Everything else - three shelves, the
newsletter archive by house, the analysis tab, the filters already applied -
is there.

Summaries you generate locally *do* appear on the published site, because they
live in the database that gets committed. Run them on your machine through the
Claude Code provider, push, and the next build picks them up.

## The original Render route

Everything below still applies if you later want the live app with Insights
working.


Fifteen minutes, start to finish. Everything in the repo is ready; the steps
below are the ones that need your accounts, which is why they are not automated.

## Before you start

**The GitHub repository must be private.** It contains `Lists.xlsx`, which names
the products actually held and exited. Nothing else sensitive is committed — the
database, `.env`, and all API keys stay out by `.gitignore`.

**The Render plan must be a paid one** (Starter, about $7/month, plus roughly
$0.25/month for the 1 GB disk). The free tier has no persistent disk: the
database would be wiped on every restart, and while videos and newsletters would
re-collect themselves within the hour, everyone's written Insights would be gone
for good. That is the one thing the portal cannot rebuild.

## 1. Push the code

The repository is already initialised and committed locally. Create an **empty
private repo** on github.com, then from `C:\Users\Risha\FundLibrary`:

    git remote add origin https://github.com/<you>/guardian-library.git
    git branch -M main
    git push -u origin main

## 2. Create the service

1. Sign in at [render.com](https://render.com) and pick **New → Blueprint**.
2. Connect the GitHub account and choose the repo. Render reads `render.yaml`
   and proposes one web service, `guardian-library`, with a 1 GB disk at `/data`.
3. It will ask for the four values marked `sync: false`. Fill in:

   | Variable | What to put |
   |---|---|
   | `VIEWER_PASSWORD` | the shared password you give colleagues |
   | `ADMIN_PASSWORD` | a different password, only for you |
   | `YOUTUBE_API_KEY` | the key already in your local `.env` |
   | `ANTHROPIC_API_KEY` | leave blank until you want newsletter summaries |

4. **Apply**. The first build takes three or four minutes.

## 3. First boot

The database starts empty, so the app seeds itself from `Lists.xlsx` — 26 funds
and 41 sources — then runs its first collection. Give it fifteen minutes and the
shelves fill up. After that it refreshes every 30 minutes on its own.

## 4. Hand it out

Render gives you a URL like `https://guardian-library.onrender.com`. Send that
plus the viewer password to the team. They sign in once and stay signed in for
30 days per browser. Only your admin password reaches the Admin tab.

## Keeping the API key safe

The YouTube key currently in `.env` is restricted by HTTP referrer or IP in the
Google Cloud console. Once the portal runs on Render it calls from Render's IPs,
so either widen that restriction to "YouTube Data API v3 only" with no IP
restriction, or add Render's outbound addresses. If searches come back 403 after
deploying, this is why.

## Cheaper alternative

If $7/month is not worth it, the same app runs on any office PC that stays on:

    python app.py

then expose it with a free Cloudflare Tunnel (`cloudflared tunnel --url
http://localhost:5055`). Colleagues get a URL that works anywhere. The catch is
that the portal is only up while that PC is on and awake.
