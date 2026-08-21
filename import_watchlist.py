"""Import the two-tab watchlist: fund managers, and fund houses.

The two tabs overlap - a house named on the managers tab usually appears on the
houses tab too, often spelled differently ("Motilal" vs "Motilal Oswal",
"Buoyant" vs "Buoyant PMS"). Importing them naively would create duplicate
entries that then collect the same news twice, so names are normalised and
merged, and every merge is printed for you to check.

    python import_watchlist.py "C:\\Claude Wroks\\Fund List.xlsx"
    python import_watchlist.py "...xlsx" --dry-run
"""
import argparse
import re
import sys

import db

# Words that carry no identity - stripped before comparing two names.
NOISE = {
    "pms", "amc", "capital", "asset", "assets", "management", "managements",
    "mutual", "fund", "funds", "house", "houses", "newsletter", "letter",
    "news", "manager", "managers", "advisors", "advisers", "investment",
    "investments", "india", "ltd", "limited", "private", "pvt", "the", "and",
    "bank", "prudential", "co", "company", "partners", "llp",
    # month names: "Sageone October News Letter" is just SageOne
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december",
}

# Genuine spelling variants that normalisation alone cannot bridge.
SPELLING_FIX = {
    "mossiac": "mosaic",
}

# Short-form names from the sheet that are too generic to search on their own.
# "Buoyant" alone matches "buoyant markets" and "Buoyant Upholstery"; "VQ" is
# meaningless to a search engine. Keyed by normalised name -> the name actually
# used in queries and shown on the dashboard.
#
# These are assumptions. Every substitution is printed at import so it can be
# corrected in Admin if any of them is the wrong entity.
SEARCH_NAME = {
    "buoyant": "Buoyant Capital",
    "vq growth": "ValueQuest",
    "2 point 2": "2Point2 Capital",
    "sageone": "SageOne Investment Managers",
    "old bridge": "Old Bridge Capital",
    # Ambit's research/PMS arm publishes as "Ambit Capital" - that name returns
    # 36 recent articles against 1 for "Ambit Asset Management".
    "ambit": "Ambit Capital",
    "fident": "Fident Asset Management",
    "tata": "Tata Mutual Fund",
    "mosaic": "Mosaic Asset Management",
    "vq": "ValueQuest",
}

# Rows to ignore on import. "Economist" in the sheet meant the publication,
# which isn't wanted here.
SKIP = {"economist"}

# Names that are too broad to search usefully. Imported as given, but called
# out so you can decide what you actually want.
QUESTIONABLE = {
    "axis": ("a whole bank — news is dominated by banking stories, not "
             "Neelkanth Mishra's commentary. His own query is separate."),
}

# People tracked for macro commentary rather than fund performance. A fund
# context ("PMS OR AMC OR portfolio") is the wrong filter for an economist.
MACRO_CONTEXT = ('(economy OR economist OR macro OR GDP OR inflation OR '
                 'fiscal OR monetary OR RBI OR budget OR "interest rates")')
MACRO_PEOPLE = set()   # normalised names; filled in once an identity is confirmed

# Google News on a bare name like "Ambit" or "Old Bridge" returns mostly
# unrelated articles, so every query is anchored to a finance context.
HOUSE_CONTEXT = ('(PMS OR "mutual fund" OR AMC OR portfolio OR '
                 '"fund manager" OR investment OR investors)')
MANAGER_CONTEXT = ('(fund OR PMS OR AMC OR investing OR markets OR '
                   'portfolio OR equity OR stocks)')


# Suffixes that describe the *content* rather than the house, and should not
# end up in the display name: "Fident- newsletter", "Sageone October News Letter".
DISPLAY_STRIP = [
    re.compile(r"\s*[-–—]?\s*(october\s+)?news\s*letter\s*$", re.I),
    re.compile(r"\s*[-–—]\s*fund\s+manager\s*$", re.I),
    re.compile(r"\s*[-–—]\s*$"),
    re.compile(r"\s+pms\s*$", re.I),
]


