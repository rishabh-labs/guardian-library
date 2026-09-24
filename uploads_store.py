"""Newsletters a fund house sends us directly.

Some houses email their letter to investors and never put it on a website, so
the collectors can never find it. This takes an uploaded file, stores it, and
puts it on the Newsletters shelf beside the ones that were scraped - same
house, same month, same page.

The file stays on the machine running the portal. It is not committed and,
unless PUBLISH_UPLOADS is switched on, it is left out of the published copy:
a document sent to us in confidence does not belong on a site that is open to
anyone with the link.
"""
import os
import re
from datetime import datetime, timezone

import config
import db

# Uploads are marked by their canonical_url, the same way in-house videos are.
# One prefix is all it takes to tell them apart from anything collected.
PREFIX = "upload:"


class UploadError(ValueError):
    """The file cannot be accepted, with a reason worth showing the user."""


def safe_name(filename):
    """A filename safe to write to disk, preserving something readable.

    Path separators and traversal are stripped rather than escaped: there is
    no legitimate newsletter whose name needs them, and the file is written
    into a directory the web server also reads from.
    """
    name = os.path.basename(filename or "").replace("\\", "/").split("/")[-1]
    name = re.sub(r"[^A-Za-z0-9 ._()'&,-]", "_", name).strip(" .")
    name = re.sub(r"\s{2,}", " ", name)
    return name[:120] or "newsletter"


def unique_path(name):
    """A path that does not overwrite an existing upload."""
    os.makedirs(config.UPLOAD_DIR, exist_ok=True)
    stem, ext = os.path.splitext(name)
    candidate, n = name, 2
    while os.path.exists(os.path.join(config.UPLOAD_DIR, candidate)):
        candidate = f"{stem} ({n}){ext}"
        n += 1
    return candidate, os.path.join(config.UPLOAD_DIR, candidate)


def title_from(filename):
    stem = os.path.splitext(filename)[0]
    stem = re.sub(r"[_]+", " ", stem)
    stem = re.sub(r"\s{2,}", " ", stem).strip(" -_")
    return stem or filename


def house_fund_id(house):
    """The fund row an uploaded newsletter hangs off.

    Uses an existing fund of that house where there is one, so uploads group
    with everything already collected for it rather than creating a second
    entry with the same name on the shelf.
    """
    house = (house or "").strip()
    if not house:
        raise UploadError("Pick which fund house this is from.")
    for f in db.list_funds():
        if (f["house"] or "").lower() == house.lower():
            return f["id"]
    # A house we do not otherwise track: create it so the upload has a home.
    return db.upsert_fund(name=house, house=house, managers="",
                          category="Newsletter only", match_terms="",
                          bucket="knowledge")


def store(file_storage, house, period, title=""):
    """Save one uploaded file and put it on the Newsletters shelf.

    Returns the new item's id. Raises UploadError with something readable
    when the file cannot be accepted.
    """
    raw_name = safe_name(getattr(file_storage, "filename", ""))
    ext = os.path.splitext(raw_name)[1].lower()
    if ext not in config.UPLOAD_EXTENSIONS:
        raise UploadError(
            f"{raw_name}: {ext or 'that file type'} is not accepted. "
            f"Allowed: {', '.join(sorted(config.UPLOAD_EXTENSIONS))}")

    if not re.fullmatch(r"\d{4}-\d{2}", (period or "").strip()):
        raise UploadError("Pick the month this newsletter is for.")

    stored_name, path = unique_path(raw_name)
    file_storage.save(path)

    size = os.path.getsize(path)
    if size == 0:
        os.remove(path)
        raise UploadError(f"{raw_name} is empty.")
    if size > config.MAX_UPLOAD_MB * 1024 * 1024:
        os.remove(path)
        raise UploadError(
            f"{raw_name} is {size // 1048576} MB, over the "
            f"{config.MAX_UPLOAD_MB} MB limit.")

    fund_id = house_fund_id(house)
    row = {
        "fund_id": fund_id,
        "source_id": None,
        # 'document' rather than 'newsletter' so the shelf shows a PDF tag,
        # matching how scraped factsheets are labelled.
        "kind": "document" if ext == ".pdf" else "newsletter",
        "title": (title or "").strip() or title_from(raw_name),
        "url": "/uploads/" + stored_name,
        "canonical_url": PREFIX + stored_name,
        "thumbnail": "",
        "author": house,
        "summary": "",
        "published_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "period": period,
    }
    db.insert_items([row])

    conn = db.connect()
    with conn:
        conn.execute(
            "UPDATE items SET content_type='research', "
            "classify_why='uploaded by the team' WHERE canonical_url = ?",
            (row["canonical_url"],))
        item_id = conn.execute(
            "SELECT id FROM items WHERE canonical_url = ?",
            (row["canonical_url"],)).fetchone()["id"]
    conn.close()
    return item_id


def is_upload(item):
    return str(item.get("canonical_url", "")).startswith(PREFIX)


def delete(item_id):
    """Remove an uploaded newsletter and its file."""
    item = db.get_item(item_id)
    if not item or not is_upload(item):
        return False
    name = item["canonical_url"][len(PREFIX):]
    path = os.path.join(config.UPLOAD_DIR, name)
    if os.path.exists(path):
        os.remove(path)
    conn = db.connect()
    with conn:
        conn.execute("DELETE FROM items WHERE id = ?", (item_id,))
    conn.close()
    return True


def count():
    conn = db.connect()
    n = conn.execute(
        "SELECT COUNT(*) c FROM items WHERE canonical_url LIKE ?",
        (PREFIX + "%",)).fetchone()["c"]
    conn.close()
    return n
