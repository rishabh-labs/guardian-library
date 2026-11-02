"""Add the channels Rishabh supplied, and the videos he picked from them.

Two kinds of channel here, and they are not treated the same:

  A fund house's own channel - Marcellus, Buoyant, Tata Mutual Fund - is
  trusted. Everything on it is theirs, so it comes in unfiltered.

  A media channel - ET Now, Mint, moneycontrol - publishes dozens of videos a
  day about everyone. Those carry an include filter of the manager names we
  track, so only our managers' appearances arrive.

Run once:  python add_channels.py
"""
import sys

import config
import db

# (video id, the fund it belongs to, by name)
VIDEOS = [
    ("hqcQl9RB92A", "Abakkus Flexi Cap"),      # Sunil Singhania on 5paisa
    ("y0dSeaQe_Wo", "Abakkus Flexi Cap"),      # Sanjay Doshi on ET Now
    ("-foiSJWkc9E", "Motilal Mid Cap"),        # Ajay Khandelwal, Motilal's own
    ("zZBtCrpGFCY", "Saurabh Mukherjea"),      # Marcellus
    ("SJ0WZI-LLvo", "Saurabh Mukherjea"),      # Marcellus
    ("SUTEaBaFSHw", "Buoyant PMS"),            # Jigar Mistry
    ("5eAk_b7g0_o", "Old Bridge"),             # Kenneth Andrade on Mint
    ("Dwo28Q2TooI", "Old Bridge"),             # Kenneth Andrade on NDTV Profit
    ("kxiTPyS9S-Q", "Old Bridge"),             # Tarang Agrawal on Money Honey
    ("iBbwtck8gN0", "VQ Growth"),              # Ravi Dharamshi, ValueQuest
    ("QNVXm-Jus0E", "Incred Healthcare"),      # Aditya Khemka on Business Today
    ("mYD5J55Rqvo", "Incred Healthcare"),      # Aditya Khemka on Groww
    ("KKT8Q77yCfc", "Ambit Micro Cap"),        # Ambit's own
    ("1Bjy2FUgmNk", "Tata Small Cap"),         # Chandraprakash Padiyar, Tata's own
    ("ooZmn14etMo", "Tata Small Cap"),         # Pankaj Mathpal on Tata Small Cap
    ("GbXddmSGtI4", "Tata Small Cap"),         # MF Summit panel, Padiyar
]

# (channel id, channel name, fund, include filter, exclude filter)
#
# House channels carry no include filter on purpose. Two of the videos picked
# for the library - Ambit's monthly commentary and ValueQuest's space-sector
# talk - name no manager at all, so filtering a house channel on manager names
# would throw out the very things we were asked to keep. The greeting rules and
# the ten-minute floor do the sifting there instead; the exclude filters below
# only drop the branded campaign series those two channels run.
CHANNELS = [
    # The houses' own channels - everything they post is theirs.
    ("UCk8EZaxKvAi1a5AEe4Hobmg", "Motilal Oswal", "Motilal Mid Cap", "",
     r"Think Wealth|Joy of Growing Up"),
    ("UCjK6_t5lCGl_cX7x7ToBfDQ", "Marcellus", "Saurabh Mukherjea", "", ""),
    ("UC2RNTgRBEPDluh_UJW5qD0w", "Buoyant Capital", "Buoyant PMS", "", ""),
    ("UCZkG_AOkOU0oOmbistyuFHw", "ValueQuest", "VQ Growth", "", ""),
    ("UC43W0oIAgaQlRGfSlkw9BgQ", "Ambit", "Ambit Micro Cap", "",
     r"Portfolio Pulse"),
    ("UC-67d51IstHHVwGL1h-GSww", "Tata Mutual Fund", "Tata Small Cap", "",
     r"Mehfil-E-Fund|Diwali|Holi|Onam|Navratri|Pongal"),

    # Media channels - only our managers' appearances.
    ("UCXcPmSjgThvZ5U69Z3B8tlQ", "5paisa", "Abakkus Flexi Cap",
     r"Sunil Singhania|Sanjay Doshi|Abakkus", ""),
    ("UCI_mwTKUhicNzFrhm33MzBQ", "ET Now", "Abakkus Flexi Cap",
     r"Sunil Singhania|Sanjay Doshi|Abakkus", ""),
    ("UCUI9vm69ZbAqRK3q3vKLWCQ", "Mint", "Old Bridge",
     r"Kenneth Andrade|Tarang Agrawal|Old Bridge", ""),
    ("UC3uJIdRFTGgLWrUziaHbzrg", "NDTV Profit", "Old Bridge",
     r"Kenneth Andrade|Tarang Agrawal|Old Bridge", ""),
    ("UCH6eO0hEYa6iDlNzh3OtAGw", "Money Honey", "Old Bridge",
     r"Kenneth Andrade|Tarang Agrawal|Old Bridge", ""),
    ("UCaPHWiExfUWaKsUtENLCv5w", "Business Today", "Incred Healthcare",
     r"Aditya Khemka|InCred", ""),
    ("UCgzsMmQiwJsE9D43Qx2bBvw", "Thrive by Groww", "Incred Healthcare",
     r"Aditya Khemka|InCred", ""),
    ("UC-n4k3K6l5J3vwbdvD8fp_g", "Pankaj Mathpal", "Tata Small Cap",
     r"Chandraprakash Padiyar|Chandra Prakash Padiyar|Tata Small Cap", ""),
    ("UChftTVI0QJmyXkajQYt2tiQ", "moneycontrol", "Tata Small Cap",
     r"Chandraprakash Padiyar|Chandra Prakash Padiyar|Tata Small Cap", ""),
]

