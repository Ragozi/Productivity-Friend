#!/usr/bin/env python3
"""
Productivity-Friend — FastAPI HTTP Server
=========================================
Exposes the TAM productivity agents over HTTP so that:
  1. TruvBrain (Next.js dashboard) can fetch live data for the embedded panel.
  2. n8n (self-hosted on Beelink) can hand off JSON attachments and trigger agents.

Start the server:
    uvicorn api_server:app --host 0.0.0.0 --port 8000 --reload

TruvBrain connects to:   http://localhost:8000  (or PRODUCTIVITY_FRIEND_API_URL)
n8n webhook receiver:    http://<your-ip>:8000/n8n/webhook
n8n trigger endpoint:    http://<your-ip>:8000/n8n/trigger

Security note:
  Set API_SERVER_SECRET in .env to require a Bearer token on all routes.
  Leave blank during local development for convenience.
"""

import hashlib
import hmac
import json
import logging
import os
import time
from collections import deque
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, HTTPException, Request, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from anthropic import Anthropic

from agents.email_agent import run_email_agent
from agents.calendar_agent import run_calendar_agent
from agents.json_agent import process_truv_json
from agents.meeting_prep_agent import run_meeting_prep_agent
from utils.truv_schemas import validate_truv_json, verify_webhook_signature

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
)
logger = logging.getLogger("api_server")

# ---------------------------------------------------------------------------
# In-memory activity log (last 200 events, shown in dashboard)
# ---------------------------------------------------------------------------
_activity: deque = deque(maxlen=200)


def log_activity(event_type: str, message: str, detail: str = "") -> None:
    entry = {
        "ts": time.strftime("%H:%M:%S"),
        "type": event_type,   # "email" | "json" | "webhook" | "calendar" | "n8n" | "error"
        "message": message,
        "detail": detail,
    }
    _activity.appendleft(entry)
    logger.info("[%s] %s %s", event_type.upper(), message, detail)


# ---------------------------------------------------------------------------
# App + CORS
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Productivity-Friend API",
    description="TAM productivity agents for TruvBrain dashboard + n8n integration",
    version="1.0.0",
)

# Allow Next.js dev (localhost:3000) and your Vercel deployment
_allowed_origins = [
    "http://localhost:3000",
    "http://localhost:3001",
    "https://*.vercel.app",
]
extra_origin = os.getenv("TRUV_BRAIN_ORIGIN", "")
if extra_origin:
    _allowed_origins.append(extra_origin)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Optional Bearer-token auth (set API_SERVER_SECRET in .env to enable)
# ---------------------------------------------------------------------------
_SERVER_SECRET = os.getenv("API_SERVER_SECRET", "")


def _check_auth(authorization: Optional[str] = Header(default=None)) -> None:
    if not _SERVER_SECRET:
        return  # No secret configured → open access (dev mode)
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")
    if authorization[7:] != _SERVER_SECRET:
        raise HTTPException(status_code=403, detail="Invalid API token")


# ---------------------------------------------------------------------------
# Claude client helper
# ---------------------------------------------------------------------------
def _get_client() -> Anthropic:
    key = os.getenv("ANTHROPIC_API_KEY", "")
    if not key:
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY not set in .env")
    return Anthropic(api_key=key)


# ---------------------------------------------------------------------------
# Output dir for JSON processing
# ---------------------------------------------------------------------------
_OUTPUT_DIR = Path("data/outputs")
_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class ScanInboxRequest(BaseModel):
    top: int = 20
    auto_draft: bool = False
    auto_clean: bool = False


class ProcessJsonRequest(BaseModel):
    json_data: dict[str, Any]
    filename: str = "customer_request.json"
    customer_email: str = "customer@example.com"
    session_id: Optional[str] = None


class N8nWebhookPayload(BaseModel):
    """
    Schema for events that n8n sends to this orchestrator.

    n8n HTTP Request node should POST to /n8n/webhook with this body.
    """
    event_type: str          # "email_received" | "json_attachment" | "manual_trigger"
    sender: Optional[str] = None
    attachment_filename: Optional[str] = None
    attachment_data: Optional[dict] = None
    metadata: Optional[dict] = None


class N8nTriggerRequest(BaseModel):
    """
    Request body for triggering an n8n workflow from this orchestrator.
    """
    workflow_id: str
    payload: Optional[dict] = None


