"""
Email Agent — Fetches, prioritizes, and drafts responses for Outlook emails.

Capabilities:
- Fetch unread messages from Outlook inbox via Microsoft Graph API
- Classify priority (HIGH / MEDIUM / LOW / SPAM / PHISHING) using Claude
- Auto-delete SPAM and PHISHING emails when --auto-clean is enabled
- Draft reply emails for high-priority messages
- Flag or archive lower-priority messages
- Detect JSON attachments (for the JSON Agent to process)
"""

import json
import logging
import base64
from typing import Optional
from anthropic import Anthropic

from utils.graph_auth import graph_get, graph_post, graph_patch, graph_delete

logger = logging.getLogger(__name__)

# Keywords that indicate urgency for a TAM at Truv
URGENCY_KEYWORDS = [
    "deployment", "integration", "production", "outage", "critical", "urgent",
    "escalation", "error", "bug", "broken", "down", "issue", "blocker",
    "api", "401", "403", "500", "/v1/", "failing", "launch",
]

# Fast-path phishing indicators (common patterns)
PHISHING_KEYWORDS = [
    "verify your account", "confirm your identity", "account has been suspended",
    "unusual sign-in activity", "click here to verify", "password expired",
    "update your payment information", "your account will be closed",
    "confirm your email address to avoid", "invoice attached", "wire transfer",
    "gift card", "nigerian prince", "lottery winner",
]

# Fast-path spam indicators
SPAM_KEYWORDS = [
    "unsubscribe", "you've been selected", "free gift", "limited time offer",
    "act now", "congratulations you have been selected", "click here to claim",
    "earn money from home", "work from home", "weight loss", "diet pill",
    "enlarge", "casino", "jackpot", "you won", "no cost", "risk free",
]

PRIORITY_SYSTEM_PROMPT = """You are an assistant helping a Technical Account Manager (TAM) at Truv.com
prioritize their email inbox. Truv provides income/employment verification APIs to enterprise clients.

Classify each email as HIGH, MEDIUM, LOW, SPAM, or PHISHING based on:
- HIGH: Production issues, urgent integration requests, customer escalations, API failures,
  anything mentioning deployment/outage/critical/down/error, C-level senders, launch deadlines
- MEDIUM: Integration questions, feature requests, follow-ups, meeting requests, vendor questions
- LOW: FYI updates, newsletters, automated reports, internal announcements
- SPAM: Unsolicited bulk email, marketing, promotions with no business value
- PHISHING: Attempts to steal credentials, fake security alerts, suspicious links asking to
  click/verify/confirm, impersonation of known services, unexpected invoice/payment requests

Return ONLY a JSON object with keys: priority (HIGH/MEDIUM/LOW/SPAM/PHISHING), reason (1 sentence), action (what to do)."""


def fetch_unread_emails(
    top: int = 20,
    user_id: str = "me",
) -> list[dict]:
    """
    Fetch unread emails from the Outlook inbox.

    Returns a list of message dicts with keys:
    id, subject, from, receivedDateTime, bodyPreview, hasAttachments
    """
    logger.info("Fetching up to %d unread emails...", top)
    try:
        data = graph_get(
            f"/users/{user_id}/mailFolders/inbox/messages",
            params={
                "$filter": "isRead eq false",
                "$top": top,
                "$select": (
                    "id,subject,from,receivedDateTime,"
                    "bodyPreview,hasAttachments,importance,body"
                ),
            },
        )
        messages = data.get("value", [])
        logger.info("Fetched %d unread emails.", len(messages))
        return messages
    except Exception as exc:
        logger.error("Failed to fetch emails: %s", exc)
        return []


def get_email_attachments(message_id: str, user_id: str = "me") -> list[dict]:
    """Fetch attachment metadata for a given message."""
    try:
        data = graph_get(f"/users/{user_id}/messages/{message_id}/attachments")
        return data.get("value", [])
    except Exception as exc:
        logger.warning("Could not fetch attachments for %s: %s", message_id, exc)
        return []


