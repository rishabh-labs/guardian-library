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
import re
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


STATIC_SKIP_BUCKETS = {"inhouse"}


def pages():
    """Every URL worth freezing, as (url, path under the output directory)."""
    out = [("/", "index.html")]
    for key, _label, _desc in config.BUCKETS:
        # Our own videos are streamed from disk by the running portal. A static
        # host has no such files - and at 175-255 MB each they exceed what
        # GitHub Pages accepts anyway - so the shelf is left out of the
        # published copy rather than published with dead play buttons.
        if key in STATIC_SKIP_BUCKETS:
            continue
        out.append((f"/shelf/{key}", os.path.join("shelf", key, "index.html")))
    out.append(("/newsletters", os.path.join("newsletters", "index.html")))
    out.append(("/analysis", os.path.join("analysis", "index.html")))
    return out


ABSOLUTE_URL = re.compile(rb'(href|src)="/(?!/)')


def add_base_path(body, base):
    """Prefix every site-absolute link and asset with the sub-path.

    A project site is served from https://user.github.io/<repo>/, so an href
    of "/shelf/active" resolves at the domain root and 404s. Rewriting the
    rendered HTML is deliberate over generating prefixed URLs: it is one
    substitution with one thing to verify, and it cannot be undone by a shell
    mangling an environment variable on the way in.

    "//cdn.example.com" (protocol-relative) and "https://..." are left alone.
    """
    return ABSOLUTE_URL.sub(rb'\1="' + base.encode() + b'/', body)


def build(outdir):
    db.init()

    # The database is committed to the repository straight after this runs, so
    # this is the last point at which a stored credential can be caught.
    scrubbed = db.scrub_secrets()
    if scrubbed:
        print(f"  redacted credentials from {scrubbed} stored field(s)")


    client = flask_app.app.test_client()

    if os.path.isdir(outdir):
        shutil.rmtree(outdir)
    os.makedirs(outdir, exist_ok=True)

    base = config.STATIC_BASE_PATH
    if base:
        print(f"  building for a site served at {base}/")

    written = 0
    for url, relpath in pages():
        # SCRIPT_NAME is what makes url_for() emit the sub-path prefix, so the
        # links and the stylesheet resolve on a project site rather than
        # pointing at the domain root.
        resp = client.get(url)
        if resp.status_code != 200:
            print(f"  FAIL  {url} returned {resp.status_code}")
            return 1
        dest = os.path.join(outdir, relpath)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        body = resp.data
        if base:
            body = add_base_path(body, base)
        with open(dest, "wb") as fh:
            fh.write(body)
        print(f"  {url:24} -> {relpath}  ({len(resp.data) // 1024} KB)")
        written += 1

    # The stylesheet is the only asset; everything else is a remote thumbnail.
    src = os.path.join(config.BASE_DIR, "static")
    shutil.copytree(src, os.path.join(outdir, "static"))

    # GitHub Pages runs Jekyll by default, which ignores files and folders
    # starting with an underscore. Nothing here does, but a .nojekyll costs
    # nothing and removes a whole class of confusing absence.
    open(os.path.join(outdir, ".nojekyll"), "w").close()

    # The site is deliberately readable by anyone holding the link, but there
    # is no reason for it to be indexed and searchable as well.
    with open(os.path.join(outdir, "robots.txt"), "w", encoding="utf-8") as fh:
        fh.write("User-agent: *\nDisallow: /\n")

    print(f"\n{written} page(s) written to {outdir}")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="site", help="output directory")
    args = ap.parse_args()
    return build(os.path.abspath(args.out))


if __name__ == "__main__":
    sys.exit(main())
