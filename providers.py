"""Where the summaries come from.

Two ways to get a newsletter summarised, deliberately interchangeable:

  api          the Anthropic API, billed per token against prepaid credit
  claude_code  the Claude Code CLI in headless mode, which authenticates with
               the Claude subscription already on this machine and so costs
               nothing extra

Both return the same dict, so analyse.py does not care which one ran.

The claude_code provider only works on a machine where Claude Code is installed
and signed in. That means the laptop, not a cloud server - see summarise_worker.py
for driving a deployed portal from here.
"""
import json
import logging
import os
import re
import shutil
import subprocess

import config

log = logging.getLogger("providers")

FIELDS = ("headline", "summary", "highlights", "portfolio_actions",
          "numbers", "outlook")


class ProviderError(RuntimeError):
    """The provider could not produce a summary."""


# ---------------------------------------------------------------- discovery

def find_claude_cli():
    """Locate the Claude Code executable.

    Checked in order: an explicit setting, PATH, then the versioned install
    directory the desktop app uses, newest version first.
    """
    if config.CLAUDE_CLI_PATH:
        if os.path.exists(config.CLAUDE_CLI_PATH):
            return config.CLAUDE_CLI_PATH
        raise ProviderError(
            f"CLAUDE_CLI_PATH points at {config.CLAUDE_CLI_PATH}, "
            "which does not exist")

    found = shutil.which("claude")
    if found:
        return found

    roots = [
        os.path.join(os.path.expanduser("~"), "AppData", "Roaming", "Claude",
                     "claude-code"),
        os.path.join(os.path.expanduser("~"), ".local", "share", "claude-code"),
    ]
    best = None
    for root in roots:
        if not os.path.isdir(root):
            continue
        for name in os.listdir(root):
            for exe in ("claude.exe", "claude"):
                path = os.path.join(root, name, exe)
                if os.path.exists(path):
                    key = _version_key(name)
                    if best is None or key > best[0]:
                        best = (key, path)
    if best:
        return best[1]
    raise ProviderError(
        "Claude Code CLI not found. Install it, or set CLAUDE_CLI_PATH to the "
        "full path of claude.exe")


def _version_key(name):
    return tuple(int(p) if p.isdigit() else 0 for p in name.split("."))


def _clean_env():
    """A child environment with this shell's Claude Code session stripped out.

    Run from inside a Claude Code session, the CLAUDE_CODE_* variables tell a
    child process to expect its token from the host rather than resolve its own
    credentials, and it reports "Not logged in". Started from the portal these
    variables are absent anyway; removing them makes the behaviour identical
    either way.
    """
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("CLAUDE") and k != "ANTHROPIC_API_KEY"}
    return env


# ---------------------------------------------------------------- providers

def summarise_via_claude_code(system, context, text, tool_schema):
    """Run the summary through the local Claude Code CLI.

    Headless Claude Code has no tool-forcing, so the schema is described in the
    prompt and the JSON is parsed back out. Everything else - the system prompt,
    the fields, the output shape - matches the API path exactly.
    """
    shape = json.dumps(tool_schema["input_schema"]["properties"], indent=2)
    prompt = (
        f"{system}\n\n"
        "Reply with a single JSON object and nothing else. No markdown fence, "
        "no commentary before or after. These are the fields:\n\n"
        f"{shape}\n\n"
        "Here is the item to summarise:\n\n"
        f"{context}\n---\n\n{text}"
    )

    return _parse_payload(_run_claude_code(prompt))


def _run_claude_code(prompt):
    """Send one prompt through headless Claude Code, return the reply text."""
    exe = find_claude_cli()
    cmd = [exe, "-p", "--output-format", "json"]
    if config.CLAUDE_CLI_MODEL:
        cmd += ["--model", config.CLAUDE_CLI_MODEL]

    try:
        proc = subprocess.run(
            cmd, input=prompt, capture_output=True, text=True,
            encoding="utf-8", errors="replace",
            timeout=config.CLAUDE_CLI_TIMEOUT, env=_clean_env())
    except subprocess.TimeoutExpired:
        raise ProviderError(
            f"Claude Code timed out after {config.CLAUDE_CLI_TIMEOUT}s")

    if proc.returncode != 0:
        raise ProviderError(_explain_failure(proc))

    try:
        envelope = json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise ProviderError(
            f"could not read Claude Code output: {proc.stdout[:200]!r}")

    if envelope.get("is_error"):
        raise ProviderError(_explain_failure(proc, envelope))

    return envelope.get("result", "")


def _explain_failure(proc, envelope=None):
    """Turn a CLI failure into something worth reading in the Analysis tab."""
    detail = ""
    if envelope:
        detail = str(envelope.get("result", ""))
    if not detail:
        detail = (proc.stderr or proc.stdout or "").strip()[:300]
    if "not logged in" in detail.lower() or "/login" in detail:
        return ("Claude Code is not signed in. Open a terminal and run "
                "'claude' once, sign in, then try again.")
    if "limit" in detail.lower():
        return f"Claude Code usage limit reached: {detail}"
    return f"Claude Code failed: {detail}"