def clean_display(name, managers=()):
    """Tidy a raw sheet name into something to show on the dashboard."""
    out = name.strip()
    for pattern in DISPLAY_STRIP:
        out = pattern.sub("", out).strip()
    # "Tata Fund House - Chandraprakash" -> "Tata Fund House"
    for mgr in managers:
        for part in [mgr] + mgr.split():
            if len(part) < 4:
                continue
            out = re.sub(rf"\s*[-–—]\s*{re.escape(part)}\s*$", "", out,
                         flags=re.I).strip()
    return out or name.strip()


def pick_display(aliases, managers=()):
    """Choose the best name from the variants seen across both tabs.

    Longest wins - "Motilal Oswal" is more useful than "Motilal" - except that
    a known misspelling never wins over a correctly spelled variant.
    """
    cleaned = {clean_display(a, managers) for a in aliases}
    cleaned = {c for c in cleaned if c}
    if not cleaned:
        return next(iter(aliases))

    def misspelt(name):
        tokens = re.sub(r"[^a-z0-9 ]", " ", name.lower()).split()
        return any(t in SPELLING_FIX for t in tokens)

    good = {c for c in cleaned if not misspelt(c)}
    pool = good or cleaned
    return sorted(pool, key=lambda s: (-len(s), s))[0]


def normalise(name):
    """Reduce a name to its identifying core for comparison."""
    s = re.sub(r"[^a-z0-9 ]", " ", str(name or "").lower())
    tokens = [t for t in s.split() if t and t not in NOISE]
    tokens = [SPELLING_FIX.get(t, t) for t in tokens]
    return " ".join(tokens)


def same_entity(a, b):
    """True when two normalised names refer to the same house.

    Substring rather than equality, so "motilal" matches "motilal oswal" and
    "tata" matches "tata chandraprakash".
    """
    if not a or not b:
        return False
    if a == b:
        return True
    shorter, longer = sorted([a, b], key=len)
    # Require a whole-word prefix match, so "sbi" never swallows "sbi life".
    return longer.startswith(shorter + " ")


def read_sheets(path):
    from openpyxl import load_workbook
    wb = load_workbook(path, data_only=True, read_only=True)

    managers, houses = [], []
    for sheet in wb.sheetnames:
        ws = wb[sheet]
        rows = [[("" if c is None else str(c).strip()) for c in r]
                for r in ws.iter_rows(values_only=True)]
        rows = [r for r in rows if any(r)]
        if not rows:
            continue

        header = " ".join(rows[0]).lower()
        is_manager_tab = "manager" in header and "house" in header

        for row in rows[1:]:
            cells = [c for c in row if c]
            if not cells:
                continue
            if is_manager_tab:
                name = cells[0]
                house = cells[1] if len(cells) > 1 else ""
                managers.append((name, house))
            else:
                houses.append(cells[0])
    return managers, houses


def build_entities(managers, houses):
    """Merge both tabs into one list of entities to track."""
    entities = []      # {key, display, managers[], sources[], notes[]}

    def find(name):
        key = normalise(name)
        for ent in entities:
            if same_entity(ent["key"], key):
                return ent
        return None

    # Houses first - they give the canonical display name.
    for raw in houses:
        key = normalise(raw)
        if not key or key in SKIP:
            continue
        existing = find(raw)
        if existing:
            existing["aliases"].add(raw)
            continue
        entities.append({"key": key, "display": raw, "aliases": {raw},
                         "managers": [], "notes": []})

    # Then managers, attaching each to their house.
    for name, house in managers:
        if not name:
            continue
        if not house:
            # No house given - track the person in their own right.
            ent = find(name)
            if not ent:
                ent = {"key": normalise(name), "display": name,
                       "aliases": {name}, "managers": [], "notes": []}
                entities.append(ent)
            if name not in ent["managers"]:
                ent["managers"].append(name)
            ent["notes"].append("no fund house given in the sheet")
            continue

        ent = find(house)
        if not ent:
            ent = {"key": normalise(house), "display": house,
                   "aliases": {house}, "managers": [], "notes": []}
            entities.append(ent)
        ent["aliases"].add(house)
        if name not in ent["managers"]:
            ent["managers"].append(name)

    for ent in entities:
        ent["display"] = pick_display(ent["aliases"], ent["managers"])

        # Swap in a searchable full name where the sheet used a short form.
        # Matched with same_entity, not an exact key lookup: a merged entity's
        # key is whichever spelling was seen first ("tata chandraprakash"),
        # which won't equal the plain key here.
        canonical = next((v for k, v in SEARCH_NAME.items()
                          if same_entity(ent["key"], k)), None)
        if canonical and canonical.lower() != ent["display"].lower():
            ent["renamed_from"] = ent["display"]
            ent["display"] = canonical
            ent["aliases"].add(canonical)

        note = next((v for k, v in QUESTIONABLE.items()
                     if same_entity(ent["key"], k)), None)
        if note:
            ent["notes"].append(note)
        elif not ent["managers"]:
            ent["notes"].append(
                "no manager named — news matched on the house name alone")
    return entities


