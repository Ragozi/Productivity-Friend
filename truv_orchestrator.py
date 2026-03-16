#!/usr/bin/env python3
"""
Productivity-Friend — Truv TAM Orchestrator
============================================
A modular, multi-agent AI productivity tool for Technical Account Managers at Truv.com.

Usage:
    python truv_orchestrator.py --scan-inbox              # Fetch & prioritize emails
    python truv_orchestrator.py --scan-inbox --auto-clean # Also delete spam/phishing
    python truv_orchestrator.py --scan-inbox --auto-draft # Also draft replies for HIGH emails
    python truv_orchestrator.py --daily-brief             # Calendar analysis + to-do list
    python truv_orchestrator.py --meeting-prep            # Prep briefs for upcoming meetings
    python truv_orchestrator.py --process-json <file>     # Process a local Truv JSON file
    python truv_orchestrator.py --full                    # Run all agents
    python truv_orchestrator.py --ask "question"          # Smart routing

JSON attachment pipeline (triggered automatically during --scan-inbox):
  When an email with a .json attachment is found:
  1. A folder is created in the project root named after the sender
  2. The raw JSON is saved there
  3. The JSON agent validates, fixes errors, and redacts PII
  4. The fixed JSON is saved to the same folder
  5. A draft reply email is prepared for the customer

Security notes:
  - PII is NEVER sent to Claude. Anonymization runs locally before any LLM call.
  - Microsoft Graph API uses OAuth2 client credentials (no user passwords stored).
  - All secrets live in .env (never committed to git).
  - PII mapping files live in data/pii_maps/ (also gitignored).
"""

import argparse
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from anthropic import Anthropic

# ---------------------------------------------------------------------------
# Bootstrap — load env before importing anything that reads env vars
# ---------------------------------------------------------------------------
load_dotenv()

from agents.email_agent       import run_email_agent
from agents.calendar_agent    import run_calendar_agent
from agents.json_agent        import process_truv_json
from agents.meeting_prep_agent import run_meeting_prep_agent

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
    level=getattr(logging, LOG_LEVEL, logging.INFO),
)
logger = logging.getLogger("orchestrator")

# Project root = directory containing this script
PROJECT_ROOT = Path(__file__).parent


# ---------------------------------------------------------------------------
# Claude client
# ---------------------------------------------------------------------------
def get_claude_client() -> Anthropic:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        logger.error(
            "ANTHROPIC_API_KEY not set. Copy .env.example to .env and add your key."
        )
        sys.exit(1)
    return Anthropic(api_key=api_key)


# ---------------------------------------------------------------------------
# Sender folder helpers
# ---------------------------------------------------------------------------
def sender_to_folder_name(sender_email: str) -> str:
    """Convert a sender email address to a safe directory name."""
    # Use the local part (before @) as the folder name
    name = sender_email.split("@")[0] if "@" in sender_email else sender_email
    # Strip characters that are invalid in directory names
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(". ")
    return name or "unknown_sender"


def get_sender_folder(sender_email: str) -> Path:
    """
    Return (and create) a folder in the project root named after the sender.
    e.g. sender john.doe@acme.com → <project_root>/john.doe/
    """
    folder = PROJECT_ROOT / sender_to_folder_name(sender_email)
    folder.mkdir(parents=True, exist_ok=True)
    return folder


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------
def section(title: str) -> None:
    width = 72
    print(f"\n{'=' * width}")
    print(f"  {title}")
    print(f"{'=' * width}")


def subsection(title: str) -> None:
    print(f"\n  ── {title}")


