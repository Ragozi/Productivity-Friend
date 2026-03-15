"""
Calendar Agent — Scans Outlook Calendar events and generates daily organization.

Capabilities:
- Fetch today's and upcoming calendar events via Graph API
- Identify conflicts (overlapping events)
- Suggest time blocks for deep work / email processing
- Generate a daily to-do list and recommended next actions using Claude
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from anthropic import Anthropic

from utils.graph_auth import graph_get

logger = logging.getLogger(__name__)

CALENDAR_SYSTEM_PROMPT = """You are an executive productivity assistant for a Technical Account Manager (TAM) at Truv.com.
Truv provides income/employment verification APIs to enterprise clients.
A TAM's key responsibilities: onboarding new customers, resolving integration issues,
conducting business reviews, coordinating with engineering, tracking API usage, and renewals.

When analyzing the calendar, provide:
1. CONFLICTS: Any overlapping or back-to-back meetings needing attention
2. TIME_BLOCKS: Suggested 30-90 min focus blocks for deep work (email processing, customer prep, etc.)
3. TODO: Prioritized to-do list for today (5-7 items max) based on meetings and TAM context
4. NEXT_ACTIONS: Top 3 immediate next actions

Return ONLY valid JSON with keys: conflicts (array), time_blocks (array), todo (array), next_actions (array)."""


def fetch_calendar_events(
    days_ahead: int = 1,
    user_id: str = "me",
) -> list[dict]:
    """
    Fetch calendar events for today and `days_ahead` future days.
    Returns list of event dicts with start, end, subject, location, organizer.
    """
    now = datetime.now(timezone.utc)
    end_dt = now + timedelta(days=days_ahead)

    start_str = now.strftime("%Y-%m-%dT00:00:00Z")
    end_str   = end_dt.strftime("%Y-%m-%dT23:59:59Z")

    logger.info("Fetching calendar events from %s to %s...", start_str, end_str)
    try:
        data = graph_get(
            f"/users/{user_id}/calendarView",
            params={
                "startDateTime": start_str,
                "endDateTime":   end_str,
                "$select": (
                    "id,subject,start,end,location,organizer,"
                    "attendees,isAllDay,bodyPreview,onlineMeeting"
                ),
                "$orderby": "start/dateTime",
                "$top": 50,
            },
        )
        events = data.get("value", [])
        logger.info("Fetched %d calendar events.", len(events))
        return events
    except Exception as exc:
        logger.error("Failed to fetch calendar events: %s", exc)
        return []


def detect_conflicts(events: list[dict]) -> list[dict]:
    """
    Detect overlapping calendar events (same-day, overlapping time windows).
    Returns list of conflict pairs: [{"event_a": ..., "event_b": ...}]
    """
    conflicts = []
    timed = [e for e in events if not e.get("isAllDay")]

    for i in range(len(timed)):
        for j in range(i + 1, len(timed)):
            a = timed[i]
            b = timed[j]
            try:
                a_start = datetime.fromisoformat(a["start"]["dateTime"].replace("Z", "+00:00"))
                a_end   = datetime.fromisoformat(a["end"]["dateTime"].replace("Z", "+00:00"))
                b_start = datetime.fromisoformat(b["start"]["dateTime"].replace("Z", "+00:00"))
                b_end   = datetime.fromisoformat(b["end"]["dateTime"].replace("Z", "+00:00"))

                # Overlap check: a starts before b ends AND b starts before a ends
                if a_start < b_end and b_start < a_end:
                    conflicts.append({
                        "event_a": {"subject": a.get("subject"), "start": str(a_start), "end": str(a_end)},
                        "event_b": {"subject": b.get("subject"), "start": str(b_start), "end": str(b_end)},
                    })
            except (KeyError, ValueError):
                pass
    return conflicts


def format_events_for_claude(events: list[dict]) -> str:
    """Format events into a compact string for LLM consumption."""
    lines = []
    for evt in events:
        if evt.get("isAllDay"):
            time_str = "All Day"
        else:
            try:
                start = datetime.fromisoformat(
                    evt["start"]["dateTime"].replace("Z", "+00:00")
                ).strftime("%H:%M")
                end = datetime.fromisoformat(
                    evt["end"]["dateTime"].replace("Z", "+00:00")
                ).strftime("%H:%M")
                time_str = f"{start}-{end}"
            except (KeyError, ValueError):
                time_str = "?"

        subject = evt.get("subject", "(no title)")
        organizer = evt.get("organizer", {}).get("emailAddress", {}).get("name", "")
        attendee_count = len(evt.get("attendees", []))
        location = evt.get("location", {}).get("displayName", "")

        line = f"  • [{time_str}] {subject}"
        if organizer:
            line += f" (org: {organizer})"
        if attendee_count > 1:
            line += f" — {attendee_count} attendees"
        if location:
            line += f" @ {location}"
        lines.append(line)

    return "\n".join(lines) if lines else "  (no events)"


def analyze_calendar(
    client: Anthropic,
    events: list[dict],
    current_date: str,
    conflicts: list[dict],
) -> dict:
    """
    Use Claude to analyze the calendar and produce a structured daily brief.
    Returns dict with: conflicts, time_blocks, todo, next_actions
    """
    events_text = format_events_for_claude(events)
    conflicts_text = (
        json.dumps(conflicts, indent=2) if conflicts else "None detected."
    )

    prompt = f"""Today is {current_date}.

CALENDAR EVENTS:
{events_text}

DETECTED CONFLICTS:
{conflicts_text}

Analyze this calendar and provide daily organization recommendations for a TAM at Truv."""

    try:
        response = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=1024,
            thinking={"type": "adaptive"},
            system=CALENDAR_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        text = next(
            (b.text for b in response.content if b.type == "text"), "{}"
        )
        text = text.strip().lstrip("```json").rstrip("```").strip()
        return json.loads(text)
    except Exception as exc:
        logger.error("Calendar analysis failed: %s", exc)
        return {
            "conflicts": conflicts,
            "time_blocks": [],
            "todo": ["Review emails", "Check Slack", "Prepare for meetings"],
            "next_actions": ["Open inbox", "Check calendar", "Review Truv dashboard"],
        }


def run_calendar_agent(
    client: Anthropic,
    days_ahead: int = 1,
) -> dict:
    """
    Main calendar agent entrypoint.
    Returns structured daily brief with conflicts, time blocks, todos, next actions.
    """
    events = fetch_calendar_events(days_ahead=days_ahead)
    conflicts = detect_conflicts(events)
    current_date = datetime.now().strftime("%A, %B %d, %Y")

    analysis = analyze_calendar(client, events, current_date, conflicts)

    return {
        "date": current_date,
        "event_count": len(events),
        "events": [
            {
                "subject": e.get("subject", ""),
                "start": e.get("start", {}).get("dateTime", ""),
                "end": e.get("end", {}).get("dateTime", ""),
                "is_all_day": e.get("isAllDay", False),
            }
            for e in events
        ],
        "conflicts": analysis.get("conflicts", conflicts),
        "suggested_time_blocks": analysis.get("time_blocks", []),
        "todo_list": analysis.get("todo", []),
        "next_actions": analysis.get("next_actions", []),
    }
