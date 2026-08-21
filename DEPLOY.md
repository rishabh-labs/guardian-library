# Putting Guardian Library on the internet

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
