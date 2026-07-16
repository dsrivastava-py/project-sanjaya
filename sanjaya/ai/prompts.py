"""Prompt templates (PRD §9.3), implemented verbatim. Each builder returns a
``(system, user)`` pair of strings; the AI layer sends them unchanged (after
redaction). Keeping the wording here — and only here — makes prompt-regression
tests (§15) a matter of diffing this file.
"""
from __future__ import annotations

import json

# Default user context injected into every prompt (§9.3). Overridable via
# config [ai].user_context.
DEFAULT_USER_CONTEXT = (
    "Runs web agency DevsCrest; college student; dual degree; preparing for placements."
)


# --- A) Span classifier (batch <=40 unknown spans) ---------------------------
_CLASSIFIER_SYSTEM = """\
You classify computer-activity records into the user's categories. Respond with
JSON only: {{"classifications":[{{"i":<index>,"category":"<name>","project":"<name or null>","confidence":<0..1>}}]}}.
Use ONLY these categories: {category_names}.
Known projects per category: {projects_json}.
The user's context: {user_context}
If genuinely ambiguous, pick the most likely category with low confidence."""


def classifier(category_names: list[str], projects_by_category: dict[str, list[str]],
               records: list[dict], user_context: str | None = None) -> tuple[str, str]:
    system = _CLASSIFIER_SYSTEM.format(
        category_names=", ".join(category_names),
        projects_json=json.dumps(projects_by_category, ensure_ascii=False),
        user_context=user_context or DEFAULT_USER_CONTEXT,
    )
    lines = ["Records:"]
    for r in records:
        lines.append(
            '{i}. app={app_name} | kind={kind} | title="{title}" | '
            'domain={domain} | detail={detail_compact}'.format(
                i=r["i"], app_name=r.get("app_name") or "",
                kind=r.get("kind") or "", title=r.get("title") or "",
                domain=r.get("domain") or "", detail_compact=r.get("detail_compact") or "",
            )
        )
    return system, "\n".join(lines)


# --- B) Daily journal --------------------------------------------------------
_JOURNAL_SYSTEM = """\
You are Sanjaya, a faithful narrator of the user's day, writing their journal so
they don't have to. Honest, specific, warm but not sycophantic. Never invent
activities not present in the data. Write in second person ("You ..."). Respond
with JSON only:
{"narrative_md": "<150-250 word markdown journal entry>",
 "highlights": ["<3-6 concrete accomplishments or notable events>"],
 "suggestions": ["<1-3 specific, actionable suggestions for tomorrow>"]}"""


def daily_journal(payload: dict) -> tuple[str, str]:
    """``payload`` fields come from reporting.build_day_payload (§9.3 B)."""
    user = (
        "Date: {date} ({weekday})\n"
        "Active screen time: {active_h}h {active_m}m · Idle: {idle_time} · "
        "Focus score: {focus_score}/100\n"
        "Category totals: {category_totals}\n"
        "Goal status: {goal_status}\n"
        "Timeline (compressed, local time):\n{timeline}\n"
        "Stopwatch readings: {stopwatch}\n"
        "User's corrections today (respect these): {edits}\n"
        "Yesterday's suggestions (report follow-through): {yesterday_suggestions}"
    ).format(**payload)
    return _JOURNAL_SYSTEM, user


# --- C) Weekly insight -------------------------------------------------------
_WEEKLY_SYSTEM = """\
You are Sanjaya, a faithful narrator of the user's week. Honest, specific, warm
but not sycophantic. Never invent activities not present in the data. Write in
second person ("You ..."). Respond with JSON only:
{"insight_md": "<200-320 word markdown weekly reflection>",
 "wins": ["<2-5 concrete wins this week>"],
 "leaks": ["<1-4 time leaks or missed goals, with the numbers>"],
 "next_week_focus": ["<1-3 specific priorities for next week>"]}"""


def weekly_insight(payload: dict) -> tuple[str, str]:
    user = (
        "Week: {week_start} to {week_end}\n"
        "Weekly category totals: {category_totals}\n"
        "Goal streaks: {goal_streaks}\n"
        "Daily focus scores: {focus_scores}\n"
        "Daily summaries:\n{day_summaries}"
    ).format(**payload)
    return _WEEKLY_SYSTEM, user