# ---------------------------------------------------------------------------
# Routes — Health & Status
# ---------------------------------------------------------------------------

@app.get("/api/status", tags=["Health"])
def get_status(_: None = Depends(_check_auth)):
    """
    Health check. Returns env var availability and recent activity count.
    TruvBrain polls this every 30 s to show the connection indicator.
    """
    return {
        "status": "ok",
        "version": "1.0.0",
        "anthropic_key_set": bool(os.getenv("ANTHROPIC_API_KEY")),
        "microsoft_graph_set": bool(os.getenv("CLIENT_ID")),
        "n8n_url_set": bool(os.getenv("N8N_BASE_URL")),
        "truv_client_id_set": bool(os.getenv("TRUV_CLIENT_ID")),
        "activity_count": len(_activity),
    }


@app.get("/api/activity", tags=["Health"])
def get_activity(limit: int = 50, _: None = Depends(_check_auth)):
    """Return the most recent activity log entries (for the dashboard live log panel)."""
    return {"activity": list(_activity)[:limit]}


# ---------------------------------------------------------------------------
# Routes — Email Agent
# ---------------------------------------------------------------------------

@app.post("/api/scan-inbox", tags=["Email"])
def scan_inbox(req: ScanInboxRequest, _: None = Depends(_check_auth)):
    """
    Run the email agent: fetch unread Outlook emails and classify priority.

    Returns a list of email summaries (HIGH / MEDIUM / LOW / SPAM / PHISHING),
    suitable for rendering in the dashboard's email queue panel.
    """
    client = _get_client()
    try:
        results = run_email_agent(
            client,
            top=req.top,
            auto_draft=req.auto_draft,
            auto_clean=req.auto_clean,
        )
        # Strip large binary attachment data before returning to dashboard
        for r in results:
            r.pop("json_attachment_data", None)

        high   = sum(1 for r in results if r.get("priority") == "HIGH")
        medium = sum(1 for r in results if r.get("priority") == "MEDIUM")
        low    = sum(1 for r in results if r.get("priority") == "LOW")
        spam   = sum(1 for r in results if r.get("priority") in ("SPAM", "PHISHING"))

        log_activity(
            "email",
            f"Scanned {len(results)} emails",
            f"HIGH:{high} MED:{medium} LOW:{low} SPAM:{spam}",
        )
        return {
            "emails": results,
            "count": len(results),
            "summary": {"high": high, "medium": medium, "low": low, "spam": spam},
        }
    except Exception as exc:
        log_activity("error", "scan-inbox failed", str(exc))
        logger.error("scan-inbox failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# Routes — Calendar Agent
# ---------------------------------------------------------------------------

@app.get("/api/daily-brief", tags=["Calendar"])
def daily_brief(days_ahead: int = 1, _: None = Depends(_check_auth)):
    """
    Run the calendar agent: fetch Outlook events, detect conflicts,
    and return a structured daily brief with suggested focus blocks and to-dos.
    """
    client = _get_client()
    try:
        result = run_calendar_agent(client, days_ahead=days_ahead)
        log_activity("calendar", f"Daily brief fetched", f"{result.get('event_count', 0)} events")
        return result
    except Exception as exc:
        log_activity("error", "daily-brief failed", str(exc))
        logger.error("daily-brief failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# Routes — Meeting Prep Agent
# ---------------------------------------------------------------------------

@app.get("/api/meeting-prep", tags=["Calendar"])
def meeting_prep(hours_ahead: int = 24, _: None = Depends(_check_auth)):
    """
    Run the meeting prep agent: generate prep briefs for upcoming meetings.
    Returns an array of meeting brief objects with talking points, questions, and resources.
    """
    client = _get_client()
    try:
        briefs = run_meeting_prep_agent(client, hours_ahead=hours_ahead)
        log_activity("calendar", f"Meeting prep complete", f"{len(briefs)} briefs generated")
        return {"briefs": briefs, "count": len(briefs)}
    except Exception as exc:
        log_activity("error", "meeting-prep failed", str(exc))
        logger.error("meeting-prep failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# Routes — JSON Agent
# ---------------------------------------------------------------------------

@app.post("/api/process-json", tags=["JSON"])
def process_json(req: ProcessJsonRequest, _: None = Depends(_check_auth)):
    """
    Run the full JSON processing pipeline:
      1. Anonymise PII locally (never sent to Claude)
      2. Validate against Truv API schema
      3. Auto-fix errors with Claude (working only on anonymised data)
      4. Generate diff report
      5. Draft a customer reply email

    Returns the processing report. The fixed JSON is also saved to data/outputs/.
    """
    client = _get_client()
    try:
        result = process_truv_json(
            client=client,
            raw_json=req.json_data,
            filename=req.filename,
            customer_email=req.customer_email,
            session_id=req.session_id,
            output_dir=_OUTPUT_DIR,
        )
        error_count = len(result.get("validation_errors", []))
        log_activity(
            "json",
            f"Processed {req.filename}",
            f"{'Fixed ' + str(error_count) + ' error(s)' if result.get('was_fixed') else 'No errors found'}",
        )
        return result
    except Exception as exc:
        log_activity("error", f"process-json failed for {req.filename}", str(exc))
        logger.error("process-json failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/validate-json", tags=["JSON"])
def validate_json_only(body: dict[str, Any], _: None = Depends(_check_auth)):
    """
    Fast schema validation without AI processing.
    Returns validation errors immediately — no LLM call, no PII handling.
    Useful for the dashboard's real-time JSON inspector.
    """
    errors = validate_truv_json(body)
    return {
        "valid": len(errors) == 0,
        "error_count": len(errors),
        "errors": errors,
    }


# ---------------------------------------------------------------------------
# Routes — n8n Integration
# ---------------------------------------------------------------------------

@app.post("/n8n/webhook", tags=["n8n"])
async def n8n_webhook(request: Request):
    """
    Receive events from n8n workflows running on the Beelink mini PC.

    n8n sends a POST here when it detects relevant triggers (e.g. new email
    with JSON attachment, manual run, scheduled check).

    The X-N8N-SECRET header is validated against N8N_WEBHOOK_SECRET in .env.
    """
    # Validate n8n webhook secret
    n8n_secret = os.getenv("N8N_WEBHOOK_SECRET", "")
    if n8n_secret:
        received = request.headers.get("X-N8N-SECRET", "")
        if not hmac.compare_digest(received, n8n_secret):
            logger.warning("n8n webhook received with invalid secret")
            raise HTTPException(status_code=403, detail="Invalid n8n webhook secret")

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Request body must be valid JSON")

    event_type = payload.get("event_type", "unknown")
    sender = payload.get("sender", "")
    filename = payload.get("attachment_filename", "")
    attachment_data = payload.get("attachment_data")

    log_activity("n8n", f"Webhook received: {event_type}", f"from={sender or 'n8n'}")

    response_data: dict = {"received": True, "event_type": event_type}

    # ── JSON attachment from email ──────────────────────────────────────────
    if event_type == "json_attachment" and attachment_data and isinstance(attachment_data, dict):
        client = _get_client()
        try:
            result = process_truv_json(
                client=client,
                raw_json=attachment_data,
                filename=filename or "attachment.json",
                customer_email=sender or "customer@example.com",
                output_dir=_OUTPUT_DIR,
            )
            log_activity(
                "json",
                f"n8n pipeline: processed {filename}",
                f"errors={len(result.get('validation_errors', []))} fixed={result.get('was_fixed')}",
            )
            response_data["json_result"] = {
                "was_fixed": result.get("was_fixed"),
                "error_count": len(result.get("validation_errors", [])),
                "output_path": result.get("output_path"),
                "draft_path": result.get("draft_path"),
            }
        except Exception as exc:
            log_activity("error", f"n8n JSON pipeline failed for {filename}", str(exc))
            response_data["error"] = str(exc)

    # ── Email scan trigger from n8n ─────────────────────────────────────────
    elif event_type == "scan_inbox":
        client = _get_client()
        try:
            emails = run_email_agent(client, top=payload.get("top", 20))
            for e in emails:
                e.pop("json_attachment_data", None)
            log_activity("email", f"n8n triggered inbox scan", f"{len(emails)} emails processed")
            response_data["email_count"] = len(emails)
        except Exception as exc:
            log_activity("error", "n8n inbox scan failed", str(exc))
            response_data["error"] = str(exc)

    # ── Truv webhook verification event from n8n ────────────────────────────
    elif event_type == "truv_webhook":
        # n8n forwarded a Truv webhook event for logging
        truv_event = payload.get("truv_event", {})
        event_name = truv_event.get("event_type", "unknown")
        log_activity("webhook", f"Truv event: {event_name}", json.dumps(truv_event)[:120])
        response_data["logged"] = True

    return response_data


@app.post("/n8n/trigger", tags=["n8n"])
def trigger_n8n_workflow(req: N8nTriggerRequest, _: None = Depends(_check_auth)):
    """
    Trigger an n8n workflow from this orchestrator.

    n8n must have a Webhook trigger node listening at:
    http://<beelink-ip>:5678/webhook/<workflow_id>

    Set N8N_BASE_URL in .env to your Beelink's n8n URL.
    """
    import requests as _requests

    n8n_base = os.getenv("N8N_BASE_URL", "").rstrip("/")
    if not n8n_base:
        raise HTTPException(
            status_code=503,
            detail="N8N_BASE_URL not set in .env. Point it to your Beelink n8n instance.",
        )

    trigger_url = f"{n8n_base}/webhook/{req.workflow_id}"
    try:
        resp = _requests.post(
            trigger_url,
            json=req.payload or {},
            timeout=10,
            headers={"Content-Type": "application/json"},
        )
        resp.raise_for_status()
        log_activity("n8n", f"Triggered workflow {req.workflow_id}", f"status={resp.status_code}")
        return {"triggered": True, "workflow_id": req.workflow_id, "status": resp.status_code}
    except Exception as exc:
        log_activity("error", f"n8n trigger failed for {req.workflow_id}", str(exc))
        raise HTTPException(status_code=502, detail=f"n8n trigger failed: {exc}")


# ---------------------------------------------------------------------------
# Routes — Truv Webhook Receiver (customers point their webhooks here for testing)
# ---------------------------------------------------------------------------

@app.post("/truv/webhook", tags=["Truv"])
async def receive_truv_webhook(request: Request):
    """
    Receive and verify incoming Truv webhook events.

    Customers can point their Truv webhook_url to this endpoint during testing.
    The signature in X-WEBHOOK-SIGN is verified using TRUV_ACCESS_SECRET.

    Verified events are logged to the activity feed and forwarded to n8n if configured.
    """
    raw_body = await request.body()
    signature = request.headers.get("X-WEBHOOK-SIGN", "")
    access_secret = os.getenv("TRUV_ACCESS_SECRET", "")

    # Verify signature if secret is configured
    if access_secret and signature:
        if not verify_webhook_signature(raw_body, signature, access_secret):
            logger.warning("Truv webhook received with invalid HMAC signature")
            raise HTTPException(status_code=401, detail="Invalid webhook signature")
    elif access_secret and not signature:
        raise HTTPException(status_code=400, detail="X-WEBHOOK-SIGN header missing")

    try:
        event = json.loads(raw_body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Webhook body is not valid JSON")

    event_type = event.get("event_type", "unknown")
    task_id = event.get("task_id", "")
    status = event.get("status", "")

    log_activity(
        "webhook",
        f"Truv webhook: {event_type}",
        f"task_id={task_id} status={status}",
    )

    # Optionally forward to n8n for further automation
    n8n_base = os.getenv("N8N_BASE_URL", "").rstrip("/")
    n8n_workflow_id = os.getenv("N8N_TRUV_WEBHOOK_WORKFLOW_ID", "")
    if n8n_base and n8n_workflow_id:
        try:
            import requests as _requests
            _requests.post(
                f"{n8n_base}/webhook/{n8n_workflow_id}",
                json={"event_type": "truv_webhook", "truv_event": event},
                timeout=5,
            )
        except Exception as exc:
            logger.warning("Could not forward Truv webhook to n8n: %s", exc)

    return {"received": True, "event_type": event_type}


# ---------------------------------------------------------------------------
# Run directly (dev mode)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("API_SERVER_PORT", "8000"))
    print(f"\n  Productivity-Friend API starting on http://0.0.0.0:{port}")
    print(f"  Docs: http://localhost:{port}/docs\n")
    uvicorn.run("api_server:app", host="0.0.0.0", port=port, reload=True)
