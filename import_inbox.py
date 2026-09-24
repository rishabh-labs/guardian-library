"""Newsletters dropped into the repository by anyone on the team.

A static site cannot accept an upload - there is no server to receive it. So
the upload happens on GitHub instead: anyone with access drops a file into
inbox/<Fund House>/ through the website, and the next build puts it on the
Newsletters shelf beside everything the collectors found.

    inbox/
      Marcellus/
        Sept 2026 investor letter.pdf
      PPFAS/
        2026-09 outreach.pdf

The fund house is the folder name. The month comes from the filename when it
says one, otherwise from the file's own date.

    python import_inbox.py        # import whatever is in inbox/

Anything here is PUBLIC: it is committed to a public repository and published
on a site open to anyone with the link. A newsletter a house sent in
confidence does not belong in inbox/ - upload it through the running portal
instead, which keeps it off the published copy.
"""
import argparse
import os
import re
import sys
from datetime import datetime, timezone

import config
import db

INBOX_DIR = os.environ.get("INBOX_DIR", os.path.join(config.BASE_DIR, "inbox"))

# Marked so these can be told apart from both collected items and the private
# uploads that never leave the running portal.
PREFIX = "inbox:"

EXTENSIONS = {".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx",
              ".png", ".jpg", ".jpeg"}

MONTHS = {m.lower(): i for i, m in enumerate(
    ["", "January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"])}
SHORT = {m[:3].lower(): i for m, i in MONTHS.items() if m}


def period_from(name, path):
    """'YYYY-MM' for a file, from its name where it says so.

    Falls back to the file's modification date, which on a GitHub runner is
    the checkout time - close enough for a newsletter uploaded the month it
    arrives, and always correctable by renaming the file.
    """
    stem = os.path.splitext(name)[0]

    m = re.search(r"(20\d{2})[-_ ]?(0[1-9]|1[0-2])\b", stem)
    if m:
        return f"{m.group(1)}-{m.group(2)}"

    m = re.search(r"\b([A-Za-z]{3,9})[' ]*[-_ ]?\s*(20\d{2})\b", stem)
    if m:
        word, year = m.group(1).lower(), m.group(2)
        num = MONTHS.get(word) or SHORT.get(word[:3])
        if num:
            return f"{year}-{num:02d}"

    ts = datetime.fromtimestamp(os.path.getmtime(path), timezone.utc)
    return ts.strftime("%Y-%m")


def title_from(name):
    stem = os.path.splitext(name)[0]
    stem = re.sub(r"[_]+", " ", stem)
    stem = re.sub(r"\s{2,}", " ", stem).strip(" -_")
    return stem or name


def scan():
    """[(house, filename, path)] for everything in the inbox."""
    out = []
    if not os.path.isdir(INBOX_DIR):
        return out
    for house in sorted(os.listdir(INBOX_DIR)):
        house_dir = os.path.join(INBOX_DIR, house)
        if not os.path.isdir(house_dir) or house.startswith("."):
            continue
        for name in sorted(os.listdir(house_dir)):
            path = os.path.join(house_dir, name)
            if not os.path.isfile(path):
                continue
            if os.path.splitext(name)[1].lower() not in EXTENSIONS:
                continue
            out.append((house, name, path))
    return out


def house_fund_id(house):
    """Group an uploaded file with the house's existing entry where there is
    one, rather than creating a second row with the same name."""
    for f in db.list_funds():
        if (f["house"] or "").lower() == house.lower():
            return f["id"]
    return db.upsert_fund(name=house, house=house, managers="",
                          category="Newsletter only", match_terms="",
                          bucket="knowledge")


def run():
    db.init()
    found = scan()
    if not found:
        print(f"nothing in {INBOX_DIR}")
        return 0

    rows = []
    for house, name, path in found:
        rows.append({
            "fund_id": house_fund_id(house),
            "source_id": None,
            "kind": "document" if name.lower().endswith(".pdf") else "newsletter",
            "title": title_from(name),
            # Served from the published site alongside the pages.
            "url": f"/uploads/{house}/{name}",
            "canonical_url": f"{PREFIX}{house}/{name}",
            "thumbnail": "",
            "author": house,
            "summary": "",
            "published_at": datetime.fromtimestamp(
                os.path.getmtime(path), timezone.utc).isoformat(timespec="seconds"),
            "period": period_from(name, path),
        })

    new = db.insert_items(rows)

    conn = db.connect()
    with conn:
        for r in rows:
            conn.execute(
                "UPDATE items SET content_type='research', "
                "classify_why='uploaded by the team' WHERE canonical_url = ?",
                (r["canonical_url"],))
    conn.close()

    print(f"{len(rows)} file(s) in the inbox, {new} newly added\n")
    for r, (house, name, _) in zip(rows, found):
        print(f"  {r['period']}  {house:<22} {r['title'][:46]}")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()
    if args.list:
        for house, name, _ in scan():
            print(f"  {house:<22} {name}")
        return 0
    return run()


if __name__ == "__main__":
    sys.exit(main())
