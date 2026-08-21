"""Regression test for video language detection.

Cases come from titles actually collected into the library, plus the scripts
we expect from Indian fund channels.

    python test_language.py
"""
import sys

from language import detect, looks_hinglish

# (title, expected language, note)
CASES = [
    # --- English: must survive ---
    ("Raamdeo Agrawal on India's Equity Outlook | 15% Returns", "en",
     "plain English"),
    ("Are AI Stocks Heading for a Reality Check? (Chips and Cloud)", "en",
     "English with jargon"),
    ("Decoding India's Space Sector, Investment Opportunities & more", "en",
     "'India' must not trigger a Hindi guess"),
    ("Monthly Market Outlook August 2026 by Prateek Agrawal", "en",
     "Indian names in an English title"),
    ("Defending the Yen, Preserving the Dollar", "en", "English"),
    ("22nd MOAGIC | Capital Markets Have Strong Growth Potential", "en",
     "acronyms"),

    # --- Devanagari / Hindi ---
    ("निफ़्टी पर आएगा तेज़ उछाल, आयी नयी भविष्यवाणी?", "hi",
     "Devanagari title"),
    ("PPFAS में क्या बदल रहा है? Rajeev Thakkar का August 2026", "hi",
     "mixed Devanagari and Latin"),
    ("Q1 Earnings में बड़ा Positive Surprise! किन Sectors में", "hi",
     "mostly Latin, Devanagari clauses"),

    # --- Romanised Hindi (Latin script) ---
    ("Roz Market Nahi Dekh Sakte? This Fund Is for You.", "hi",
     "romanised Hindi"),
    ("Yono sbi me sip stop kaise kare || how to stop sip", "hi",
     "romanised Hindi"),
    ("Don't Think 'Kaash', Think Wealth Creation", "en",
     "one marker only - must NOT trip"),

    # --- Other Indian scripts ---
    ("పెట్టుబడి మార్కెట్ విశ్లేషణ", "te", "Telugu"),
    ("முதலீட்டு சந்தை பகுப்பாய்வு", "ta", "Tamil"),
    ("বিনিয়োগ বাজার বিশ্লেষণ", "bn", "Bengali"),
]

# Tags fill in where the text is silent, but visible script wins over a tag.
TAG_CASES = [
    ("Market Outlook", None, "hi", "hi", "audio tag hi beats English-looking text"),
    ("Market Outlook", "en-US", None, "en", "en-US counts as English"),
    ("Market Outlook", None, None, "en", "no tag, plain English text"),
    # Uploaders leave defaultLanguage at "en" while publishing Hindi — the
    # Devanagari in the title has to win, or these reach the shelf.
    ("Raamdeo Agrawal stock picks | पोर्टफोलियो के Dark Horse", "en", "en",
     "hi", "Devanagari in title beats an 'en' tag"),
    ("AI Capex Cycle और भारत के Market Valuations | August", "en", None,
     "hi", "same, mixed-script title"),
    # "zxx" means "no linguistic content" and is set carelessly — it must not
    # be treated as a language, or 47 English videos get hidden.
    ("Monthly Market Outlook by Prateek Agrawal", None, "zxx", "en",
     "zxx audio tag ignored, falls through to text"),
    ("Market Outlook", "und", None, "en", "und tag ignored"),
]


def main():
    failures = []

    print("=== detection from text ===")
    for title, expected, note in CASES:
        got, why = detect(title)
        ok = got == expected
        if not ok:
            failures.append(f"{title[:44]!r}: got {got}, expected {expected} ({why})")
        print(f"  {'ok  ' if ok else 'FAIL'} [{got:2}] {title[:46]:48} {note}")

    print("\n=== YouTube language tags override text ===")
    for title, tag, audio, expected, note in TAG_CASES:
        got, why = detect(title, tag=tag, audio_tag=audio)
        ok = got == expected
        if not ok:
            failures.append(f"tag case {title[:30]!r}: got {got}, expected {expected}")
        print(f"  {'ok  ' if ok else 'FAIL'} [{got:2}] {note}")

    print("\n=== hinglish needs two distinct markers ===")
    for text, expected in [("kaise kare", True), ("kaash", False),
                           ("Shanghai market", False), ("nahi hai", True)]:
        got = looks_hinglish(text)
        ok = got == expected
        if not ok:
            failures.append(f"looks_hinglish({text!r}) = {got}, expected {expected}")
        print(f"  {'ok  ' if ok else 'FAIL'} [{str(got):5}] {text!r}")

    if failures:
        print(f"\n{len(failures)} FAILURE(S):")
        for f in failures:
            print("  " + f)
        return 1
    print(f"\nall {len(CASES) + len(TAG_CASES) + 4} cases correct")
    return 0


if __name__ == "__main__":
    sys.exit(main())
