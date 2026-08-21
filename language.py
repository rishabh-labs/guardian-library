"""Work out what language a video is in.

Three signals, most reliable first:

1. The language YouTube itself reports (`defaultAudioLanguage` /
   `defaultLanguage` on the videos endpoint). Authoritative when present, but
   many uploaders never set it.
2. The script the title is written in. A title containing Devanagari or Telugu
   characters is not an English video, whatever the metadata claims.
3. Romanised Hindi. "Roz Market Nahi Dekh Sakte?" is Latin script but is not
   an English video, so scripts alone are not enough.
"""
import re

# Unicode ranges for the scripts that actually show up on Indian fund channels.
SCRIPTS = [
    ("hi", r"ऀ-ॿ"),   # Devanagari - Hindi, Marathi
    ("bn", r"ঀ-৿"),   # Bengali
    ("pa", r"਀-੿"),   # Gurmukhi - Punjabi
    ("gu", r"઀-૿"),   # Gujarati
    ("or", r"଀-୿"),   # Odia
    ("ta", r"஀-௿"),   # Tamil
    ("te", r"ఀ-౿"),   # Telugu
    ("kn", r"ಀ-೿"),   # Kannada
    ("ml", r"ഀ-ൿ"),   # Malayalam
    ("ur", r"؀-ۿ"),   # Arabic - Urdu
]
SCRIPT_RES = [(code, re.compile(f"[{rng}]")) for code, rng in SCRIPTS]

# Romanised Hindi/Hinglish. Whole-word matches only: "hai" must not fire on
# "Shanghai", "kar" not on "market".
HINGLISH = re.compile(
    r"\b(kaise|kaisa|kyun|kyu|kya|nahi|nahin|hai|hain|tha|thi|karo|kare|karna|"
    r"karein|dekh|dekho|dekhe|dekhna|samajh|samjhe|bata|batao|jaane|jaanein|"
    r"chahiye|milega|milta|hoga|hogi|honge|rahe|raha|rahi|liye|lekin|magar|"
    r"aur|abhi|kabhi|sabse|jyada|zyada|thoda|bahut|paisa|paise|rupaye|"
    r"nivesh|bazaar|baazar|shuru|band|accha|achha|sahi|galat|matlab|"
    r"roz|aaj|kal|saal|mahina|din|waqt|samay|"
    r"apna|apne|hamara|humara|tumhara|unka|iska|uska|"
    r"kaash|jaldi|dhyan|faayda|fayda|nuksan|munafa|kamai)\b", re.I)

# Language tags that count as English ("en", "en-US", "en-IN", "en-GB", ...).
ENGLISH_TAG = re.compile(r"^en(-|$)", re.I)

# Tags that carry no information. "zxx" is the ISO code for "no linguistic
# content"; uploaders set it (and "und") carelessly on ordinary talking-head
# videos, so treating either as a real language hides English content.
EMPTY_TAGS = {"zxx", "und", "mul", "mis"}


def from_tag(tag):
    """Interpret a YouTube language tag. Returns a code or None."""
    if not tag:
        return None
    tag = tag.strip()
    if ENGLISH_TAG.match(tag):
        return "en"
    code = tag.split("-")[0].lower()
    return None if code in EMPTY_TAGS else code


def from_script(text):
    """Detect a non-Latin script. Returns a code or None.

    A stray character isn't enough - channel names and hashtags sometimes carry
    one. Require a meaningful share of the text to be in the script.
    """
    if not text:
        return None
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return None
    for code, pattern in SCRIPT_RES:
        hits = len(pattern.findall(text))
        if hits >= 3 or (hits and hits / len(letters) > 0.15):
            return code
    return None


def looks_hinglish(text):
    """Romanised Hindi. Two distinct marker words to avoid false positives."""
    if not text:
        return False
    found = {m.group(0).lower() for m in HINGLISH.finditer(text)}
    return len(found) >= 2


def detect(title, description="", channel="", tag=None, audio_tag=None):
    """Returns (code, why). Code is an ISO language, or '' when undetermined."""
    # 1. Script of the title outranks the metadata tag. Uploaders routinely
    #    leave defaultLanguage at "en" while publishing in Hindi, and the title
    #    is what actually appears on the shelf - so visible script wins.
    code = from_script(title)
    if code:
        return code, f"{code} script in title"

    # 2. What YouTube says, when the uploader set something meaningful.
    for source, value in (("audio track", audio_tag), ("metadata", tag)):
        code = from_tag(value)
        if code:
            return code, f"{source}: {value}"

    # 3. Script of the description.
    code = from_script(description)
    if code:
        return code, f"{code} script in description"

    # 3. Romanised Hindi in the title (descriptions are often boilerplate).
    if looks_hinglish(title):
        return "hi", "romanised Hindi in title"

    # A channel named in another script is a decent hint about its output.
    code = from_script(channel)
    if code:
        return code, f"{code} script in channel name"

    # Latin script, no markers - treat as English rather than unknown, so a
    # missing metadata tag doesn't hide a perfectly good English video.
    return "en", "latin script, no other-language markers"
