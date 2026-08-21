"""Where each fund house publishes its newsletters.

Keyed by the fund name as stored in the database. Each entry is
(kind, url, label), optionally followed by an include regex and an exclude
regex matched against the document filename — use those when a house publishes
several document families side by side and only one of them is wanted.

kind is:

  newsletter_page    - a listing page to scrape
  newsletter_pattern - a URL template; {month} {mon} {mm} {yyyy} {yy}

Add or correct entries here, or add sources by hand in Admin. A house with no
entry simply collects nothing until one is added.

    python newsletter_sources.py            # apply to the database
    python newsletter_sources.py --check    # fetch each page and report
"""
import argparse
import sys

SOURCES = {
    # Keys are fund *houses* as derived by import_lists.house_of(), not
    # strategy names: Tata publishes one factsheet whether we hold one of its
    # funds or three.
    "Marcellus": [
        ("newsletter_page", "https://marcellus.in/newsletter-archives/",
         "Marcellus newsletters"),
    ],
    "PPFAS": [
        ("newsletter_pattern",
         "https://amc.ppfas.com/newsletter/{yyyy}/outreach-{month}-{yyyy}/",
         "PPFAS Outreach"),
    ],
    "Buoyant": [
        # https://www.buoyantcap.com/insights/factsheets/ renders with
        # JavaScript, so it cannot be scraped directly - this reads the same
        # PDFs from the WordPress media library behind that page. They publish
        # the monthly factsheet once plain and once per distributor; keep one.
        ("wp_media", "https://www.buoyantcap.com", "Buoyant PMS factsheet",
         r"Buoyant-PMS-Flyer(-Axis)?-\d{4}-\d{2}",
         r"Offshore|Disclaimer", True),
    ],
    "Ambit": [
        ("wp_media", "https://www.ambit.co", "Ambit newsletters"),
    ],
    "Fident": [
        ("wp_media", "https://fident.in", "Fident factsheets"),
        ("newsletter_page", "https://fident.in/insights/", "Fident insights"),
    ],
    "VQ": [
        ("newsletter_page", "https://www.valuequest.in/blog/",
         "ValueQuest insights"),
    ],
    "Motilal": [
        ("newsletter_page",
         "https://www.motilaloswalmf.com/motilal-oswal-edge/articles",
         "Monthly market outlook"),
    ],
    "Old Bridge": [
        ("newsletter_page", "https://www.oldbridgecapital.com/newsletter",
         "Old Bridge newsletter"),
    ],
    # From the Knowledge Centre sheet.
    "HDFC": [
        ("newsletter_page",
         "https://www.hdfcfund.com/learn/macros-markets-more/market-review",
         "HDFC macros, markets & more"),
    ],
    "SBI": [
        ("newsletter_page", "https://www.sbimf.com/cio-desk", "SBI CIO desk"),
    ],
    "LIC": [
        ("newsletter_page", "https://www.licmf.com/insights/market-update",
         "LIC market update"),
    ],
    "Abakkus": [
        ("newsletter_page", "https://insights.abakkusinvest.com/",
         "Abakkus insights"),
    ],
}


def check():
    """Fetch every page and report what the collector would extract.

    Each page is read twice - once with the real 6-month window, once with no
    window at all. That separates 'the page cannot be read' from 'the page is
    fine, this house just hasn't published recently', which need different
    fixes.
    """
    sys.path.insert(0, ".")
    from collectors import newsletters

    COLLECTORS = {
        "newsletter_page": newsletters.collect_newsletter_page,
        "newsletter_pattern": newsletters.collect_newsletter_pattern,
        "wp_media": newsletters.collect_wp_media,
    }

    ok = broken = stale = empty = 0
    for fund, entries in SOURCES.items():
        for entry in entries:
            kind, url, label = entry[0], entry[1], entry[2]
            fn = COLLECTORS.get(kind, newsletters.collect_newsletter_page)
            base = {"fund_id": 0, "id": 0, "value": url, "label": label,
                    "last_checked": None,
                    "include_re": entry[3] if len(entry) > 3 else "",
                    "exclude_re": entry[4] if len(entry) > 4 else "",
                    "one_per_period": entry[5] if len(entry) > 5 else 0}
            try:
                recent = fn(dict(base))
                everything = fn(dict(base, _window_days=3650))
            except Exception as exc:
                broken += 1
                print(f"  FAIL  {fund[:24]:26} {type(exc).__name__}: "
                      f"{str(exc)[:42]}")
                continue

            if recent:
                ok += 1
                periods = sorted({i["period"] for i in recent}, reverse=True)
                print(f"  OK    {fund[:24]:26} {len(recent):>2} in 6M  "
                      f"{', '.join(periods[:6])}")
                for i in recent[:2]:
                    print(f"          {i['period']}  {i['title'][:58]}")
            elif everything:
                stale += 1
                periods = sorted({i["period"] for i in everything}, reverse=True)
                print(f"  STALE {fund[:24]:26} readable, but newest is "
                      f"{periods[0]} ({len(everything)} total)")
            else:
                empty += 1
                print(f"  EMPTY {fund[:24]:26} nothing parseable  {url[:44]}")

    print(f"\n{ok} with recent newsletters, {stale} readable but stale, "
          f"{empty} unreadable, {broken} failed")


def apply():
    sys.path.insert(0, ".")
    import db
    db.init()
    # One representative fund per house carries that house's newsletter
    # sources; the shelf groups by house, so duplicates would look like noise.
    funds = {}
    for f in db.list_funds():
        funds.setdefault(f["house"] or f["name"], f["id"])
    added = missing = 0
    for fund, entries in SOURCES.items():
        if fund not in funds:
            print(f"  no fund house in the database for: {fund}")
            missing += 1
            continue
        for entry in entries:
            kind, url, label = entry[0], entry[1], entry[2]
            include_re = entry[3] if len(entry) > 3 else ""
            exclude_re = entry[4] if len(entry) > 4 else ""
            one_per = entry[5] if len(entry) > 5 else 0
            db.add_source(funds[fund], kind, url, label, include_re,
                          exclude_re, one_per)
            added += 1
            if include_re or exclude_re:
                print(f"  {fund[:26]:28} filter +{include_re!r} "
                      f"-{exclude_re!r}"
                      f"{' one/month' if one_per else ''}")
    print(f"added/kept {added} newsletter source(s); {missing} unknown fund(s)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    check() if args.check else apply()
