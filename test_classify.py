"""Regression test for the promo/research classifier.

The corpus is real: every title below was actually collected from Motilal
Oswal's channel during development, plus hand-added cases for patterns we
expect from other fund houses.

Rules only - no API key, no duration. That is the worst case, so anything
passing here passes with the extra signals too.

    python test_classify.py
"""
import sys

from classify import classify_video

MANAGERS = ["Prateek Agrawal", "Pratik Oswal"]

# (title, expected) - real titles from the live collection run
REAL = [
    ("Monthly Market Outlook by Prateek Agrawal | August 2026 | #MotilalOswalAMC", "research"),
    ("The Truth About Momentum Investing in India | Part 2 | #Unscripted | Motilal Oswal", "research"),
    ("3 Things to Avoid When Setting Up a Family Office | Motilal Oswal AMC", "research"),
    ("How Momentum Keeps the Portfolio Aligned with Market Trends", "research"),
    ("Motilal Oswal Large & Midcap Fund vs Benchmark | Historical Returns Explained", "research"),

    ("NFO Closing Today | Motilal Oswal BSE Midcap 150 Momentum 30 Index Fund", "promo"),
    ("1 Day Left | NFO Closes Tomorrow | Motilal Oswal BSE Midcap 150", "promo"),
    ("2 Days Left | Motilal Oswal BSE Midcap 150 Momentum 30 Index Fund NFO", "promo"),
    ("Did you know?", "promo"),
    ("Mr. Pratik Oswal Reflects on the Biggest Highlight of the Passive Funds Conclave", "promo"),
    ("Mr. Pratik Oswal Shares His Advice for Young Mutual Fund Partners", "promo"),
    ("Mr. Pratik Oswal's Key Takeaway from the Passive Funds Conclave 2026", "promo"),
    ("What is the market telling us right now?", "promo"),
]

# Patterns we expect from other houses but haven't collected yet.
SYNTHETIC = [
    ("Saurabh Mukherjea on why we exited HDFC Bank | Marcellus", "research"),
    ("In Conversation with Saurabh Mukherjea | Consistent Compounders", "research"),
    ("Q2 FY26 Portfolio Review | Marcellus Kings of Capital", "research"),
    ("Annual Letter to Investors 2026", "research"),
    ("Our view on the RBI policy | Fund Manager commentary", "research"),
    ("How to evaluate a bank's loan book | Explained", "research"),

    ("Happy Diwali from all of us at Marcellus", "promo"),
    ("Congratulations to our team on winning Best PMS 2026", "promo"),
    ("Invest Now | Last Day to Subscribe", "promo"),
    ("Celebrating 10 years of excellence | Anniversary special", "promo"),
    ("Register Now for our investor meet", "promo"),
    ("#Shorts | Fun fact about compounding", "promo"),

    # Retail / tutorial / stock-tip noise seen once real channels were added.
    ("Axis Bank Lifetime free credit card, Axis Bank Neo benefits", "promo"),
    ("Axis Bank Zero Balance Account 2026 | Full Details", "promo"),
    ("Yono sbi me sip stop kaise kare || how to stop sip", "promo"),
    ("SBI FD scheme 2026 | how to open account", "promo"),
    ("MOTILAL OSWAL SHARE TARGET ANALYSIS | multibagger", "promo"),
    ("Weekly Technical Picks - Aarti Industries, LG Electronics", "promo"),
    ("axis bank share news today || axis bank share price", "promo"),

    # Must survive the new rules - these are the real thing.
    ("Raamdeo Agrawal on India's Equity Outlook | 15% Returns", "research"),
    ("Gautam Duggad on Indian Markets, Earnings & Key Sectors", "research"),
    ("Earnings Upgrades Seen After Six Quarters: Motilal Oswal", "research"),
    ("22nd MOAGIC | Capital Markets Have Strong Growth Potential", "research"),
]


def run(cases, label):
    failures = []
    for title, expected in cases:
        got, why = classify_video(title, managers=MANAGERS, allow_model=False)
        mark = "ok  " if got == expected else "FAIL"
        if got != expected:
            failures.append((title, expected, got, why))
        print(f"  {mark} [{got:8}] {title[:64]}")
    print(f"\n{label}: {len(cases) - len(failures)}/{len(cases)} correct")
    return failures


if __name__ == "__main__":
    print("=== real titles from the live run ===")
    bad = run(REAL, "real")
    print("\n=== synthetic patterns from other houses ===")
    bad += run(SYNTHETIC, "synthetic")

    if bad:
        print(f"\n{len(bad)} FAILURE(S):")
        for title, expected, got, why in bad:
            print(f"  {title!r}\n    expected {expected}, got {got} ({why})")
        sys.exit(1)

    print(f"\nall {len(REAL) + len(SYNTHETIC)} cases correct")
