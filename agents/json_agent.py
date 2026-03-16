"""
JSON Agent — Truv-specific JSON processing pipeline.

Pipeline:
1. Ingest raw JSON from customer email attachment
2. Detect & anonymize PII (locally, no LLM involved)
3. Validate anonymized JSON against the appropriate Truv API schema
4. If invalid: use Claude to fix the JSON (working only on anonymized data)
5. Generate a diff between original anonymized vs. fixed JSON
6. Save fixed JSON to data/outputs/
7. Draft an email response to the customer with explanations

Claude NEVER sees raw PII — only anonymized [REDACTED_*] placeholders.
"""

import json
import uuid
import logging
import os
from pathlib import Path
from typing import Optional
from deepdiff import DeepDiff
from anthropic import Anthropic

from utils.pii_handler import anonymize_json, deanonymize_json, summarize_pii_findings
from utils.truv_schemas import validate_truv_json, get_schema_for_endpoint
from utils.truv_docs import get_endpoint_docs

logger = logging.getLogger(__name__)

DEFAULT_OUTPUT_DIR = Path("data/outputs")
DEFAULT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

JSON_FIX_SYSTEM_PROMPT = """You are a Truv API integration expert. Your job is to fix malformed
JSON API request payloads so they conform to Truv's API schema.

Rules:
1. Do NOT modify any [REDACTED_*] placeholders — they are PII stand-ins
2. Fix schema errors: add missing required fields, correct data types, fix endpoint patterns
3. Ensure endpoint matches pattern ^/v1/.*$
4. Ensure payload is a proper JSON object with required fields
5. Return ONLY the fixed JSON object — no explanation, no markdown fences"""


def generate_diff_report(original: dict, fixed: dict) -> str:
    """
    Generate a human-readable diff report between original and fixed JSON.
    """
    diff = DeepDiff(original, fixed, verbose_level=2)
    if not diff:
        return "No changes required — JSON was already valid."

    lines = ["Changes made to fix the JSON:"]

    if "type_changes" in diff:
        for path, change in diff["type_changes"].items():
            lines.append(f"  • Type fix at {path}: {type(change['old_value']).__name__} → {type(change['new_value']).__name__}")

    if "values_changed" in diff:
        for path, change in diff["values_changed"].items():
            lines.append(f"  • Changed {path}: '{change['old_value']}' → '{change['new_value']}'")

    if "dictionary_item_added" in diff:
        for path in diff["dictionary_item_added"]:
            lines.append(f"  • Added field: {path}")

    if "dictionary_item_removed" in diff:
        for path in diff["dictionary_item_removed"]:
            lines.append(f"  • Removed field: {path}")

    if "iterable_item_added" in diff:
        for path in diff["iterable_item_added"]:
            lines.append(f"  • Added item: {path}")

    if "iterable_item_removed" in diff:
        for path in diff["iterable_item_removed"]:
            lines.append(f"  • Removed item: {path}")

    return "\n".join(lines)


def fix_json_with_claude(
    client: Anthropic,
    anon_json: dict,
    validation_errors: list[str],
    endpoint: str,
) -> Optional[dict]:
    """
    Ask Claude to fix the anonymized JSON based on schema validation errors.
    Returns a fixed JSON dict, or None if Claude couldn't fix it.
    """
    schema = get_schema_for_endpoint(endpoint)
    error_text = "\n".join(f"  - {e}" for e in validation_errors)

    # Fetch live Truv API docs for this endpoint (cached locally for 1 week)
    live_docs = get_endpoint_docs(endpoint)
    docs_section = (
        f"\nOFFICIAL TRUV API DOCUMENTATION FOR THIS ENDPOINT:\n{live_docs}\n"
        if live_docs else ""
    )

    prompt = f"""Fix this Truv API JSON payload to resolve these validation errors:

VALIDATION ERRORS:
{error_text}

CURRENT JSON (PII has been replaced with [REDACTED_*] placeholders):
{json.dumps(anon_json, indent=2)}

HARDCODED VALIDATION SCHEMA:
{json.dumps(schema, indent=2)}
{docs_section}
Return ONLY the corrected JSON object."""

    try:
        response = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=2048,
            thinking={"type": "adaptive"},
            system=JSON_FIX_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        text = next(
            (b.text for b in response.content if b.type == "text"), ""
        )
        # Strip any markdown code fences Claude may wrap around the JSON
        import re as _re
        text = _re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=_re.MULTILINE)
        text = _re.sub(r"\s*```$", "", text.strip(), flags=_re.MULTILINE)
        # Extract just the JSON object if there's surrounding text
        match = _re.search(r"\{[\s\S]*\}", text)
        if match:
            text = match.group(0)
        fixed = json.loads(text)
        logger.info("Claude successfully fixed the JSON.")
        return fixed
    except json.JSONDecodeError as exc:
        logger.error("Claude returned invalid JSON: %s", exc)
        return None
    except Exception as exc:
        logger.error("JSON fix request failed: %s", exc)
        return None


