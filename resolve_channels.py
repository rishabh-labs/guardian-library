"""Find each fund house's official YouTube channel and subscribe to its feed.

Searching YouTube for a house *name* pulls in retail tutorials, stock-tip
channels and unrelated people who happen to share the name ("Pastor Marcellus").
Subscribing to the official channel instead is exact: it returns that channel's
uploads and nothing else, and afterwards costs no quota at all because it reads
the free RSS feed.

    python resolve_channels.py            # show candidates, write nothing
    python resolve_channels.py --apply    # add confident matches as sources
    python resolve_channels.py --apply --drop-house-search
"""
import argparse
import re
import sys

import config
import db
from collectors import util

SEARCH_API = "https://www.googleapis.com/youtube/v3/search"
CHANNELS_API = "https://www.googleapis.com/youtube/v3/channels"

# Words that must not be the only thing matching a channel title.
GENERIC = util.GENERIC_TOKENS


def search_channels(query, limit=5):
    data = util.fetch(SEARCH_API, params={
        "key": config.YOUTUBE_API_KEY, "part": "snippet", "q": query,
        "type": "channel", "maxResults": limit}).json()
    out = []
    for it in data.get("items", []):
        cid = it["id"].get("channelId") or it["snippet"].get("channelId")
        if cid:
            out.append({"id": cid,
                        "title": it["snippet"]["title"],
                        "desc": it["snippet"].get("description", "")})
    return out


def channel_stats(channel_ids):
    """Subscriber and video counts, to tell an official channel from a fan one."""
    if not channel_ids:
        return {}
    data = util.fetch(CHANNELS_API, params={
        "key": config.YOUTUBE_API_KEY, "part": "statistics,snippet",
        "id": ",".join(channel_ids)}).json()
    out = {}
    for it in data.get("items", []):
        s = it.get("statistics", {})
        out[it["id"]] = {
            "subs": int(s.get("subscriberCount", 0) or 0),
            "videos": int(s.get("videoCount", 0) or 0),
            "title": it["snippet"]["title"],
        }
    return out


def score(house, cand, stats):
    """How confident are we that this is the house's own channel?"""
    want = util.term_tokens(house)
    title_tokens = set(re.findall(r"[a-z0-9]+", cand["title"].lower()))

    if not want <= title_tokens:
        return 0, "distinctive words missing from channel title"

    st = stats.get(cand["id"], {})
    subs, videos = st.get("subs", 0), st.get("videos", 0)

    points = 60
    reason = []
    if subs >= 50_000:
        points += 20
        reason.append(f"{subs:,} subs")
    elif subs >= 5_000:
        points += 10
        reason.append(f"{subs:,} subs")
    else:
        points -= 10
        reason.append(f"only {subs:,} subs")

    if videos >= 100:
        points += 10
        reason.append(f"{videos} videos")
    elif videos < 10:
        points -= 20
        reason.append(f"only {videos} videos")

    # An exact title match is the strongest signal available.
    if util.term_tokens(cand["title"]) == want:
        points += 15
        reason.append("title matches exactly")

    return points, ", ".join(reason)


def run(apply=False, drop_house_search=False, threshold=70):
    if not config.YOUTUBE_API_KEY:
        print("YOUTUBE_API_KEY is not set")
        return 1
    db.init()

    confident, unsure = [], []
    for fund in db.list_funds(active_only=True):
        house = fund["name"]
        try:
            cands = search_channels(house)
        except Exception as exc:
            print(f"  {house[:26]:28} search failed: {exc}")
            continue
        stats = channel_stats([c["id"] for c in cands])

        ranked = sorted(((score(house, c, stats), c) for c in cands),
                        key=lambda t: -t[0][0])
        if not ranked:
            unsure.append((fund, None, "no channels returned"))
            continue

        (points, why), best = ranked[0]
        if points >= threshold:
            confident.append((fund, best, points, why))
        else:
            unsure.append((fund, best, why))

    print(f"=== confident matches ({len(confident)}) ===")
    for fund, ch, points, why in confident:
        print(f"  {fund['name'][:26]:28} -> {ch['title'][:32]:34} "
              f"[{points}] {why}")

    print(f"\n=== needs a channel URL from you ({len(unsure)}) ===")
    for fund, ch, why in unsure:
        got = f"best guess: {ch['title'][:30]}" if ch else "nothing found"
        print(f"  {fund['name'][:26]:28} {got:44} ({why})")

    if not apply:
        print("\nNothing written. Re-run with --apply to add these.")
        return 0

    for fund, ch, points, why in confident:
        db.add_source(fund["id"], "youtube_channel", ch["id"],
                      f"{ch['title']} (official)")
    print(f"\nadded {len(confident)} channel feed(s)")

    if drop_house_search:
        managers = {}
        for fund in db.list_funds():
            managers[fund["id"]] = {m.strip().lower()
                                    for m in (fund["managers"] or "").split(",")
                                    if m.strip()}
        removed = 0
        for s in db.list_sources():
            if s["kind"] != "youtube_search":
                continue
            if s["value"].strip().lower() not in managers.get(s["fund_id"], set()):
                db.delete_source(s["id"])
                removed += 1
        print(f"removed {removed} house-name YouTube search(es) — "
              f"manager-name searches kept")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--drop-house-search", action="store_true")
    ap.add_argument("--threshold", type=int, default=70)
    args = ap.parse_args()
    sys.exit(run(args.apply, args.drop_house_search, args.threshold))