# Managers seen in these videos who were not on the list before.
NEW_MANAGERS = {
    "Abakkus Flexi Cap": "Sanjay Doshi",
    "Abakkus Small Cap": "Sanjay Doshi",
    "Old Bridge": "Tarang Agrawal",
}


def fund_ids():
    return {f["name"]: f["id"] for f in db.list_funds()}


def add_managers():
    added = []
    for fund_name, manager in NEW_MANAGERS.items():
        for f in db.list_funds():
            if f["name"] != fund_name:
                continue
            current = [m.strip() for m in (f["managers"] or "").split(",") if m.strip()]
            if manager.lower() in [c.lower() for c in current]:
                continue
            current.append(manager)
            db.upsert_fund(name=f["name"], house=f["house"],
                           managers=", ".join(current), category=f["category"],
                           match_terms=f["match_terms"], bucket=f["bucket"])
            added.append(f"{manager} -> {fund_name}")
    return added


def fetch(video_ids):
    """Title, thumbnail, length and date for each video, in one call."""
    import re
    import requests
    if not config.YOUTUBE_API_KEY:
        raise SystemExit("YOUTUBE_API_KEY is not set")
    r = requests.get("https://www.googleapis.com/youtube/v3/videos", params={
        "key": config.YOUTUBE_API_KEY, "part": "snippet,contentDetails",
        "id": ",".join(video_ids)}, timeout=60)
    r.raise_for_status()

    def seconds(iso):
        m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
        if not m:
            return None
        h, mi, se = (int(x) if x else 0 for x in m.groups())
        return h * 3600 + mi * 60 + se

    out = {}
    for v in r.json().get("items", []):
        s = v["snippet"]
        thumbs = s.get("thumbnails", {})
        out[v["id"]] = {
            "title": s["title"],
            "channel": s["channelTitle"],
            "published": s["publishedAt"],
            "thumb": (thumbs.get("high") or thumbs.get("medium")
                      or thumbs.get("default") or {}).get("url", ""),
            "secs": seconds(v["contentDetails"].get("duration")),
            "desc": (s.get("description") or "")[:400],
        }
    return out


def add_videos():
    from collectors import util
    meta = fetch([v for v, _ in VIDEOS])
    ids = fund_ids()
    rows, missing, secs = [], [], {}
    for vid, fund_name in VIDEOS:
        if fund_name not in ids:
            missing.append(f"{vid}: no fund called {fund_name!r}")
            continue
        m = meta.get(vid)
        if not m:
            missing.append(f"{vid}: YouTube returned nothing")
            continue
        url = f"https://www.youtube.com/watch?v={vid}"
        secs[util.canonicalise(url)] = m["secs"]
        rows.append({
            "fund_id": ids[fund_name],
            "source_id": None,
            "kind": "video",
            "title": m["title"],
            "url": url,
            "canonical_url": util.canonicalise(url),
            "thumbnail": m["thumb"],
            "author": m["channel"],
            "summary": m["desc"],
            "published_at": m["published"],
        })
    new = db.insert_items(rows)

    # Hand-picked, so they bypass the shelf filters rather than being judged
    # by them - the same treatment the in-house videos get.
    conn = db.connect()
    with conn:
        for r in rows:
            conn.execute(
                """UPDATE items
                   SET content_type='research', classify_why='added by hand',
                       language='en', language_why='added by hand',
                       speaker='manager', speaker_why='added by hand',
                       duration_secs=COALESCE(duration_secs, ?)
                   WHERE canonical_url = ?""",
                (secs.get(r["canonical_url"]), r["canonical_url"]))
    conn.close()
    return rows, new, missing


def add_sources():
    ids = fund_ids()
    added, missing = 0, []
    for chan_id, name, fund_name, include, exclude in CHANNELS:
        if fund_name not in ids:
            missing.append(f"{name}: no fund called {fund_name!r}")
            continue
        db.add_source(ids[fund_name], "youtube_channel", chan_id,
                      f"{name} (YouTube)", include, exclude, 0)
        added += 1
    return added, missing


def main():
    db.init()

    managers = add_managers()
    if managers:
        print("tracked managers added:")
        for m in managers:
            print(f"    {m}")
        print()

    rows, new, missing = add_videos()
    print(f"{len(rows)} video(s) matched to a fund, {new} newly added")
    for m in missing:
        print(f"    SKIPPED {m}")
    print()

    added, src_missing = add_sources()
    print(f"{added} channel source(s) added or kept")
    for m in src_missing:
        print(f"    SKIPPED {m}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
