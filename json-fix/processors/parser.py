"""
JSON parser and document-type detector.
Loads JSON files and figures out what kind of Truv payload they should become.
"""

import json


def load_json(file_content: bytes) -> tuple:
    """
    Parse raw bytes as JSON.
    Returns (data, error) — one will be None.
    """
    try:
        text = file_content.decode("utf-8-sig")  # Handle BOM
        data = json.loads(text)
        return data, None
    except json.JSONDecodeError as e:
        return None, {
            "type": "json_syntax_error",
            "message": str(e),
            "line": e.lineno,
            "column": e.colno,
            "position": e.pos,
        }
    except Exception as e:
        return None, {"type": "parse_error", "message": str(e)}


def normalize_key(k: str) -> str:
    return k.lower().strip().replace("-", "_").replace(" ", "_")


def detect_document_type(data: dict) -> dict:
    """
    Heuristic detection of what Truv payload type this JSON represents.
    Returns:
    {
        "type": "user_create" | "bridge_token" | "employment_report" | "unknown",
        "confidence": float,
        "reason": str,
    }
    """
    if not isinstance(data, dict):
        # Could be a list of records
        if isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict):
            return {
                "type": "bulk_records",
                "confidence": 70.0,
                "reason": "Top-level JSON is an array — treating as bulk user/employment records.",
            }
        return {"type": "unknown", "confidence": 0.0, "reason": "Not a JSON object or array."}

    keys = {normalize_key(k) for k in data.keys()}
    score = {}

    # --- User creation signals ---
    user_create_signals = {
        "external_user_id", "first_name", "last_name", "email", "phone", "ssn",
        "firstname", "lastname", "fname", "lname", "given_name", "surname",
    }
    user_score = len(keys & user_create_signals)
    if user_score > 0:
        score["user_create"] = user_score * 20

    # --- Bridge token signals ---
    bridge_signals = {"product_type", "tracking_info", "bridge_token", "account"}
    bridge_score = len(keys & bridge_signals)
    if bridge_score > 0:
        score["bridge_token"] = bridge_score * 25

    # --- Employment report signals ---
    report_signals = {
        "employments", "profile", "statements", "company", "income",
        "annual_income_summary", "w2s", "bank_accounts",
    }
    report_score = len(keys & report_signals)
    if report_score > 0:
        score["employment_report"] = report_score * 20

    # Nested structure detection
    if "profile" in keys and isinstance(data.get("profile"), dict):
        score["employment_report"] = score.get("employment_report", 0) + 30
    if "employments" in keys and isinstance(data.get("employments"), list):
        score["employment_report"] = score.get("employment_report", 0) + 40
    if "statements" in keys and isinstance(data.get("statements"), list):
        score["employment_report"] = score.get("employment_report", 0) + 20

    if not score:
        return {
            "type": "unknown",
            "confidence": 0.0,
            "reason": "No recognizable Truv fields found. Please select document type manually.",
        }

    best_type = max(score, key=score.get)
    best_score = score[best_type]
    total = sum(score.values())
    confidence = min(100.0, (best_score / max(total, 1)) * 100 + (best_score / 2))

    reasons = {
        "user_create": "Found identity fields (name, email, SSN) at the root level.",
        "bridge_token": "Found bridge/product token fields.",
        "employment_report": "Found employment/income/company/profile structure.",
        "unknown": "Could not determine document type.",
    }

    return {
        "type": best_type,
        "confidence": round(confidence, 1),
        "reason": reasons.get(best_type, ""),
        "all_scores": score,
    }


def flatten_for_mapping(data: dict) -> dict:
    """
    Flatten one level of nesting to help the mapper handle nested objects.
    Nested keys are prefixed with their parent key.
    e.g. {"profile": {"first_name": "John"}} → {"profile.first_name": "John", "profile": {...}}
    """
    flat = {}
    for key, value in data.items():
        flat[key] = value
        if isinstance(value, dict):
            for sub_key, sub_value in value.items():
                flat[f"{key}.{sub_key}"] = sub_value
    return flat
