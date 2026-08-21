"""Is the fund manager in this video, or is someone talking about the fund?

Both kinds mention the fund. Only one is worth watching when you hold the
product: the manager's own view. A reviewer's take on "Tata Small Cap" is a
different thing from Chandraprakash Padiyar explaining what he bought.

The rule is deliberately simple, because the signal is strong:

  from the house's own channel        -> the manager's content
  a manager's full name in the title  -> the manager is the guest
  otherwise                           -> somebody else's video about the fund

The house name alone never qualifies. That is exactly what a review says.
"""
import re

# Phrasing that belongs to commentary *about* a fund rather than *by* it.
REVIEW_PHRASES = re.compile(
    r"\bshould you (invest|buy|hold|exit)\b|worth (investing|buying|it)\b|"
    r"\breview\b|\brating\b|\branked?\b|\bvs\.?\b|\bversus\b|\bcompare[ds]?\b|"
    r"\btop \d+\b|\bbest \w+ (funds?|pms|schemes?)\b|\bwhich (fund|scheme)\b|"
    r"\bmy (portfolio|picks)\b|\bhonest (review|opinion)\b|"
    r"\bgood or bad\b|\bavoid\b|\bexposed\b|\btruth about\b|"
    r"\breturns? (analysis|breakdown)\b|\bperformance (review|analysis)\b|"
    r"\bfund analysis\b|\bdeep dive into\b", re.I)

# An interview framing is a positive signal: the manager is the subject.
INTERVIEW_PHRASES = re.compile(
    r"\bin conversation\b|\binterview\b|\bexclusive\b|\bspeaks? (to|with)\b|"
    r"\btalks? (to|about)\b|\bfireside\b|\bpodcast\b|\bepisode\b|\bAMA\b|"
    r"\bon (the )?(markets?|outlook|portfolio|strategy)\b", re.I)


def name_variants(full_name):
    """Ways a person's name legitimately appears in a title.

    Full name, and surname alone only when the first name is also present
    somewhere - a bare "Shah" or "Agrawal" is far too common to trust.
    """
    parts = [p for p in re.split(r"[^\w]+", full_name or "") if len(p) > 1]
    if not parts:
        return []
    return [" ".join(parts)] if len(parts) == 1 else [" ".join(parts)]


def names_present(text, managers):
    """Which of these managers are named in the text."""
    blob = (text or "").lower()
    hits = []
    for m in managers:
        for variant in name_variants(m):
            if variant.lower() in blob:
                hits.append(m)
                break
    return hits


def detect(title, description="", channel="", managers=(),
           from_own_channel=False):
    """Returns (speaker, why): 'manager' or 'third_party'."""
    managers = [m.strip() for m in managers if m and m.strip()]

    # The house's own channel only publishes the house's own content.
    if from_own_channel:
        return "manager", "the house's own channel"

    in_title = names_present(title, managers)
    if in_title:
        # A named manager plus reviewer phrasing is still usually the manager
        # ("Saurabh Mukherjea on why we exited HDFC Bank" contains no review
        # phrasing; "Best PMS review ft. Saurabh Mukherjea" does, and is an
        # interview in review clothing). Naming them in the title wins.
        return "manager", f"names {in_title[0]} in the title"

    in_desc = names_present(description, managers)
    if in_desc and INTERVIEW_PHRASES.search(f"{title} {description}"):
        return "manager", f"names {in_desc[0]}, interview framing"

    if REVIEW_PHRASES.search(title):
        return "third_party", "review phrasing, no manager named"

    if in_desc:
        return "third_party", f"{in_desc[0]} mentioned only in the description"

    return "third_party", "no tracked manager named"
