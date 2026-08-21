"""Live end-to-end check: seeds two real fund houses, polls every collector,
prints what came back. Safe to re-run - it writes to data/library.db only.

    python smoke_test.py
"""
import os
import sys

os.environ.setdefault("ENABLE_SCHEDULER", "0")

import collectors  # noqa: E402
import config      # noqa: E402
import db          # noqa: E402

SEED = [
    dict(name="Marcellus Consistent Compounders",
         house="Marcellus Investment Managers",
         managers="Saurabh Mukherjea, Rakshit Ranjan",
         category="PMS",
         # Left blank deliberately: paste the real channel URL from the browser
         # address bar. Guessed handles 404 - the resolver reports that clearly
         # rather than silently collecting nothing.
         youtube="",
         website="https://marcellus.in/blog/"),
    dict(name="Motilal Oswal PMS",
         house="Motilal Oswal Asset Management",
         managers="Prateek Agrawal",
         category="PMS",
         youtube="https://www.youtube.com/@MotilalOswalAMC",
         website=""),
]


def main():
    db.init()
    print(f"database: {config.DB_PATH}\n")

    for s in SEED:
        fid = db.upsert_fund(name=s["name"], house=s["house"],
                             managers=s["managers"], category=s["category"])
        if s["youtube"]:
            db.add_source(fid, "youtube_channel", s["youtube"], "own channel")
        if s["website"]:
            db.add_source(fid, "page_watch", s["website"], "blog")
        terms = [s["name"], s["house"]] + [m.strip() for m in s["managers"].split(",")]
        db.add_source(fid, "news_search",
                      " OR ".join(f'"{t}"' for t in terms), "Google News")
        print(f"seeded: {s['name']}")

    print("\npolling every source...\n")
    result = collectors.run_all()

    print(f"\n=== {result['new_items']} new item(s), "
          f"{result['ok']} source(s) ok, {result['failed']} failed ===\n")

    for src in db.list_sources():
        flag = "  " if "ok" in src["last_status"] or "seeded" in src["last_status"] else "!!"
        print(f"{flag} {src['kind']:16} {src['last_status'][:90]}")

    print("\n--- 12 most recent items ---")
    for it in db.query_items(limit=12):
        print(f"  [{it['kind']:8}] {(it['published_at'] or '')[:10]:10} "
              f"{it['fund_name'][:22]:24} {it['title'][:60]}")

    total = db.count_items()
    print(f"\ntotal items in library: {total}")
    return 0 if total else 1


if __name__ == "__main__":
    sys.exit(main())
