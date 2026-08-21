"""Summarise an item.

The summariser itself lives in providers.py - either the paid API or the
local Claude Code CLI, chosen by ANALYSIS_PROVIDER.

Output is forced through a tool schema so we always get the same fields back and
never have to parse prose.
"""
import logging

import config
import db
import extract
import providers

log = logging.getLogger("analyse")

SYSTEM = """You are an analyst at an Indian PMS house. Your firm allocates client
money to third-party PMS, AIF and mutual fund products, and reviews those
products regularly.

You will be given the text of a fund house's newsletter, investor letter or
factsheet for a product we are invested in.

Write for a reader who will NOT watch or read the original. They need enough to
decide whether the source is worth their own time, and enough to update their
view of the product if it isn't.

Rules:
- Report only what the source actually says. Never infer a number, a holding or
  a portfolio action that is not stated.
- Quote figures exactly as given, with their units and period.
- If the manager is vague or promotional, say so plainly rather than dressing it
  up as insight.
- Keep the manager's stated reasoning, not just their conclusion.
- No investment advice of your own, and no recommendation to buy or sell."""

TOOL = {
    "name": "record_analysis",
    "description": "Record the structured analysis of this source.",
    "input_schema": {
        "type": "object",
        "properties": {
            "headline": {
                "type": "string",
                "description": "One line, max 15 words, capturing the single "
                               "most important thing said.",
            },
            "summary": {
                "type": "string",
                "description": "3-5 sentences covering what was discussed and "
                               "the manager's core argument.",
            },
            "highlights": {
                "type": "array",
                "items": {"type": "string"},
                "description": "4-8 bullets, each a specific point made in the "
                               "source. Include the reasoning, not just claims.",
            },
            "portfolio_actions": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Any stated buys, sells, trims, adds, sector "
                               "rotation, cash levels or position changes. "
                               "Empty array if none were mentioned.",
            },
            "numbers": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Concrete figures quoted, each as 'label: value' "
                               "(e.g. 'FY26 revenue growth guidance: 14-16%'). "
                               "Empty array if none.",
            },
            "outlook": {
                "type": "string",
                "description": "The forward-looking view stated in the source, "
                               "in 1-2 sentences. Empty string if none given.",
            },
        },
        "required": ["headline", "summary", "highlights", "portfolio_actions",
                     "numbers", "outlook"],
    },
}


def _model_label():
    """What produced this summary, for the record on the item."""
    if config.ANALYSIS_PROVIDER == "claude_code":
        return "claude-code:" + (config.CLAUDE_CLI_MODEL or "default")
    return config.ANALYSIS_MODEL


def configured():
    """(ok, explanation) for whichever provider is selected."""
    return providers.available()


def analyse_item(item):
    """Extract, summarise and persist. Returns the status string written."""
    item_id = item["id"]
    if item["kind"] not in config.ANALYSABLE_KINDS:
        db.save_analysis(item_id, "skipped",
                         error=f"{item['kind']} items are not summarised")
        return "skipped"
    try:
        text, source_kind = extract.get_text(item)
    except extract.NoContent as exc:
        # A video with almost no speech in it is a Short or a title card, which
        # the title rules can miss. The transcript settles it.
        if item["kind"] == "video" and "too thin" in str(exc):
            db.set_content_type(item_id, "promo",
                                f"negligible transcript ({exc})")
        db.save_analysis(item_id, "skipped", error=str(exc))
        return "skipped"
    except Exception as exc:
        db.save_analysis(item_id, "failed",
                         error=f"extract {type(exc).__name__}: {exc}")
        return "failed"

    context = (
        f"Product we are invested in: {item.get('fund_name', 'unknown')}\n"
        f"Item type: {item['kind']}\n"
        f"Title: {item['title']}\n"
        f"Published by: {item.get('author') or 'unknown'}\n"
        f"Date: {item.get('published_at') or 'unknown'}\n"
        f"Source text type: {source_kind}\n"
    )

    try:
        payload = providers.summarise(SYSTEM, context, text, TOOL)
    except Exception as exc:
        db.save_analysis(item_id, "failed", source_kind=source_kind,
                         source_chars=len(text),
                         error=f"{type(exc).__name__}: {exc}")
        log.warning("analysis failed for item %s: %s", item_id, exc)
        return "failed"

    db.save_analysis(
        item_id, "done", source_kind=source_kind, source_chars=len(text),
        headline=payload.get("headline", ""),
        summary=payload.get("summary", ""),
        highlights=payload.get("highlights", []),
        portfolio_actions=payload.get("portfolio_actions", []),
        numbers=payload.get("numbers", []),
        outlook=payload.get("outlook", ""),
        model=_model_label())
    return "done"


def run_pending(limit=None):
    """Summarise anything that arrived without an analysis yet."""
    ok, why = configured()
    if not ok:
        log.info("no summariser available (%s) - skipping analysis pass", why)
        return {"done": 0, "skipped": 0, "failed": 0}

    limit = limit or config.MAX_ANALYSES_PER_RUN
    counts = {"done": 0, "skipped": 0, "failed": 0}
    for item in db.items_needing_analysis(limit):
        counts[analyse_item(item)] += 1
    log.info("analysis pass: %s", counts)
    return counts
