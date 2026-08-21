"""The people worth searching for at each fund house.

The uploaded sheet named a manager for only some houses. For the rest the house
name alone is a poor search term - Old Bridge's content is almost all Kenneth
Andrade speaking, and no amount of searching "Old Bridge Capital" finds it.

These are added as YouTube name searches, which is what catches appearances on
CNBC-TV18, ET Now and podcasts. Names from the sheet are kept as-is; the ones
here are additions.

Correct anything wrong in Admin, or edit this file and re-run.

    python key_people.py --dry-run
    python key_people.py
"""
import argparse
import sys

# house name in the database -> people who speak for it publicly
PEOPLE = {
    "Old Bridge Capital": ["Kenneth Andrade"],
    "SageOne Investment Managers": ["Samit Vartak"],
    "Marcellus": ["Saurabh Mukherjea", "Rakshit Ranjan"],
    "Ambit Capital": ["Trilok Agarwal", "Bhargav Buddhadev"],
    "DSP Netra": ["Sahil Kapoor", "Vinit Sambre"],
    "ValueQuest": ["Ravi Dharamshi"],
    "Motilal Oswal": ["Raamdeo Agrawal", "Prateek Agrawal"],
    "PPFAS": ["Raunak Onkar", "Neil Parikh"],
    "Kotak Mutual Fund": ["Nilesh Shah", "Harsha Upadhyaya"],
    "ICICI Prudential AMC": ["S Naren"],
    "SBI Mutual Fund": ["R Srinivasan", "Dinesh Balachandran"],
    "Tata Mutual Fund": ["Rahul Singh"],
    "Buoyant Capital": ["Sachin Khivasara"],
    "2Point2 Capital": ["Amit Mantri"],
    "Axis Bank": [],          # Neelkanth Mishra already comes from the sheet
    "Mosaic Asset Management": [],
    "Fident Asset Management": [],
}

# Podcasts a house runs itself. Attached as `rss` sources.
HOUSE_PODCASTS = {
    # "Motilal Oswal": [("https://...", "Indian Market in Minutes")],
}

# House-name YouTube searches, for houses that have no channel of their own.
# Searching "Old Bridge Mutual Fund" surfaces Kenneth Andrade's interviews on
# other people's channels, which is the only way to see them.
#
# The query is deliberately the *qualified* name, not the bare one: plain
# "Old Bridge" and "Marcellus" returned bridges and a pastor. Results are then
# filtered on the finance check and the phrase rule, so the query only has to
# be roughly right.
HOUSE_SEARCHES = {
    "Old Bridge Capital": "Old Bridge Mutual Fund",
    "2Point2 Capital": "2Point2 Capital PMS",
    "SageOne Investment Managers": "SageOne Investment Managers",
    "Mosaic Asset Management": "Mosaic Asset Management India",
}


def run(dry_run=False):
    sys.path.insert(0, ".")
    import db
    db.init()

    funds = {f["name"]: f for f in db.list_funds()}
    existing = {}
    for s in db.list_sources():
        existing.setdefault(s["fund_id"], set()).add(
            (s["kind"], s["value"].strip().lower()))

    added = 0
    for house, names in PEOPLE.items():
        if house not in funds:
            print(f"  no such fund: {house}")
            continue
        fund = funds[house]
        already = {m.strip().lower()
                   for m in (fund["managers"] or "").split(",") if m.strip()}
        for name in names:
            if name.lower() in already:
                continue
            if ("youtube_search", name.lower()) in existing.get(fund["id"], set()):
                continue
            print(f"  + {house[:26]:28} {name}")
            added += 1
            if not dry_run:
                db.add_source(fund["id"], "youtube_search", name,
                              f"{name} on YouTube")
                # Record them on the fund too, so the relevance filter and the
                # promo classifier both know this person speaks for the house.
                merged = [m.strip() for m in (fund["managers"] or "").split(",")
                          if m.strip()] + [name]
                db.upsert_fund(
                    name=fund["name"], house=fund["house"],
                    managers=", ".join(dict.fromkeys(merged)),
                    category=fund["category"], match_terms=fund["match_terms"],
                    active=fund["active"], fund_id=fund["id"])
                fund = db.get_fund(fund["id"])

    # House-name searches, but only where the house has no channel feed -
    # a channel is exact, so searching its name as well would just add noise.
    with_channel = {s["fund_id"] for s in db.list_sources()
                    if s["kind"] == "youtube_channel"}
    for house, query in HOUSE_SEARCHES.items():
        if house not in funds:
            print(f"  no such fund: {house}")
            continue
        fund = funds[house]
        if fund["id"] in with_channel:
            print(f"  - {house[:26]:28} skipped, has an official channel")
            continue
        if ("youtube_search", query.lower()) in existing.get(fund["id"], set()):
            continue
        print(f"  + {house[:26]:28} search {query!r}")
        added += 1
        if not dry_run:
            db.add_source(fund["id"], "youtube_search", query,
                          f"{query} on YouTube")

    for house, feeds in HOUSE_PODCASTS.items():
        if house not in funds:
            continue
        for url, label in feeds:
            print(f"  + {house[:26]:28} podcast {label}")
            added += 1
            if not dry_run:
                db.add_source(funds[house]["id"], "rss", url, label)

    print(f"\n{added} source(s) "
          f"{'would be added' if dry_run else 'added'}")
    return added


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    run(args.dry_run)
