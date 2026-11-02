"""Re-apply the speaker rule to videos already collected.

classify.run_pending only looks at rows it has never judged, so a change to
the rule leaves everything already on the shelves judged by the old one. This
walks the lot. Rows added by hand are left alone - a human call outranks the
classifier.

    python respeak.py            # show what would change
    python respeak.py --apply    # write it
"""
import sys

import db
import speaker


def main():
    apply = "--apply" in sys.argv
    conn = db.connect()
    rows = conn.execute(
        """SELECT i.id, i.title, i.summary, i.author, i.speaker, i.speaker_why,
                  i.starred, f.managers, f.house, s.kind AS source_kind
           FROM items i
           JOIN funds f ON f.id = i.fund_id
           LEFT JOIN sources s ON s.id = i.source_id
           WHERE i.kind IN ('video','podcast')
             AND i.speaker_why != 'added by hand'
             -- Our own videos were marked by hand when they were imported and
             -- name no fund manager, because they are ours. The classifier
             -- would call every one of them third party.
             AND f.bucket != 'inhouse'""").fetchall()

    changes = []
    for r in rows:
        managers = [m for m in (r["managers"] or "").split(",") if m.strip()]
        who, why = speaker.detect(
            r["title"], r["summary"] or "", r["author"] or "", managers,
            from_own_channel=(r["source_kind"] == "youtube_channel"))
        if who != r["speaker"]:
            changes.append((r["id"], r["speaker"], who, why, r["title"],
                            r["starred"]))
    conn.close()

    for _id, was, now, why, title, starred in changes:
        star = "  [starred, shows anyway]" if starred else ""
        print(f"  {was or '(none)'} -> {now:12} {title[:62]}{star}")
        print(f"      {why}")
    print(f"\n{len(changes)} of {len(rows)} would change")

    if not apply:
        print("nothing written - pass --apply to write it")
        return 0

    conn = db.connect()
    with conn:
        for _id, _was, now, why, _t, _s in changes:
            conn.execute("UPDATE items SET speaker=?, speaker_why=? WHERE id=?",
                         (now, why, _id))
    conn.close()
    print("written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
