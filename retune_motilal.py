"""Put the Motilal Oswal fund on its new footing.

Renames the fund and its house, swaps Raamdeo Agrawal for the three managers
we actually follow, points the sources at them, and clears out what was
collected for him.

Written as a script rather than done by hand because the daily runner commits
its own copy of data/library.db, so this has to be replayable against
whichever copy wins a rebase.

    python retune_motilal.py            # show what would change
    python retune_motilal.py --apply
"""
import re
import sys

import collectors
import db

OLD_HOUSE = "Motilal"
NAME = "Motilal Oswal Flexi Cap"
HOUSE = "Motilal Oswal"
MANAGERS = ["Ajay Khandelwal", "Ankit Agarwal", "Atul Mehra"]

CHANNEL = "UCk8EZaxKvAi1a5AEe4Hobmg"          # Motilal Oswal's own channel
DROPPED_SEARCH = "Ramdeo Agarwal"

KEEP = re.compile("|".join(MANAGERS), re.I)
# रामदे - his name in Devanagari, which a Latin-only pattern misses.
GONE = re.compile(r"Ra+mdeo|Ra+mdev|रामदे", re.I)


def fund():
    for f in db.list_funds():
        if f["house"] in (OLD_HOUSE, HOUSE):
            return f
    raise SystemExit(f"no fund under {OLD_HOUSE!r} or {HOUSE!r}")


def doomed(fund_id, conn):
    """Videos on this fund that belong to nobody we follow any more.

    Raamdeo Agrawal's, and the house channel's general output - a piece on
    wedding-card spending, another on minting a one-rupee coin. Newsletters
    stay: the monthly outlook is the house's, not any one manager's. Starred
    rows stay: an explicit human call outranks this.
    """
    out = []
    for r in conn.execute(
            "SELECT id, title, author, source_id, kind, starred "
            "FROM items WHERE fund_id = ?", (fund_id,)):
        blob = f"{r['title']} {r['author'] or ''}"
        if KEEP.search(blob) or r["kind"] != "video" or r["starred"]:
            continue
        if GONE.search(blob) or r["source_id"] == channel_source_id(fund_id, conn):
            out.append(dict(r))
    return out


def channel_source_id(fund_id, conn):
    row = conn.execute(
        "SELECT id FROM sources WHERE fund_id = ? AND value = ?",
        (fund_id, CHANNEL)).fetchone()
    return row["id"] if row else None


def main():
    apply = "--apply" in sys.argv
    f = fund()
    conn = db.connect()
    gone = doomed(f["id"], conn)

    print(f"{f['name']} / {f['house']} -> {NAME} / {HOUSE}")
    print(f"managers {f['managers']} -> {', '.join(MANAGERS)}")
    print(f"{len(gone)} video(s) to remove, "
          f"{GONE.pattern and sum(1 for g in gone if GONE.search(g['title']))} "
          f"of them Raamdeo Agrawal's")
    conn.close()

    if not apply:
        print("nothing written - pass --apply")
        return 0

    db.upsert_fund(name=NAME, house=HOUSE, managers=", ".join(MANAGERS),
                   category=f["category"], match_terms=f["match_terms"],
                   fund_id=f["id"], bucket=f["bucket"])

    conn = db.connect()
    row = conn.execute(
        "SELECT id FROM sources WHERE fund_id = ? AND kind = 'youtube_search' "
        "AND value = ?", (f["id"], DROPPED_SEARCH)).fetchone()
    if row:
        db.delete_source(row["id"])

    for name in MANAGERS[1:]:              # Khandelwal already had a search
        db.add_source(f["id"], "youtube_search", name,
                      f"{name} (YouTube search)")

    # The house's own channel is no longer trusted wholesale: it is Raamdeo
    # Agrawal's main outlet and posts a good deal besides.
    with conn:
        conn.execute("UPDATE sources SET include_re = ? WHERE fund_id = ? "
                     "AND value = ?",
                     ("|".join(MANAGERS), f["id"], CHANNEL))

    ids = [g["id"] for g in doomed(f["id"], conn)]
    if ids:
        with conn:
            conn.execute("DELETE FROM items WHERE id IN (%s)"
                         % ",".join("?" * len(ids)), ids)
    print(f"removed {len(ids)} video(s)")

    total = 0
    for s in conn.execute(
            "SELECT * FROM sources WHERE fund_id = ? AND kind IN "
            "('youtube_search','youtube_channel')", (f["id"],)).fetchall():
        s = dict(s)
        s["house"] = HOUSE
        fn = (collectors.youtube.collect_channel if s["kind"] == "youtube_channel"
              else collectors.youtube.collect_search)
        total += db.insert_items(fn(s))
    conn.close()
    print(f"collected {total} new item(s)")

    import classify
    print("classified:", classify.run_pending(limit=300))
    return 0


if __name__ == "__main__":
    sys.exit(main())