def draft_json_response_email(
    client: Anthropic,
    customer_email: str,
    filename: str,
    pii_summary: str,
    validation_errors: list[str],
    diff_report: str,
    was_fixed: bool,
) -> str:
    """
    Draft a professional email to send back to the customer with the fixed JSON.
    """
    system = """You are a Technical Account Manager at Truv.com responding to a customer
who sent a JSON integration file. Write a professional, helpful email that:
- Thanks them for their submission
- Briefly explains what PII was detected and scrubbed (for their awareness)
- Lists the validation issues found (if any)
- Describes the fixes made (if any)
- Attaches the fixed JSON file (mention it's attached)
- Offers to hop on a quick call if they need help
Keep it concise — under 200 words. Return only the email body."""

    status = "fixed and attached" if was_fixed else "reviewed (no changes needed)"
    errors_text = "\n".join(f"  - {e}" for e in validation_errors) if validation_errors else "None — the JSON was already valid."

    prompt = f"""Draft a reply email for customer: {customer_email}
File reviewed: {filename}
Status: {status}

PII detected: {pii_summary}

Validation errors found:
{errors_text}

Changes made:
{diff_report}"""

    try:
        response = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=512,
            thinking={"type": "adaptive"},
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        return next((b.text for b in response.content if b.type == "text"), "")
    except Exception as exc:
        logger.error("Draft email generation failed: %s", exc)
        return (
            f"Hi,\n\nThank you for sending {filename}. "
            f"We have reviewed it and {'fixed validation issues. ' if was_fixed else 'it looks good. '}"
            "Please find the processed file attached.\n\nBest regards,\nTruv TAM Team"
        )


def save_json_output(data: dict, filename: str, output_dir: Optional[Path] = None) -> Path:
    """Save processed JSON to the specified directory. Returns the saved path."""
    target_dir = output_dir or DEFAULT_OUTPUT_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(filename).stem
    out_path = target_dir / f"{stem}_fixed.json"
    with open(out_path, "w") as f:
        json.dump(data, f, indent=2)
    logger.info("Saved fixed JSON to %s", out_path)
    return out_path


def save_draft_email(draft: str, filename: str) -> Path:
    """Save the draft email text to data/outputs/ for review before sending."""
    stem = Path(filename).stem
    out_path = OUTPUT_DIR / f"{stem}_draft_reply.txt"
    with open(out_path, "w") as f:
        f.write(draft)
    logger.info("Draft email saved to %s", out_path)
    return out_path


def process_truv_json(
    client: Anthropic,
    raw_json: dict,
    filename: str,
    customer_email: str,
    session_id: Optional[str] = None,
    output_dir: Optional[Path] = None,
) -> dict:
    """
    Full Truv JSON processing pipeline.

    Returns a result dict with keys:
    - session_id: str
    - pii_summary: str
    - validation_errors: list[str] (on anonymized data)
    - was_fixed: bool
    - diff_report: str
    - draft_email: str
    - output_path: str (path to saved fixed JSON)
    - anon_json: dict (the anonymized + possibly fixed JSON)
    """
    session_id = session_id or str(uuid.uuid4())[:8]
    logger.info("Processing JSON: %s (session=%s)", filename, session_id)

    # Step 1: Anonymize PII (local, no LLM)
    anon_json, pii_mapping = anonymize_json(raw_json, session_id)
    pii_summary = summarize_pii_findings(pii_mapping)
    logger.info("PII step complete. %s", pii_summary.splitlines()[0])

    # Step 2: Validate against Truv schema
    validation_errors = validate_truv_json(anon_json)
    if validation_errors:
        logger.warning("Validation errors (%d): %s", len(validation_errors), validation_errors[0])
    else:
        logger.info("JSON is valid against Truv schema.")

    # Step 3: Fix with Claude if invalid
    fixed_json = anon_json
    was_fixed = False
    if validation_errors:
        endpoint = anon_json.get("endpoint", "")
        fixed = fix_json_with_claude(client, anon_json, validation_errors, endpoint)
        if fixed:
            # Re-validate the fix
            remaining_errors = validate_truv_json(fixed)
            if not remaining_errors:
                fixed_json = fixed
                was_fixed = True
                logger.info("JSON fixed successfully.")
            else:
                logger.warning("Claude's fix still has errors: %s", remaining_errors)
                fixed_json = fixed  # Use best-effort fix anyway

    # Step 4: Generate diff report
    diff_report = generate_diff_report(anon_json, fixed_json)

    # Step 5: Save output
    output_path = save_json_output(fixed_json, filename, output_dir=output_dir)

    # Step 6: Draft customer email response and save to file
    draft_email = draft_json_response_email(
        client, customer_email, filename, pii_summary,
        validation_errors, diff_report, was_fixed,
    )
    draft_path = save_draft_email(draft_email, filename)

    return {
        "session_id": session_id,
        "filename": filename,
        "customer_email": customer_email,
        "pii_summary": pii_summary,
        "validation_errors": validation_errors,
        "was_fixed": was_fixed,
        "diff_report": diff_report,
        "draft_email": draft_email,
        "output_path": str(output_path),
        "draft_path": str(draft_path),
        "anon_json": fixed_json,
    }
