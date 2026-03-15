"""
Meeting Prep Agent — Generates meeting briefs, talking points, and action items.

Capabilities:
- Scan upcoming calendar events for meetings needing prep
- Pull related emails (by subject/sender matching) for context
- Summarize prior conversation threads
- Generate talking points, questions, and expected action items using Claude
"""

import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional
from anthropic import Anthropic

from utils.graph_auth import graph_get

logger = logging.getLogger(__name__)

MEETING_PREP_SYSTEM_PROMPT = """You are a meeting prep assistant for a Technical Account Manager (TAM) at Truv.com.
Truv provides income/employment verification APIs to fintech, mortgage, and lending companies.

For each meeting, produce a concise brief containing:
1. CONTEXT: 2-3 sentences about who the attendees likely are and the purpose
2. TALKING_POINTS: 4-6 bullet points to cover (prioritize customer success + Truv value)
3. QUESTIONS: 3-4 open-ended discovery or follow-up questions to ask
4. ACTION_ITEMS: Likely follow-up actions after the meeting (2-4 items)
5. TRUV_RESOURCES: Relevant Truv docs/features to mention (e.g., specific API endpoints, docs.truv.com links)

Return ONLY valid JSON with keys: context, talking_points, questions, action_items, truv_resources."""


def fetch_related_emails(
    subject_keywords: list[str],
    sender_email: Optional[str] = None,
    limit: int = 5,
    user_id: str = "me",
) -> list[dict]:
    """
    Search inbox for emails related to a meeting (by keyword/sender).
    Returns list of email dicts with subject, from, bodyPreview, receivedDateTime.
    """
    if not subject_keywords and not sender_email:
        return []

    # Build filter: search by sender if available, otherwise keyword scan
    filter_parts = []
    if sender_email:
        filter_parts.append(f"from/emailAddress/address eq '{sender_email}'")

    params: dict = {
        "$top": limit,
        "$select": "subject,from,bodyPreview,receivedDateTime",
        "$orderby": "receivedDateTime desc",
    }

    if filter_parts:
        params["$filter"] = " and ".join(filter_parts)
    elif subject_keywords:
        # Use $search for keyword matching (requires specific Graph permissions)
        params["$search"] = f'"{subject_keywords[0]}"'

    try:
        data = graph_get(f"/users/{user_id}/messages", params=params)
        emails = data.get("value", [])
        # Client-side keyword filter when not using $search
        if subject_keywords and "$search" not in params:
            kws = [kw.lower() for kw in subject_keywords]
            emails = [
                e for e in emails
                if any(kw in (e.get("subject", "") + e.get("bodyPreview", "")).lower() for kw in kws)
            ]
        return emails[:limit]
    except Exception as exc:
        logger.warning("Could not fetch related emails: %s", exc)
        return []


def extract_meeting_context(event: dict) -> dict:
    """Extract key metadata from a calendar event dict."""
    subject = event.get("subject", "(no title)")
    organizer = event.get("organizer", {}).get("emailAddress", {})
    attendees = event.get("attendees", [])
    body_preview = event.get("bodyPreview", "")

    try:
        start = datetime.fromisoformat(
            event["start"]["dateTime"].replace("Z", "+00:00")
        ).strftime("%A %b %d at %H:%M")
    except (KeyError, ValueError):
        start = "Unknown time"

    attendee_names = [
        a.get("emailAddress", {}).get("name", a.get("emailAddress", {}).get("address", ""))
        for a in attendees
        if a.get("type") != "required" or True  # include all
    ]

    return {
        "subject": subject,
        "start": start,
        "organizer_name": organizer.get("name", ""),
        "organizer_email": organizer.get("address", ""),
        "attendees": attendee_names,
        "body_preview": body_preview[:300],
    }


def generate_meeting_brief(
    client: Anthropic,
    meeting_ctx: dict,
    related_emails: list[dict],
) -> dict:
    """
    Use Claude to generate a structured meeting brief.
    Returns dict with context, talking_points, questions, action_items, truv_resources.
    """
    email_context = ""
    if related_emails:
        email_lines = []
        for e in related_emails[:3]:
            email_lines.append(
                f"  [{e.get('receivedDateTime', '')[:10]}] "
                f"From: {e.get('from', {}).get('emailAddress', {}).get('address', '')} — "
                f"{e.get('subject', '')} | {e.get('bodyPreview', '')[:150]}"
            )
        email_context = "\n\nRELATED EMAILS:\n" + "\n".join(email_lines)

    attendees_str = ", ".join(meeting_ctx.get("attendees", [])[:6]) or "unknown"

    prompt = f"""Prepare a brief for this meeting:

Subject: {meeting_ctx['subject']}
Time: {meeting_ctx['start']}
Organizer: {meeting_ctx['organizer_name']} ({meeting_ctx['organizer_email']})
Attendees: {attendees_str}
Meeting notes/agenda preview: {meeting_ctx['body_preview']}
{email_context}"""

    try:
        response = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=1024,
            thinking={"type": "adaptive"},
            system=MEETING_PREP_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        text = next(
            (b.text for b in response.content if b.type == "text"), "{}"
        )
        text = text.strip().lstrip("```json").rstrip("```").strip()
        return json.loads(text)
    except Exception as exc:
        logger.error("Meeting brief generation failed: %s", exc)
        return {
            "context": f"Meeting: {meeting_ctx['subject']}",
            "talking_points": ["Introductions", "Agenda review", "Q&A"],
            "questions": ["What's the current status of your integration?"],
            "action_items": ["Send follow-up email", "Update CRM"],
            "truv_resources": ["docs.truv.com"],
        }


def run_meeting_prep_agent(
    client: Anthropic,
    hours_ahead: int = 24,
) -> list[dict]:
    """
    Main meeting prep agent entrypoint.
    Finds meetings in the next `hours_ahead` hours and generates prep briefs.
    Returns list of meeting brief dicts.
    """
    from utils.graph_auth import graph_get

    now = datetime.now(timezone.utc)
    end_dt = now + timedelta(hours=hours_ahead)

    try:
        data = graph_get(
            "/me/calendarView",
            params={
                "startDateTime": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "endDateTime":   end_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "$select": (
                    "id,subject,start,end,organizer,attendees,bodyPreview,isAllDay"
                ),
                "$orderby": "start/dateTime",
                "$top": 10,
            },
        )
        events = [e for e in data.get("value", []) if not e.get("isAllDay")]
    except Exception as exc:
        logger.error("Failed to fetch meetings: %s", exc)
        return []

    if not events:
        logger.info("No meetings found in the next %d hours.", hours_ahead)
        return []

    briefs = []
    for event in events:
        meeting_ctx = extract_meeting_context(event)
        subject = meeting_ctx["subject"]
        organizer_email = meeting_ctx.get("organizer_email", "")

        logger.info("Preparing brief for: %s", subject)

        # Fetch related emails for context
        keywords = [w for w in subject.split() if len(w) > 3][:3]
        related_emails = fetch_related_emails(
            subject_keywords=keywords,
            sender_email=organizer_email or None,
            limit=5,
        )

        brief = generate_meeting_brief(client, meeting_ctx, related_emails)

        briefs.append({
            "event_id": event.get("id", ""),
            "subject": subject,
            "start": meeting_ctx["start"],
            "organizer": meeting_ctx["organizer_email"],
            "attendees": meeting_ctx["attendees"],
            "brief": brief,
            "related_email_count": len(related_emails),
        })

    return briefs
