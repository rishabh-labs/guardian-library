"""Run one collection pass from the command line.

Importing app.py starts the scheduler, which fires its own pass immediately —
so calling app.refresh_cycle() by hand collected everything twice and burned
double the YouTube quota. This runs the same work with no web app attached.

    python refresh.py            # collect, then classify what came in
    python refresh.py --quiet    # only the summary line
"""
import argparse
import logging

import classify
import collectors
import config
import db


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quiet", action="store_true",
                    help="hide per-source warnings")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.ERROR if args.quiet else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    db.init()
    result = collectors.run_all()
    result["classified"] = classify.run_pending()
    if config.AUTO_ANALYSE:
        import analyse
        result["analysis"] = analyse.run_pending()

    print(f"new {result.get('new', 0)}  ok {result.get('ok', 0)}  "
          f"failed {result.get('failed', 0)}  "
          f"classified {result.get('classified', 0)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
