"""Regression test for news relevance matching.

Every case here came from a real miss or a real false positive during the
first watchlist import.

    python test_relevance.py
"""
import sys

from collectors.util import is_relevant, term_tokens

# (entity terms, article text, should_match, note)
CASES = [
    # Abbreviations must match - requiring the full phrase dropped the entire
    # Tata feed on the first run.
    (["Tata Mutual Fund"], "Gold or silver in 2026? Tata MF says keep 70% in gold",
     True, "abbreviated house name"),
    (["SageOne Investment Managers"],
     "SageOne buys 3.2% stake in kidswear manufacturer Karnika Industries",
     True, "long legal name vs short name in headline"),
    (["Fident Asset Management"], "Fident's Dadheech sees value in midcaps",
     True, "short form in headline"),
    (["Mosaic Asset Management"], "Mosaic sees bond value", True,
     "generic suffix stripped"),

    # Sheet annotations must not become required words.
    (["Sageone October News Letter"], "SageOne buys stake in Karnika", True,
     "sheet annotation stripped from the name"),

    # Every distinctive word must appear - this is what kills the noise.
    (["Old Bridge Capital"], "Brooklyn Bridge repairs to cost $400m", False,
     "partial match must not count"),
    (["Buoyant Capital"], "UK biotech venture investment remains buoyant in Q2",
     True, "unavoidable: 'buoyant' is a real word, handled by query precision"),
    (["Ambit Capital"], "Vodafone Idea rises as Ambit sees 45% upside", True,
     "house named in headline"),
    (["Fident Asset Management"],
     "DCB Bank meets investors at 360 ONE conference", False,
     "unrelated article must be rejected"),
    (["Marcellus"], "Devon's Coterra Merger and Marcellus Exit Reshape Devon",
     True, "unavoidable: US shale basin shares the name"),

    # Personal names need both parts.
    (["Neelkanth Mishra"], "Neelkanth Mishra on the rate cycle", True,
     "full personal name"),
    (["Neelkanth Mishra"], "Mishra appointed to committee", False,
     "surname alone is not enough"),

    # Names whose only distinctive word is ordinary English must match as a
    # phrase. "2 Point 2 Capital" reduced to {"point"} and matched every
    # podcast episode that used the word.
    (["2 point 2 capital"], "Why Investors Switch Mutual Funds at this point",
     False, "'point' alone must not match"),
    (["2 point 2 capital"], "Amit Mantri of 2Point2 Capital on small caps",
     True, "written without spaces"),
    (["2 point 2 capital"], "A chat with 2 Point 2 Capital", True,
     "written with spaces"),
    (["Old Bridge Capital"], "The old regime and a bridge too far", False,
     "both words present but not as a phrase"),
    (["Old Bridge Capital"], "Kenneth Andrade of Old Bridge Capital", True,
     "real phrase match"),
]

TOKEN_CASES = [
    ("Tata Mutual Fund", {"tata"}),
    ("SageOne Investment Managers", {"sageone"}),
    ("Sageone October News Letter", {"sageone"}),
    ("Old Bridge Capital", {"old", "bridge"}),
    ("2Point2 Capital", {"2point2"}),
    ("Savi Jain", {"savi", "jain"}),
    # Entirely generic - must fall back rather than match everything.
    ("Asset Management", {"asset", "management"}),
]


def main():
    failures = []

    print("=== token extraction ===")
    for term, expected in TOKEN_CASES:
        got = term_tokens(term)
        ok = got == expected
        if not ok:
            failures.append(f"tokens({term!r}) = {got}, expected {expected}")
        print(f"  {'ok  ' if ok else 'FAIL'} {term:32} -> {sorted(got)}")

    print("\n=== relevance ===")
    for terms, text, expected, note in CASES:
        got = is_relevant(text, terms)
        ok = got == expected
        if not ok:
            failures.append(f"{terms[0]!r} vs {text[:40]!r}: "
                            f"got {got}, expected {expected}")
        print(f"  {'ok  ' if ok else 'FAIL'} [{str(got):5}] {terms[0][:26]:28} {note}")

    if failures:
        print(f"\n{len(failures)} FAILURE(S):")
        for f in failures:
            print("  " + f)
        return 1
    print(f"\nall {len(TOKEN_CASES) + len(CASES)} cases correct")
    return 0


if __name__ == "__main__":
    sys.exit(main())
