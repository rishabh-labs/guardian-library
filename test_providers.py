"""Claude Code returns prose, not a forced tool call, so the JSON has to be
recovered from whatever shape the reply arrives in. These are the shapes seen
in practice plus the failures worth naming clearly."""
import json

import providers

GOOD = {
    "headline": "Manager trimmed financials into strength",
    "summary": "Three sentences here.",
    "highlights": ["one", "two"],
    "portfolio_actions": ["Trimmed HDFC Bank"],
    "numbers": ["Cash: 12%"],
    "outlook": "Cautious on valuations.",
}

PARSE_CASES = [
    ("bare object", json.dumps(GOOD), True),
    ("json fence", "```json\n" + json.dumps(GOOD) + "\n```", True),
    ("plain fence", "```\n" + json.dumps(GOOD) + "\n```", True),
    ("preamble", "Here is the summary:\n\n" + json.dumps(GOOD), True),
    ("preamble and trailer",
     "Sure!\n" + json.dumps(GOOD) + "\nLet me know if you need more.", True),
    ("leading whitespace", "\n\n  " + json.dumps(GOOD), True),
    ("empty", "", False),
    ("no json at all", "I could not read that document.", False),
    ("broken json", '{"headline": "x", ', False),
    ("json array", "[1, 2, 3]", False),
]

FAILURE_CASES = [
    ("not logged in", "Not logged in · Please run /login", "not signed in"),
    ("usage limit", "5-hour limit reached, resets at 4pm", "usage limit"),
    ("other", "spawn ENOENT", "Claude Code failed"),
]


class FakeProc:
    def __init__(self, stdout="", stderr=""):
        self.stdout, self.stderr, self.returncode = stdout, stderr, 1


def main():
    failures = 0

    for name, raw, should_parse in PARSE_CASES:
        try:
            got = providers._parse_payload(raw)
            ok = should_parse and got["headline"] == GOOD["headline"]
            detail = "parsed"
        except providers.ProviderError as exc:
            ok = not should_parse
            detail = f"rejected ({str(exc)[:40]})"
        if not ok:
            failures += 1
            print(f"  FAIL  {name}: {detail}")

    # A reply missing a field must still return every key, so save_analysis
    # never sees a KeyError.
    partial = providers._parse_payload('{"headline": "only this"}')
    if set(partial) != set(providers.FIELDS):
        failures += 1
        print(f"  FAIL  partial reply lost fields: {sorted(partial)}")
    if partial["highlights"] is not None:
        failures += 1
        print("  FAIL  missing field should come back as None")

    for name, detail, expect in FAILURE_CASES:
        msg = providers._explain_failure(FakeProc(stderr=detail))
        if expect.lower() not in msg.lower():
            failures += 1
            print(f"  FAIL  {name}: {msg!r} does not mention {expect!r}")

    # The child environment must not carry this shell's Claude Code session,
    # or a nested run reports "Not logged in".
    import os
    os.environ["CLAUDE_CODE_CHILD_SESSION"] = "1"
    os.environ["ANTHROPIC_API_KEY"] = "sk-should-not-leak"
    env = providers._clean_env()
    leaked = [k for k in env if k.startswith("CLAUDE") or k == "ANTHROPIC_API_KEY"]
    if leaked:
        failures += 1
        print(f"  FAIL  child environment still carries {leaked}")
    if "PATH" not in env and "Path" not in env:
        failures += 1
        print("  FAIL  child environment lost PATH")

    total = len(PARSE_CASES) + len(FAILURE_CASES) + 4
    if failures:
        print(f"{failures} of {total} cases failed")
        return 1
    print(f"all {total} cases correct")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
