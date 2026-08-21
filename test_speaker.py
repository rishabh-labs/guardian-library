"""Regression test: is the manager in the video, or is it a review of it?

    python test_speaker.py
"""
import sys

from speaker import detect

MANAGERS = ["Chandraprakash Padiyar", "Saurabh Mukherjea", "Jigar Mistry",
            "Kenneth Andrade", "Rajeev Thakkar", "Nilesh Shah"]

# (title, from_own_channel, expected, note)
CASES = [
    # --- the manager speaking: keep ---
    ("Saurabh Mukherjea on why we exited HDFC Bank", False, "manager",
     "manager named in title"),
    ("Market witnessing normal consolidation, says Chandraprakash Padiyar",
     False, "manager", "named, attribution phrasing"),
    ("In Conversation with Kenneth Andrade | Old Bridge", False, "manager",
     "interview, named"),
    ("Buoyant Capital's Jigar Mistry on risks and opportunities", False,
     "manager", "possessive form"),
    ("Monthly Market Outlook | August 2026", True, "manager",
     "house's own channel needs no name"),
    ("Nifty outlook and portfolio positioning", True, "manager",
     "own channel, generic title"),

    # --- somebody else reviewing the fund: drop ---
    ("Tata Small Cap Fund Review 2026 | Should You Invest?", False,
     "third_party", "classic review"),
    ("Top 10 Small Cap Funds for 2026", False, "third_party", "listicle"),
    ("Best PMS in India 2026 - Full Comparison", False, "third_party",
     "comparison"),
    ("PPFAS Flexicap vs Parag Parikh: which fund wins?", False, "third_party",
     "versus"),
    ("Old Bridge Focused Fund - honest review", False, "third_party",
     "review of a fund we hold"),
    ("My portfolio: 5 funds I hold in 2026", False, "third_party",
     "someone else's portfolio"),
    ("Is Buoyant Capital worth investing in?", False, "third_party",
     "worth investing"),
    ("Tata Small Cap performance analysis", False, "third_party",
     "performance analysis, nobody named"),
    ("Ambit Small Cap Fund explained", False, "third_party",
     "explainer by an outsider, no manager"),
]


def main():
    failures = []
    for title, own, expected, note in CASES:
        got, why = detect(title, managers=MANAGERS, from_own_channel=own)
        ok = got == expected
        if not ok:
            failures.append(f"{title[:50]!r}: got {got}, expected {expected} ({why})")
        flag = "ok  " if ok else "FAIL"
        print(f"  {flag} [{got:11}] {title[:52]:54} {note}")

    if failures:
        print(f"\n{len(failures)} FAILURE(S):")
        for f in failures:
            print("  " + f)
        return 1
    print(f"\nall {len(CASES)} cases correct")
    return 0


if __name__ == "__main__":
    sys.exit(main())