def get_json_attachment(
    message_id: str, user_id: str = "me"
) -> Optional[tuple[str, dict]]:
    """
    Look for a JSON attachment on the email. If found, return (filename, parsed_json).
    Returns None if no JSON attachment is present.
    """
    attachments = get_email_attachments(message_id, user_id)
    for att in attachments:
        name: str = att.get("name", "")
        if name.lower().endswith(".json"):
            content_bytes = att.get("contentBytes", "")
            if content_bytes:
                try:
                    raw = base64.b64decode(content_bytes).decode("utf-8")
                    parsed = json.loads(raw)
                    logger.info("Found JSON attachment: %s", name)
                    return name, parsed
                except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                    logger.warning("Could not parse JSON attachment %s: %s", name, exc)
    return None


def classify_email_priority(
    client: Anthropic,
    subject: str,
    sender: str,
    body_preview: str,
) -> dict:
    """
    Use Claude to classify email priority.
    Returns {"priority": str, "reason": str, "action": str}
    """
    combined_text = f"{subject} {body_preview}".lower()

    # Fast pre-check: phishing detection
    if any(kw in combined_text for kw in PHISHING_KEYWORDS):
        return {
            "priority": "PHISHING",
            "reason": "Contains phishing indicators (credential harvest, fake security alert, or suspicious link).",
            "action": "Delete immediately — do not click any links.",
        }

    # Fast pre-check: spam detection
    if any(kw in combined_text for kw in SPAM_KEYWORDS):
        return {
            "priority": "SPAM",
            "reason": "Matches spam patterns (unsolicited bulk email or marketing).",
            "action": "Delete — no action required.",
        }

    # Fast pre-check: keyword-based HIGH detection (avoids an LLM call)
    if any(kw in combined_text for kw in URGENCY_KEYWORDS):
        return {
            "priority": "HIGH",
            "reason": "Contains urgency keywords related to Truv integrations.",
            "action": "Draft a response and flag for immediate follow-up.",
        }

    prompt = f"""Email to classify:
Subject: {subject}
From: {sender}
Body preview: {body_preview}"""

    try:
        response = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=256,
            thinking={"type": "adaptive"},
            system=PRIORITY_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        # Extract JSON from the text block
        text = next(
            (b.text for b in response.content if b.type == "text"), "{}"
        )
        # Strip markdown fences if present
        text = text.strip().lstrip("```json").rstrip("```").strip()
        return json.loads(text)
    except Exception as exc:
        logger.warning("Priority classification failed: %s", exc)
        return {"priority": "MEDIUM", "reason": "Classification unavailable.", "action": "Review manually."}


def draft_reply(
    client: Anthropic,
    subject: str,
    sender: str,
    body_preview: str,
    context: str = "",
) -> str:
    """
    Use Claude to draft a professional email reply for a TAM at Truv.
    Returns the draft text (does NOT send).
    """
    system = """You are a Technical Account Manager at Truv.com, an income/employment verification
API company. Draft professional, concise email replies that:
- Acknowledge the customer's request immediately
- Provide clear next steps or answers
- Reference Truv documentation when relevant (docs.truv.com)
- Maintain a helpful, confident, technical tone
- Keep replies to 3-5 sentences unless more detail is genuinely needed
Do NOT include a subject line. Return only the email body."""

    user_prompt = f"""Draft a reply to this email:

Subject: {subject}
From: {sender}
Message: {body_preview}
{f"Additional context: {context}" if context else ""}"""

    response = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=512,
        thinking={"type": "adaptive"},
        system=system,
        messages=[{"role": "user", "content": user_prompt}],
    )
    return next((b.text for b in response.content if b.type == "text"), "")