def house_query(ent):
    """Search every name variant, not just the tidy one.

    A house is written differently across outlets - "SageOne" vs "SageOne
    Investment Managers" returns 11 recent articles vs 1. Searching only the
    full legal name quietly loses most of the coverage, so all variants are
    OR'd and precision is left to the token filter at collection time.
    """
    variants = {ent["display"]} | set(ent["aliases"])
    # Include the tidied form of each alias too: the raw sheet string can be a
    # phrase no outlet would ever print ("Sageone October News Letter"), while
    # its cleaned form ("SageOne") is the name actually used in coverage.
    variants |= {clean_display(a, ent["managers"]) for a in ent["aliases"]}
    cleaned = sorted({v.strip() for v in variants if v and v.strip()},
                     key=len)
    quoted = " OR ".join(f'"{v}"' for v in cleaned)
    return f"({quoted}) AND {HOUSE_CONTEXT}"


def sources_for(ent):
    """News and YouTube searches for one entity."""
    out = []
    house = ent["display"]
    names = ent["managers"]

    # House-level news across every spelling, anchored to a finance context.
    out.append(("news_search", house_query(ent), f"{house} in the news"))

    # One query per manager - a person's name is far more precise than a
    # house name, and this is what catches interviews and columns.
    for name in names:
        context = (MACRO_CONTEXT if normalise(name) in MACRO_PEOPLE
                   else MANAGER_CONTEXT)
        out.append(("news_person", f'"{name}" AND {context}',
                    f"{name} in the news"))
        out.append(("youtube_search", name, f"{name} on YouTube"))

    # House-level video search, for uploads not tied to a named manager.
    out.append(("youtube_search", house, f"{house} on YouTube"))
    return out


def run(path, dry_run=False):
    db.init()
    managers, houses = read_sheets(path)
    print(f"read {len(managers)} manager row(s), {len(houses)} house row(s)\n")

    entities = build_entities(managers, houses)

    merged = [e for e in entities if len(e["aliases"]) > 1]
    if merged:
        print("merged duplicate names across the two tabs:")
        for e in merged:
            others = sorted(a for a in e["aliases"] if a != e["display"])
            print(f"  {e['display']:26} <- {', '.join(others)}")
        print()

    renamed = [e for e in entities if e.get("renamed_from")]
    if renamed:
        print("renamed for search precision — correct any of these in Admin "
              "if it's the wrong entity:")
        for e in renamed:
            print(f"  {e['renamed_from']:26} -> {e['display']}")
        print()

    flagged = [e for e in entities if e["notes"]]
    if flagged:
        print("needs your attention:")
        for e in flagged:
            print(f"  {e['display']:26} {'; '.join(e['notes'])}")
        print()

    total_sources = 0
    for ent in entities:
        srcs = sources_for(ent)
        total_sources += len(srcs)
        mgr = f"  — {', '.join(ent['managers'])}" if ent["managers"] else ""
        print(f"  {ent['display']}{mgr}")
        if not dry_run:
            fund_id = db.upsert_fund(
                name=ent["display"],
                house=ent["display"],
                managers=", ".join(ent["managers"]),
                category="",
                match_terms=", ".join(sorted(ent["aliases"])))
            for kind, value, label in srcs:
                db.add_source(fund_id, kind, value, label)

    print(f"\n{len(entities)} entities, {total_sources} sources")
    print("Dry run — nothing written." if dry_run else
          "Imported. Add YouTube channel URLs and website pages in Admin.")
    return entities


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    sys.exit(0 if run(args.path, args.dry_run) else 1)
