"""Render the portal to flat HTML files for a static host.

The live app is Flask, but a static copy needs no server at all - which is what
makes free hosting possible. Pages are written as directories with an
index.html, so the URLs are identical to the live app's: /shelf/inactive
stays /shelf/inactive rather than becoming /shelf/inactive.html.

Anything that writes back to the database - insights, starring, mark-as-read,
Summarise, the filter form - is left out of the static build by
config.STATIC_EXPORT rather than shipped as a button that does nothing.

    python export_static.py            # writes ./site
    python export_static.py --out dir  # somewhere else
"""
import argparse
import os
import shutil
import sys

# Must be set before app.py is imported, because the templates read it at
# render time and the scheduler must not start inside a build job.
os.environ["STATIC_EXPORT"] = "1"
os.environ["ENABLE_SCHEDULER"] = "0"
os.environ.setdefault("VIEWER_PASSWORD", "")   # no login on a static copy

import config  # noqa: E402
config.STATIC_EXPORT = True
config.ENABLE_SCHEDULER = False
config.VIEWER_PASSWORD = ""

import app as flask_app  # noqa: E402
import db  # noqa: E402


def pages():
    """Every URL worth freezing, as (url, path under the output directory)."""
    out = [("/", "index.html")]
    for key, _label, _desc in config.BUCKETS:
        out.append((f"/shelf/{key}", os.path.join("shelf", key, "index.html")))
    out.append(("/newsletters", os.path.join("newsletters", "index.html")))
    out.append(("/analysis", os.path.join("analysis", "index.html")))
    return out


def build(outdir):
    db.init()
    client = flask_app.app.test_client()

    if os.path.isdir(outdir):
        shutil.rmtree(outdir)
    os.makedirs(outdir, exist_ok=True)

    written = 0
    for url, relpath in pages():
        resp = client.get(url)
        if resp.status_code != 200:
            print(f"  FAIL  {url} returned {resp.status_code}")
            return 1
        dest = os.path.join(outdir, relpath)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as fh:
            fh.write(resp.data)
        print(f"  {url:24} -> {relpath}  ({len(resp.data) // 1024} KB)")
        written += 1

    # The stylesheet is the only asset; everything else is a remote thumbnail.
    src = os.path.join(config.BASE_DIR, "static")
    shutil.copytree(src, os.path.join(outdir, "static"))

    # GitHub Pages runs Jekyll by default, which ignores files and folders
    # starting with an underscore. Nothing here does, but a .nojekyll costs
    # nothing and removes a whole class of confusing absence.
    open(os.path.join(outdir, ".nojekyll"), "w").close()

    print(f"\n{written} page(s) written to {outdir}")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="site", help="output directory")
    args = ap.parse_args()
    return build(os.path.abspath(args.out))


if __name__ == "__main__":
    sys.exit(main())