def create_draft_reply(
    message_id: str,
    reply_body: str,
    user_id: str = "me",
) -> Optional[str]:
    """
    Save a draft reply to the message in Outlook (does NOT send).
    Returns the new draft message ID on success, None on failure.
    """
    try:
        data = graph_post(
            f"/users/{user_id}/messages/{message_id}/createReply",
            body={},
        )
        draft_id = data.get("id")
        if draft_id:
            graph_patch(
                f"/users/{user_id}/messages/{draft_id}",
                body={"body": {"contentType": "Text", "content": reply_body}},
            )
            logger.info("Draft reply created: %s", draft_id)
        return draft_id
    except Exception as exc:
        logger.error("Failed to create draft reply: %s", exc)
        return None


def flag_message(message_id: str, user_id: str = "me") -> bool:
    """Flag a message for follow-up."""
    try:
        graph_patch(
            f"/users/{user_id}/messages/{message_id}",
            body={"flag": {"flagStatus": "flagged"}},
        )
        return True
    except Exception as exc:
        logger.warning("Could not flag message %s: %s", message_id, exc)
        return False


def mark_as_read(message_id: str, user_id: str = "me") -> bool:
    """Mark a message as read."""
    try:
        graph_patch(
            f"/users/{user_id}/messages/{message_id}",
            body={"isRead": True},
        )
        return True
    except Exception as exc:
        logger.warning("Could not mark message %s as read: %s", message_id, exc)
        return False


def delete_message(message_id: str, user_id: str = "me") -> bool:
    """Permanently delete a message."""
    try:
        graph_delete(f"/users/{user_id}/messages/{message_id}")
        logger.info("Deleted message %s", message_id)
        return True
    except Exception as exc:
        logger.warning("Could not delete message %s: %s", message_id, exc)
        return False


def run_email_agent(
    client: Anthropic,
    top: int = 20,
    auto_draft: bool = False,
    auto_clean: bool = False,
) -> list[dict]:
    """
    Main email agent entrypoint. Fetches unread emails, classifies priority,
    optionally drafts replies for HIGH priority items, and optionally deletes
    SPAM/PHISHING when auto_clean=True.

    Returns a list of processed email summaries.
    """
    emails = fetch_unread_emails(top=top)
    if not emails:
        logger.info("No unread emails found.")
        return []

    results = []
    for email in emails:
        msg_id = email.get("id", "")
        subject = email.get("subject", "(no subject)")
        sender = email.get("from", {}).get("emailAddress", {}).get("address", "unknown")
        preview = email.get("bodyPreview", "")[:500]
        has_attachments = email.get("hasAttachments", False)

        classification = classify_email_priority(client, subject, sender, preview)
        priority = classification.get("priority", "MEDIUM")

        result = {
            "id": msg_id,
            "subject": subject,
            "from": sender,
            "received": email.get("receivedDateTime", ""),
            "priority": priority,
            "reason": classification.get("reason", ""),
            "action": classification.get("action", ""),
            "has_json_attachment": False,
            "draft_id": None,
            "deleted": False,
        }

        # Auto-delete SPAM and PHISHING
        if auto_clean and priority in ("SPAM", "PHISHING"):
            deleted = delete_message(msg_id)
            result["deleted"] = deleted
            if deleted:
                logger.info("[%s] DELETED: %s | %s", priority, subject, sender)
                results.append(result)
                continue

        # Check for JSON attachments (for the JSON agent)
        if has_attachments:
            json_att = get_json_attachment(msg_id)
            if json_att:
                result["has_json_attachment"] = True
                result["json_attachment_filename"] = json_att[0]
                result["json_attachment_data"] = json_att[1]

        # Draft reply for high-priority emails if requested
        if auto_draft and priority == "HIGH":
            draft_text = draft_reply(client, subject, sender, preview)
            draft_id = create_draft_reply(msg_id, draft_text)
            result["draft_id"] = draft_id
            result["draft_text"] = draft_text

        # Flag high-priority emails
        if priority == "HIGH":
            flag_message(msg_id)

        results.append(result)
        logger.info("[%s] %s | %s | %s", priority, subject, sender, classification.get("reason", ""))

    return results
