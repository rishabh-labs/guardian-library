"""The database is committed to the repository and rendered in Admin, so
anything stored in it is effectively published. An HTTP error carries the full
request URL, and for the YouTube API that URL contains the key."""
import db

CASES = [
    ("HTTPError: 429 for https://www.googleapis.com/youtube/v3/search"
     "?key=AIzaSyREALLOOKINGKEY123456&part=snippet", "AIzaSyREALLOOKINGKEY123456"),
    ("token=abc123secretvalue&x=1", "abc123secretvalue"),
    ("https://x.test/a?api_key=sekrit12345&b=2", "sekrit12345"),
    ("https://x.test/a?access_token=zzz99999&b=2", "zzz99999"),
    ("fetch failed: password=hunter2hunter2", "hunter2hunter2"),
    ("https://x.test/a?API-KEY=MixedCase123456&b=2", "MixedCase123456"),
]

KEEP = [
    ("HTTPError: 403 Client Error: Forbidden for url: "
     "https://www.hdfcfund.com/learn/market-review", "hdfcfund.com"),
    ("ok - 12 fetched, 3 new", "12 fetched"),
]


def main():
    bad = 0
    for text, secret in CASES:
        out = db.redact(text)
        if secret in out:
            bad += 1
            print(f"  FAIL  secret survived: {out[:80]}")
        elif "<redacted>" not in out:
            bad += 1
            print(f"  FAIL  nothing redacted in: {out[:80]}")

    for text, must_keep in KEEP:
        out = db.redact(text)
        if must_keep not in out:
            bad += 1
            print(f"  FAIL  redacted too much: {text[:50]} -> {out[:60]}")

    # Configured secrets are stripped even when they appear bare.
    db.config.YOUTUBE_API_KEY = "AIzaSyCONFIGUREDKEY9876"
    if "AIzaSyCONFIGUREDKEY9876" in db.redact("leaked AIzaSyCONFIGUREDKEY9876 here"):
        bad += 1
        print("  FAIL  configured key not stripped")

    # A short value must not be treated as a secret and blank out real text.
    db.config.ADMIN_PASSWORD = "abc"
    if "<redacted>" in db.redact("abc happens to appear in this sentence"):
        bad += 1
        print("  FAIL  short config value over-matched")

    total = len(CASES) + len(KEEP) + 2
    if bad:
        print(f"{bad} of {total} cases failed")
        return 1
    print(f"all {total} cases correct")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