def print_email_results(results: list[dict]) -> None:
    section("EMAIL INBOX SCAN")
    if not results:
        print("  No unread emails found.")
        return

    high     = [r for r in results if r["priority"] == "HIGH"]
    med      = [r for r in results if r["priority"] == "MEDIUM"]
    low      = [r for r in results if r["priority"] == "LOW"]
    spam     = [r for r in results if r["priority"] == "SPAM"]
    phishing = [r for r in results if r["priority"] == "PHISHING"]

    total_cleaned = len([r for r in results if r.get("deleted")])

    print(f"  Scanned {len(results)} unread emails:")
    print(f"    🔴 HIGH     : {len(high)}")
    print(f"    🟡 MEDIUM   : {len(med)}")
    print(f"    🟢 LOW      : {len(low)}")
    if spam:
        deleted_count = len([r for r in spam if r.get("deleted")])
        print(f"    🗑  SPAM     : {len(spam)}"
              + (f"  ({deleted_count} deleted)" if deleted_count else ""))
    if phishing:
        deleted_count = len([r for r in phishing if r.get("deleted")])
        print(f"    ☠  PHISHING : {len(phishing)}"
              + (f"  ({deleted_count} deleted)" if deleted_count else ""))
    if total_cleaned:
        print(f"\n  ✓ Auto-cleaned {total_cleaned} spam/phishing email(s).")

    if high:
        subsection("HIGH PRIORITY (action required)")
        for r in high:
            print(f"    [{r['priority']}] {r['subject']}")
            print(f"         From: {r['from']}")
            print(f"         Why:  {r['reason']}")
            print(f"         Do:   {r['action']}")
            if r.get("has_json_attachment"):
                print(f"         📎 JSON attachment: {r.get('json_attachment_filename')}")
            if r.get("draft_id"):
                print(f"         ✉  Draft reply saved (ID: {r['draft_id']})")
            print()

    if med:
        subsection("MEDIUM PRIORITY")
        for r in med:
            print(f"    • {r['subject']} — {r['from']}")
            print(f"      {r['reason']}")

    if low:
        subsection("LOW PRIORITY")
        for r in low:
            print(f"    • {r['subject']}")

    if phishing and not all(r.get("deleted") for r in phishing):
        subsection("⚠  PHISHING (not deleted — run with --auto-clean to remove)")
        for r in phishing:
            if not r.get("deleted"):
                print(f"    ☠  {r['subject']} — {r['from']}")

    if spam and not all(r.get("deleted") for r in spam):
        subsection("SPAM (not deleted — run with --auto-clean to remove)")
        for r in spam:
            if not r.get("deleted"):
                print(f"    🗑  {r['subject']} — {r['from']}")


def print_calendar_results(result: dict) -> None:
    section("DAILY CALENDAR BRIEF")
    print(f"  Date: {result.get('date')}")
    print(f"  Events: {result.get('event_count', 0)}")

    events = result.get("events", [])
    if events:
        subsection("Today's Schedule")
        for evt in events[:10]:
            start = evt.get("start", "")[:16].replace("T", " ")
            print(f"    • [{start}] {evt.get('subject', '(no title)')}")

    conflicts = result.get("conflicts", [])
    if conflicts:
        subsection(f"⚠  CONFLICTS DETECTED ({len(conflicts)})")
        for c in conflicts:
            ea = c.get("event_a", {})
            eb = c.get("event_b", {})
            print(f"    • '{ea.get('subject')}' overlaps with '{eb.get('subject')}'")

    time_blocks = result.get("suggested_time_blocks", [])
    if time_blocks:
        subsection("Suggested Focus Blocks")
        for block in time_blocks:
            if isinstance(block, dict):
                print(f"    • {block.get('time', block.get('start', ''))} — {block.get('purpose', block)}")
            else:
                print(f"    • {block}")

    todos = result.get("todo_list", [])
    if todos:
        subsection("Today's To-Do List")
        for i, item in enumerate(todos, 1):
            print(f"    {i}. {item}")

    next_actions = result.get("next_actions", [])
    if next_actions:
        subsection("Next Actions")
        for action in next_actions:
            print(f"    → {action}")


def print_meeting_briefs(briefs: list[dict]) -> None:
    section("MEETING PREP BRIEFS")
    if not briefs:
        print("  No meetings found in the next 24 hours.")
        return

    for brief_data in briefs:
        subject = brief_data.get("subject", "(no title)")
        start = brief_data.get("start", "")
        brief = brief_data.get("brief", {})

        subsection(f"{subject}  [{start}]")

        context = brief.get("context", "")
        if context:
            print(f"    Context: {context}")

        talking_points = brief.get("talking_points", [])
        if talking_points:
            print("\n    Talking Points:")
            for pt in talking_points:
                print(f"      • {pt}")

        questions = brief.get("questions", [])
        if questions:
            print("\n    Questions to Ask:")
            for q in questions:
                print(f"      ? {q}")

        action_items = brief.get("action_items", [])
        if action_items:
            print("\n    Expected Follow-ups:")
            for a in action_items:
                print(f"      ✓ {a}")

        resources = brief.get("truv_resources", [])
        if resources:
            print("\n    Truv Resources:")
            for r in resources:
                print(f"      📖 {r}")
        print()


def print_json_results(result: dict) -> None:
    section("TRUV JSON PROCESSING REPORT")
    print(f"  File    : {result.get('filename')}")
    print(f"  Customer: {result.get('customer_email')}")
    print(f"  Session : {result.get('session_id')}")
    print()

    print(f"  {result.get('pii_summary', 'No PII detected.')}")

    errors = result.get("validation_errors", [])
    if errors:
        subsection(f"Validation Errors Found ({len(errors)})")
        for e in errors:
            print(f"    ✗ {e}")
    else:
        print("\n  ✓ JSON is valid against Truv schema.")

    if result.get("was_fixed"):
        subsection("Fixes Applied")
        print(f"    {result.get('diff_report', '')}")

    out_path = result.get("output_path")
    if out_path:
        print(f"\n  📁 Fixed JSON saved to:  {out_path}")

    draft_path = result.get("draft_path")
    if draft_path:
        print(f"  ✉  Draft email saved to: {draft_path}")

    draft = result.get("draft_email", "")
    if draft:
        subsection("Draft Customer Email Response")
        for line in draft.splitlines():
            print(f"    {line}")


