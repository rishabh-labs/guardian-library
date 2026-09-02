"""Put our own videos on the shelf.

Drop a video file into the media folder and run this. The file itself never
moves and is never uploaded: the portal streams it from disk to whoever is
signed in, which is what keeps client-education material private.

    python import_media.py            # scan and add anything new
    python import_media.py --list     # show what is already on the shelf

Titles come from the filename, so name the file the way you want it read:
"Commercial Vehicle Sectoral Overview.mp4" becomes exactly that.
"""
import argparse
import os
import re
import struct
import sys

import config
import db

VIDEO_EXTENSIONS = {".mp4", ".m4v", ".mov", ".webm", ".mkv"}

# One fund row carries all of it, so the shelf groups under the house name.
HOUSE = "Guardian Capital"


def mp4_duration(path):
    """Seconds, read from the mp4 header. None when it cannot be determined.

    Walks the atom tree to the 'mvhd' header rather than shelling out to
    ffmpeg, which is not installed and would be a heavy dependency for one
    number. Only mp4/m4v/mov are laid out this way; other containers return
    None and the shelf simply shows no runtime.
    """
    try:
        with open(path, "rb") as fh:
            return _find_mvhd(fh, 0, os.path.getsize(path))
    except (OSError, struct.error, ValueError):
        return None


def _find_mvhd(fh, start, end, depth=0):
    """Depth-first walk of the atom tree looking for the movie header."""
    if depth > 4:
        return None
    pos = start
    while pos < end - 8:
        fh.seek(pos)
        header = fh.read(8)
        if len(header) < 8:
            return None
        size, kind = struct.unpack(">I4s", header)
        body = pos + 8
        if size == 1:                      # 64-bit extended size
            size = struct.unpack(">Q", fh.read(8))[0]
            body = pos + 16
        if size < 8:
            return None

        if kind == b"mvhd":
            fh.seek(body)
            version = fh.read(1)[0]
            fh.read(3)                     # flags
            if version == 1:
                fh.read(16)                # created, modified (64-bit)
                scale, units = struct.unpack(">IQ", fh.read(12))
            else:
                fh.read(8)                 # created, modified (32-bit)
                scale, units = struct.unpack(">II", fh.read(8))
            return int(units / scale) if scale else None

        if kind in (b"moov", b"trak", b"mdia"):
            found = _find_mvhd(fh, body, pos + size, depth + 1)
            if found:
                return found

        pos += size
    return None


def title_from(filename):
    """A readable title from a filename, without mangling real punctuation."""
    stem = os.path.splitext(filename)[0]
    stem = re.sub(r"[_]+", " ", stem)
    stem = re.sub(r"\s{2,}", " ", stem).strip()
    return stem or filename


def scan():
    """Everything in the media folder, newest first."""
    folder = config.MEDIA_DIR
    if not os.path.isdir(folder):
        return []
    out = []
    for name in os.listdir(folder):
        path = os.path.join(folder, name)
        if not os.path.isfile(path):
            continue
        if os.path.splitext(name)[1].lower() not in VIDEO_EXTENSIONS:
            continue
        out.append({
            "filename": name,
            "path": path,
            "size": os.path.getsize(path),
            "mtime": os.path.getmtime(path),
        })
    return sorted(out, key=lambda f: f["mtime"], reverse=True)


def house_fund_id():
    """The fund row our own videos hang off, created on first use."""
    for f in db.list_funds():
        if f["name"] == HOUSE:
            return f["id"]
    return db.upsert_fund(name=HOUSE, house=HOUSE, managers="",
                          category="In-house", match_terms="",
                          bucket="inhouse")


def run():
    db.init()
    files = scan()
    if not files:
        print(f"no video files in {config.MEDIA_DIR}")
        print("drop .mp4 files there and run this again")
        return 0

    fund_id = house_fund_id()
    rows = []
    from datetime import datetime, timezone
    for f in files:
        secs = mp4_duration(f["path"])
        published = datetime.fromtimestamp(
            f["mtime"], timezone.utc).isoformat(timespec="seconds")
        rows.append({
            "fund_id": fund_id,
            "source_id": None,
            "kind": "video",
            "title": title_from(f["filename"]),
            # Served by the portal, never a public URL.
            "url": "/media/" + f["filename"],
            "canonical_url": "local:" + f["filename"],
            "thumbnail": "",
            "author": HOUSE,
            "summary": "",
            "published_at": published,
        })

    new = db.insert_items(rows)

    # Our own videos are curated, not scraped: they bypass the promo, language
    # and speaker filters entirely rather than being judged by them.
    conn = db.connect()
    with conn:
        for f, r in zip(files, rows):
            secs = mp4_duration(f["path"])
            conn.execute(
                """UPDATE items
                   SET content_type='research', classify_why='our own video',
                       language='en', language_why='in-house',
                       speaker='manager', speaker_why='in-house',
                       duration_secs=COALESCE(?, duration_secs)
                   WHERE canonical_url = ?""",
                (secs, r["canonical_url"]))
    conn.close()

    print(f"{len(files)} file(s) in {config.MEDIA_DIR}, {new} newly added\n")
    for f in files:
        secs = mp4_duration(f["path"])
        mins = f"{secs // 60}m" if secs else "?"
        print(f"  {f['size'] / 1048576:7.0f} MB  {mins:>5}  {title_from(f['filename'])}")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true",
                    help="show what is on the shelf already")
    args = ap.parse_args()
    db.init()
    if args.list:
        items = db.query_items(bucket="inhouse", limit=200)
        if not items:
            print("nothing on the in-house shelf yet")
        for i in items:
            secs = i.get("duration_secs") or 0
            print(f"  {secs // 60:>4}m  {i['title']}")
        return 0
    return run()


if __name__ == "__main__":
    sys.exit(main())
