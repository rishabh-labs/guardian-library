"""Regression test: is the manager in the video, or is it a review of it?

    python test_speaker.py
"""
import sys

from speaker import detect

MANAGERS = ["Chandraprakash Padiyar", "Saurabh Mukherjea", "Jigar Mistry",
            "Kenneth Andrade", "Rajeev Thakkar", "Nilesh Shah",
            "Sunil Singhania", "Samir Arora", "Shibani Kurian",
            "Ramdeo Agarwal", "Ajay Khandelwal", "Atul Mehra"]

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

    # --- a segment about a stock he holds: drop, even though he is named ---
    # All three were on the Abakkus shelf and are what prompted the rule.
    ("Ace Investors Madhusudan Kela & Sunil Singhania Back This Stock, "
     "Should You Hike Exposure?", False, "third_party",
     "tip sheet, manager named as the backer"),
    ("Can You Expect An Up Move In This Sunil Singhania's Abakkus-Backed "
     "Stock?", False, "third_party", "technical call on a stock he holds"),
    ("Sunil Singhania (Abakkus) Ne Sejal Glass Mein Stake Liya! Q4 Huge "
     "Profit", False, "third_party", "Hindi report of a stake purchase"),
    ("Marcellus Buys 2% Stake In Divi's Labs", False, "third_party",
     "trade report, house named not manager"),
    ("Nilesh Shah's Multibagger Pick For 2027", False, "third_party",
     "stock tip wearing his name"),
    ("Sunil Singhania ने खरीदे ये Small Cap Stocks! Abakkus Fund की बड़ी खरीदारी",
     False, "third_party", "the same trade report in Hindi"),
    ("ये 4 Small Cap Stocks Sunil Singhania ने खरीदे #investing", False,
     "third_party", "Hindi, manager as the subject of the trade"),

    # ...but ordinary market commentary that merely mentions stocks is his.
    ("Samir Arora's Big Market Bet: Why NBFCs Over Banks & New-Age Stocks",
     False, "manager", "his call on sectors, not a single-stock tip"),
    ("Stock Picks To Watch: Shibani Kurian Reveals Kotak AMC's Market Bets",
     False, "manager", "she is the one revealing them"),
    ("Why Owning 50 Indian Stocks Is NOT Diversification | Saurabh Mukherjea",
     False, "manager", "stocks in the title, still his argument"),
    ("Kenneth Andrade on why he exited the stock last quarter", False,
     "manager", "he explains his own trade"),
    # "multibagger" is a hashtag half of finance YouTube attaches to
    # everything, the managers' own clips included. Bare, it means nothing.
    ("Ramdeo Agarwal:- How to Find blue chip Stocks #financialeducation "
     "#multibagger", False, "manager", "a hashtag is not a stock tip"),
    ("India's Next Multibagger Sectors? Abakkus Experts Weigh In", False,
     "third_party", "sectors, not a pick - but nobody tracked is named"),
]

# Business television titles a clip with the view and names the guest only in
# the description. These are real pairs from CNBC-TV18 and the fund houses.
# (title, description, expected, note)
DESC_CASES = [
    ("Underweight On Metals And Commodity Businesses: Motilal Oswal AMC",
     "AlphaManagers | Atul Mehra, Motilal Oswal AMC To @CNBCTV18News * "
     "Underweight on metals and commodity businesses",
     "manager", "named underneath, attributed to the channel"),
    ("Indices Open Higher | Market Seems Fairly Valued",
     "MarketOutlook | D-Street: Positive Start To Trade OldBridge Asset "
     "Management's Kenneth Andrade to CNBC-TV18",
     "manager", "possessive form of the same convention"),
    ("Earnings Upgrades Seen After Six Quarters: Motilal Oswal MF",
     "MarketOutlook | Ajay Khandelwal, Motilal Oswal MF tells @CNBCTV18News",
     "manager", "tells the channel"),
    ("Why Parag Parikh Flexi Cap Is Underperforming?",
     "Fund CIO Rajeev Thakkar explains the reasons behind it",
     "manager", "the house's own 'X explains' format"),
    ("Where should you put your money in 2027?",
     "Our analyst breaks down what Kenneth Andrade has been buying lately",
     "third_party", "named, but it is somebody else's video about him"),
    ("Top 5 PMS Schemes Reviewed",
     "We rate the schemes run by Saurabh Mukherjea and others",
     "third_party", "review phrasing wins over a name in the description"),
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

    print("\n=== named only in the description ===")
    for title, desc, expected, note in DESC_CASES:
        got, why = detect(title, desc, managers=MANAGERS)
        ok = got == expected
        if not ok:
            failures.append(f"{title[:44]!r}: got {got}, expected {expected} ({why})")
        print(f"  {'ok  ' if ok else 'FAIL'} [{got:11}] {title[:46]:48} {note}")

    if failures:
        print(f"\n{len(failures)} FAILURE(S):")
        for f in failures:
            print("  " + f)
        return 1
    print(f"\nall {len(CASES) + len(DESC_CASES)} cases correct")
    return 0


if __name__ == "__main__":
    sys.exit(main())