def print_json_done_notification(result: dict, sender_folder: Path) -> None:
    """Print a clear completion notification after JSON processing."""
    width = 72
    print(f"\n{'─' * width}")
    print(f"  ✅  JSON PROCESSING COMPLETE")
    print(f"{'─' * width}")
    print(f"  Sender folder : {sender_folder}")
    print(f"  Fixed file    : {result.get('output_path')}")
    if result.get("was_fixed"):
        err_count = len(result.get("validation_errors", []))
        print(f"  Fixed errors  : {err_count} validation issue(s) resolved")
    else:
        print(f"  Status        : JSON was already valid — no changes needed")
    pii = result.get("pii_summary", "")
    if pii:
        print(f"  PII redacted  : {pii.splitlines()[0]}")
    print(f"  Draft reply   : ready (see report above)")
    print(f"{'─' * width}\n")


# ---------------------------------------------------------------------------
# Orchestrator routing — Claude classifies the overall task
# ---------------------------------------------------------------------------
ORCHESTRATOR_SYSTEM_PROMPT = """You are a productivity orchestrator for a TAM at Truv.com.
Given a user request or current context, determine which agents to run.

Available agents:
- email: Scan inbox, prioritize emails, draft replies
- calendar: Fetch today's calendar, detect conflicts, generate to-do list
- meeting_prep: Generate prep briefs for upcoming meetings
- json: Process a Truv API JSON file (detect PII, validate, fix, draft response)

Return ONLY a JSON array of agent names to run, in order. Example: ["email", "calendar"]"""


def route_with_claude(client: Anthropic, user_request: str) -> list[str]:
    """Ask Claude to decide which agents to invoke for a free-form request."""
    try:
        response = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=128,
            system=ORCHESTRATOR_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_request}],
        )
        text = next(
            (b.text for b in response.content if b.type == "text"), "[]"
        )
        text = text.strip().lstrip("```json").rstrip("```").strip()
        agents = json.loads(text)
        if isinstance(agents, list):
            return [a for a in agents if a in ("email", "calendar", "meeting_prep", "json")]
    except Exception as exc:
        logger.warning("Routing failed: %s", exc)
    return ["email", "calendar"]


