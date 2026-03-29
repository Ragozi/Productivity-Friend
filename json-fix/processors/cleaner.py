"""
Orchestration layer: parse → map → validate → build output.
"""

import json
import uuid
from datetime import datetime

from processors.parser import load_json, detect_document_type, flatten_for_mapping
from processors.mapper import map_all_fields
from processors.validator import validate_and_clean
from processors.api_builder import build_full_output


def process_file(file_content: bytes, filename: str) -> dict:
    """
    Full processing pipeline for a single uploaded JSON file.

    Returns a session-ready analysis dict:
    {
        "file_id": str,
        "filename": str,
        "status": "ready" | "needs_input" | "critical" | "error",
        "doc_type": str,
        "doc_type_confidence": float,
        "doc_type_reason": str,
        "mapping": {canonical: {original_key, value, confidence, method}},
        "unmapped": {customer_key: value},
        "issues": [{field, severity, message}],
        "auto_fixes": [{field, original, fixed, note}],
        "cleaned": {canonical: value},
        "original_data": dict,
        "critical_count": int,
        "warning_count": int,
        "error": str | None,
    }
    """
    file_id = str(uuid.uuid4())

    # Step 1: Parse JSON
    data, parse_error = load_json(file_content)
    if parse_error:
        return {
            "file_id": file_id,
            "filename": filename,
            "status": "error",
            "error": parse_error,
            "doc_type": None,
            "issues": [],
            "mapping": {},
            "unmapped": {},
            "cleaned": {},
            "original_data": None,
            "critical_count": 0,
            "warning_count": 0,
        }

    # Handle array input (bulk records) — process first item for analysis
    original_data = data
    if isinstance(data, list):
        working_data = data[0] if data else {}
    else:
        working_data = data

    # Step 2: Detect document type
    detection = detect_document_type(working_data)
    doc_type = detection["type"]

    # Step 3: Flatten and map fields
    flat = flatten_for_mapping(working_data)
    mapping_result = map_all_fields(flat)
    mapped = mapping_result["mapped"]
    unmapped = mapping_result["unmapped"]

    # Step 4: Validate and clean
    validation_result = validate_and_clean(mapped, doc_type)
    cleaned = validation_result["cleaned"]
    issues = validation_result["issues"]
    auto_fixes = validation_result["auto_fixes"]

    # Determine status
    critical_issues = [i for i in issues if i["severity"] == "CRITICAL"]
    warning_issues = [i for i in issues if i["severity"] == "WARNING"]

    if critical_issues:
        status = "critical"
    elif warning_issues:
        status = "needs_input"
    else:
        status = "ready"

    return {
        "file_id": file_id,
        "filename": filename,
        "status": status,
        "doc_type": doc_type,
        "doc_type_confidence": detection.get("confidence", 0.0),
        "doc_type_reason": detection.get("reason", ""),
        "mapping": mapped,
        "unmapped": unmapped,
        "issues": issues,
        "auto_fixes": auto_fixes,
        "cleaned": cleaned,
        "original_data": original_data,
        "critical_count": len(critical_issues),
        "warning_count": len(warning_issues),
        "error": None,
    }


def generate_output(session_data: dict, user_overrides: dict, doc_type_override: str = None) -> tuple:
    """
    Generate the final Truv API-ready JSON from session data + user-provided overrides.

    Returns (output_json_str, audit_json_str).
    """
    doc_type = doc_type_override or session_data.get("doc_type", "employment_report")
    cleaned = session_data.get("cleaned", {})
    original_data = session_data.get("original_data", {})

    output = build_full_output(doc_type, cleaned, original_data, user_overrides)

    # Build audit log
    audit = {
        "json_fix_version": "1.0.0",
        "processed_at": datetime.utcnow().isoformat() + "Z",
        "original_filename": session_data.get("filename"),
        "document_type_detected": doc_type,
        "document_type_confidence": session_data.get("doc_type_confidence"),
        "field_mapping": {
            canonical: {
                "original_field_name": info.get("original_key"),
                "confidence": info.get("confidence"),
                "method": info.get("method"),
            }
            for canonical, info in session_data.get("mapping", {}).items()
        },
        "unmapped_customer_fields": list(session_data.get("unmapped", {}).keys()),
        "auto_fixes_applied": session_data.get("auto_fixes", []),
        "user_provided_fields": list(user_overrides.keys()),
        "issues_at_time_of_processing": session_data.get("issues", []),
    }

    return (
        json.dumps(output, indent=2),
        json.dumps(audit, indent=2),
    )