CLASSIFY_INSTRUCTION = """You sort a fund house's video output for an analyst who
wants only substantive commentary.

'research' - a fund manager or analyst discussing markets, strategy, portfolio
positioning, or teaching an investing concept.
'promo' - marketing: a scheme launch or NFO, a festival greeting, an award or
milestone, a call to invest, or short filler content.

When genuinely uncertain answer 'research': missing a real manager video costs
more than letting a promo through."""


def classify_batch(records):
    """Sort a batch of ambiguous videos into research or promo.

    One call for the whole batch rather than one per video. Spawning Claude
    Code 48 times would take minutes and burn subscription quota for what is
    a handful of tokens of judgement each.

    records: [{"n": int, "title": str, "author": str, "description": str}]
    returns: {n: (category, reason)} - only for entries the model answered.
    """
    if not records:
        return {}

    listing = "\n\n".join(
        f"[{r['n']}] Channel: {r.get('author', '')}\n"
        f"Title: {r['title']}\n"
        f"Description: {(r.get('description') or '')[:400]}"
        for r in records)

    prompt = (
        f"{CLASSIFY_INSTRUCTION}\n\n"
        f"Sort each of the {len(records)} videos below.\n\n"
        "Reply with a single JSON object and nothing else - no markdown fence, "
        'no commentary. Shape: {"verdicts": [{"n": <the number in brackets>, '
        '"category": "research" or "promo", "reason": "under 10 words"}]}\n'
        "Include every video exactly once.\n\n"
        f"{listing}")

    if config.ANALYSIS_PROVIDER == "claude_code":
        raw = _run_claude_code(prompt)
    else:
        raw = _run_api_text(prompt)

    payload = _extract_json(raw)
    out = {}
    for v in payload.get("verdicts", []):
        try:
            n = int(v["n"])
            category = str(v["category"]).strip().lower()
        except (KeyError, TypeError, ValueError):
            continue
        if category in ("research", "promo"):
            out[n] = (category, str(v.get("reason", ""))[:120])
    return out


def _run_api_text(prompt):
    if not config.ANTHROPIC_API_KEY:
        raise ProviderError("ANTHROPIC_API_KEY is not set")
    import anthropic
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    resp = client.messages.create(
        model=config.CLASSIFY_MODEL, max_tokens=4000,
        messages=[{"role": "user", "content": prompt}])
    return "".join(b.text for b in resp.content if b.type == "text")


def _parse_payload(raw):
    """Pull the JSON object out of the model's reply.

    Tolerates a markdown fence or a stray sentence around it, because a
    conversational CLI is less strictly bound than a forced tool call.
    """
    return {k: _extract_json(raw).get(k) for k in FIELDS}


def _extract_json(raw):
    """Recover the JSON object from a reply that may be wrapped in prose."""
    raw = (raw or "").strip()
    if not raw:
        raise ProviderError("Claude Code returned nothing")

    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", raw, re.S)
    candidate = fenced.group(1) if fenced else raw
    if not candidate.lstrip().startswith("{"):
        start, end = candidate.find("{"), candidate.rfind("}")
        if start == -1 or end <= start:
            raise ProviderError(f"no JSON in the reply: {raw[:200]!r}")
        candidate = candidate[start:end + 1]

    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise ProviderError(f"reply was not valid JSON ({exc}): {raw[:200]!r}")

    if not isinstance(payload, dict):
        raise ProviderError("reply was not a JSON object")
    return payload


def summarise_via_api(system, context, text, tool_schema):
    """The paid path: one forced tool call against the Anthropic API."""
    if not config.ANTHROPIC_API_KEY:
        raise ProviderError("ANTHROPIC_API_KEY is not set")
    import anthropic
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    resp = client.messages.create(
        model=config.ANALYSIS_MODEL,
        max_tokens=2000,
        system=system,
        tools=[tool_schema],
        tool_choice={"type": "tool", "name": tool_schema["name"]},
        messages=[{"role": "user", "content": f"{context}\n---\n\n{text}"}],
    )
    payload = next(b.input for b in resp.content if b.type == "tool_use")
    return {k: payload.get(k) for k in FIELDS}


PROVIDERS = {
    "api": summarise_via_api,
    "claude_code": summarise_via_claude_code,
}


def summarise(system, context, text, tool_schema):
    fn = PROVIDERS.get(config.ANALYSIS_PROVIDER)
    if not fn:
        raise ProviderError(
            f"unknown ANALYSIS_PROVIDER {config.ANALYSIS_PROVIDER!r}; "
            f"expected one of {', '.join(PROVIDERS)}")
    return fn(system, context, text, tool_schema)


def available():
    """(ok, explanation) - whether summaries can run at all right now."""
    if config.ANALYSIS_PROVIDER == "claude_code":
        try:
            return True, f"Claude Code at {find_claude_cli()}"
        except ProviderError as exc:
            return False, str(exc)
    if config.ANTHROPIC_API_KEY:
        return True, f"Anthropic API, model {config.ANALYSIS_MODEL}"
    return False, "ANTHROPIC_API_KEY is not set"