# ---------------------------------------------------------------------------
# Main entrypoint
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Productivity-Friend — AI co-pilot for Truv TAMs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  python truv_orchestrator.py --scan-inbox
  python truv_orchestrator.py --scan-inbox --auto-clean
  python truv_orchestrator.py --scan-inbox --auto-draft
  python truv_orchestrator.py --daily-brief
  python truv_orchestrator.py --meeting-prep
  python truv_orchestrator.py --process-json customer_request.json --customer-email customer@example.com
  python truv_orchestrator.py --full
  python truv_orchestrator.py --ask "What should I focus on today?" """,
    )

    parser.add_argument(
        "--scan-inbox",
        action="store_true",
        help="Fetch and prioritize unread Outlook emails",
    )
    parser.add_argument(
        "--auto-draft",
        action="store_true",
        help="Automatically draft replies for HIGH priority emails (use with --scan-inbox)",
    )
    parser.add_argument(
        "--auto-clean",
        action="store_true",
        help="Automatically delete SPAM and PHISHING emails (use with --scan-inbox)",
    )
    parser.add_argument(
        "--daily-brief",
        action="store_true",
        help="Fetch calendar events and generate daily to-do list",
    )
    parser.add_argument(
        "--meeting-prep",
        action="store_true",
        help="Generate prep briefs for meetings in the next 24 hours",
    )
    parser.add_argument(
        "--process-json",
        metavar="FILE",
        help="Process a local Truv API JSON file (path to .json file)",
    )
    parser.add_argument(
        "--customer-email",
        metavar="EMAIL",
        default="customer@example.com",
        help="Customer email address (for --process-json reply drafting)",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Run all agents (inbox scan + daily brief + meeting prep)",
    )
    parser.add_argument(
        "--ask",
        metavar="QUESTION",
        help="Let the orchestrator decide which agents to run based on your request",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=20,
        help="Number of emails to fetch (default: 20)",
    )
    parser.add_argument(
        "--days-ahead",
        type=int,
        default=1,
        help="Days ahead for calendar scan (default: 1)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be done without making Graph API calls",
    )
    parser.add_argument(
        "--refresh-docs",
        action="store_true",
        help="Re-fetch and cache Truv API docs from docs.truv.com (run this periodically)",
    )
    parser.add_argument(
        "--version",
        action="version",
        version="Productivity-Friend v0.2.0",
    )

    args = parser.parse_args()

    # Show help if no args given
    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(0)

    if args.dry_run:
        print("DRY RUN MODE — no Graph API calls will be made.")
        print("Arguments parsed:", vars(args))
        sys.exit(0)

    if args.refresh_docs:
        from utils.truv_docs import refresh_all_docs
        section("REFRESHING TRUV API DOCS CACHE")
        print("  Fetching from docs.truv.com...\n")
        results = refresh_all_docs()
        ok = sum(1 for v in results.values() if v)
        print(f"\n  Done: {ok}/{len(results)} endpoints cached in data/truv_docs/")
        sys.exit(0)

    # Initialize Claude client
    client = get_claude_client()

    # Determine which agents to run
    run_email    = args.scan_inbox or args.full
    run_calendar = args.daily_brief or args.full
    run_meeting  = args.meeting_prep or args.full
    run_json     = bool(args.process_json)

    if args.ask:
        routed = route_with_claude(client, args.ask)
        logger.info("Orchestrator routing decision: %s", routed)
        run_email    = "email"        in routed
        run_calendar = "calendar"     in routed
        run_meeting  = "meeting_prep" in routed
        run_json     = "json"         in routed

    # ── Email Agent ──────────────────────────────────────────────────────────
    if run_email:
        try:
            email_results = run_email_agent(
                client,
                top=args.top,
                auto_draft=args.auto_draft,
                auto_clean=args.auto_clean,
            )
            print_email_results(email_results)

            # Hand off any JSON attachments to the JSON Agent
            json_emails = [r for r in email_results if r.get("has_json_attachment")]
            for r in json_emails:
                sender = r["from"]
                filename = r.get("json_attachment_filename", "attachment.json")
                raw_json = r["json_attachment_data"]

                logger.info(
                    "JSON attachment found in email from %s — starting JSON pipeline.", sender
                )

                # Create a folder named after the sender in the project root
                sender_folder = get_sender_folder(sender)

                # Save the raw attachment into the sender folder
                raw_path = sender_folder / filename
                raw_path.write_text(
                    __import__("json").dumps(raw_json, indent=2), encoding="utf-8"
                )
                logger.info("Raw attachment saved to %s", raw_path)

                # Run the full JSON processing pipeline, saving output to same folder
                json_result = process_truv_json(
                    client=client,
                    raw_json=raw_json,
                    filename=filename,
                    customer_email=sender,
                    output_dir=sender_folder,
                )
                print_json_results(json_result)
                print_json_done_notification(json_result, sender_folder)

        except Exception as exc:
            logger.error("Email agent failed: %s", exc, exc_info=True)

    # ── Calendar Agent ───────────────────────────────────────────────────────
    if run_calendar:
        try:
            calendar_result = run_calendar_agent(
                client, days_ahead=args.days_ahead
            )
            print_calendar_results(calendar_result)
        except Exception as exc:
            logger.error("Calendar agent failed: %s", exc, exc_info=True)

    # ── Meeting Prep Agent ───────────────────────────────────────────────────
    if run_meeting:
        try:
            meeting_briefs = run_meeting_prep_agent(client)
            print_meeting_briefs(meeting_briefs)
        except Exception as exc:
            logger.error("Meeting prep agent failed: %s", exc, exc_info=True)

    # ── JSON Agent (local file) ───────────────────────────────────────────────
    if run_json:
        json_path = Path(args.process_json)
        if not json_path.exists():
            logger.error("JSON file not found: %s", json_path)
            sys.exit(1)

        try:
            with open(json_path) as f:
                raw_json = json.load(f)
        except (json.JSONDecodeError, IOError) as exc:
            logger.error("Could not read JSON file: %s", exc)
            sys.exit(1)

        # For local file processing, save output next to the input file
        output_dir = json_path.parent

        try:
            json_result = process_truv_json(
                client=client,
                raw_json=raw_json,
                filename=json_path.name,
                customer_email=args.customer_email,
                output_dir=output_dir,
            )
            print_json_results(json_result)
            print_json_done_notification(json_result, output_dir)
        except Exception as exc:
            logger.error("JSON agent failed: %s", exc, exc_info=True)

    if not any([run_email, run_calendar, run_meeting, run_json]):
        print("No agents to run. Use --help to see available options.")
        sys.exit(1)


if __name__ == "__main__":
    main()
