"""Regression test for the per-channel filters.

Every title here is a real one from the feeds the library polls.

A media channel - ET Now, Mint, moneycontrol - uploads dozens of videos a day
about everyone in the market, so those sources carry an include filter of the
manager names we track. A fund house's own channel carries none: two of the
videos chosen for the library, Ambit's monthly commentary and ValueQuest's
space-sector talk, name no manager at all, so a manager filter there would
throw out the very things we were asked to keep. House channels get exclude
filters instead, for the branded campaign series.

    python test_channel_filter.py
"""
import sys

from collectors.youtube import _channel_filters, entry_allowed

MANAGERS_OLD_BRIDGE = r"Kenneth Andrade|Tarang Agrawal|Old Bridge"
MANAGERS_ABAKKUS = r"Sunil Singhania|Sanjay Doshi|Abakkus"
TATA_CAMPAIGNS = r"Mehfil-E-Fund|Diwali|Holi|Onam|Navratri|Pongal"

# (include, exclude, title, description, should_keep, note)
CASES = [
    # Media channels: our managers in, everything else out.
    (MANAGERS_OLD_BRIDGE, "",
     "Why Kenneth Andrade Isn't Investing In IT Despite Attractive Valuations",
     "", True, "manager named in the title"),
    (MANAGERS_OLD_BRIDGE, "",
     "Market Cycles Explained: History Often Rhymes | Tarang Agrawal", "",
     True, "second manager of the same house"),
    (MANAGERS_OLD_BRIDGE, "",
     "Nifty Outlook: What Brokerages Expect From The November Series", "",
     False, "same channel, nothing to do with us"),
    (MANAGERS_OLD_BRIDGE, "",
     "Where Are The Opportunities Now? | Market Masters",
     "Kenneth Andrade of Old Bridge Capital on where he sees value",
     True, "named in the description, not the title"),
    (MANAGERS_ABAKKUS, "",
     "Midcaps & Smallcaps To Outperform? Abakkus MF's Sanjay Doshi Makes A Case",
     "", True, "manager added after he turned up in a clip"),
    (MANAGERS_ABAKKUS, "",
     "kenneth andrade on where the next leg of growth comes from", "",
     False, "right person, wrong house's source"),
    (MANAGERS_OLD_BRIDGE, "",
     "KENNETH ANDRADE ON MARKETS AT RECORD HIGHS", "", True,
     "shouting in the title still matches"),

    # House channels: no include filter, campaign series excluded.
    ("", TATA_CAMPAIGNS, "Ek Diwali Unki Bhi | Mehfil-E-Fund by Tata Mutual Fund",
     "", False, "festival campaign reel"),
    ("", TATA_CAMPAIGNS, "Tata Small Cap Fund: What Should Investors Do Now?",
     "", True, "the house talking about its own fund"),
    ("", r"Portfolio Pulse",
     "Ambit Asset Management: The Storm is similar. The Vessel is different.",
     "", True, "names no manager, and must still be kept"),
    ("", r"Portfolio Pulse", "Portfolio Pulse - September 2026", "", False,
     "the series we were asked to drop"),
    ("", r"Think Wealth|Joy of Growing Up",
     "The Joy of Growing Up | Every Journey Has a Destination | Think Wealth",
     "", False, "brand film, not research"),
    ("", "", "Decoding India's Space Sector, Investment Opportunities & more",
     "", True, "unfiltered house channel keeps everything"),

    # Both filters at once: include wins the first pass, exclude the second.
    (MANAGERS_OLD_BRIDGE, r"Shorts",
     "Kenneth Andrade on valuations #Shorts", "", False,
     "matches the manager but is excluded anyway"),
]

# A filter typed into the admin form can be invalid. It must not stop the
# source collecting - better a noisy shelf than a silently dead channel.
BAD_REGEX_CASES = [
    ("Kenneth Andrade|", ""),
    ("(unclosed", ""),
    ("", "[z-a]"),
]


def main():
    failures = []

    print("=== channel filters ===")
    for include, exclude, title, desc, expected, note in CASES:
        inc, exc = _channel_filters({"include_re": include,
                                     "exclude_re": exclude, "id": 0})
        got = entry_allowed({"title": title, "media_description": desc},
                            inc, exc)
        ok = got == expected
        if not ok:
            failures.append(f"{title[:50]!r}: got {got}, expected {expected}")
        verdict = "keep" if got else "drop"
        print(f"  {'ok  ' if ok else 'FAIL'} [{verdict}] {note}")

    print("\n=== a bad filter must not kill the source ===")
    for include, exclude in BAD_REGEX_CASES:
        inc, exc = _channel_filters({"include_re": include,
                                     "exclude_re": exclude, "id": 0})
        try:
            got = entry_allowed({"title": "Kenneth Andrade on markets",
                                 "media_description": ""}, inc, exc)
        except Exception as exc_raised:            # pragma: no cover
            failures.append(f"{include or exclude!r} raised {exc_raised}")
            print(f"  FAIL {include or exclude!r} raised")
            continue
        ok = got is True
        if not ok:
            failures.append(f"{include or exclude!r}: dropped the entry")
        print(f"  {'ok  ' if ok else 'FAIL'} {(include or exclude)!r:16} "
              f"ignored, entry kept")

    if failures:
        print(f"\n{len(failures)} FAILURE(S):")
        for f in failures:
            print("  " + f)
        return 1
    print(f"\nall {len(CASES) + len(BAD_REGEX_CASES)} cases correct")
    return 0


if __name__ == "__main__":
    sys.exit(main())
