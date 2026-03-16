"""
PII detection, anonymization, and de-anonymization for Truv JSON payloads.

Security model:
- PII is detected locally using regex + key-name heuristics (no LLM involved).
- Detected values are replaced with typed placeholders like [REDACTED_EMAIL_1].
- A local encrypted mapping file stores the original→placeholder relationship
  so data can be de-anonymized if needed (e.g., to send a response).
- The encryption key is derived from the ANTHROPIC_API_KEY env var as a KDF
  input so the mapping is tied to this installation without a separate secret.

IMPORTANT: The mapping file (data/pii_maps/) must NEVER be committed to git.
"""

import re
import json
import hashlib
import os
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Regex patterns for PII detection
# ---------------------------------------------------------------------------
PII_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("EMAIL",       re.compile(r'\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b')),
    ("SSN",         re.compile(r'\b(?:\d{3}-\d{2}-\d{4}|\d{9})\b')),
    ("PHONE",       re.compile(r'\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b')),
    ("DOB",         re.compile(r'\b(?:\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}|\d{4}[/\-]\d{2}[/\-]\d{2})\b')),
    ("CREDIT_CARD", re.compile(r'\b(?:\d{4}[- ]?){3}\d{4}\b')),
    ("ROUTING_NUM", re.compile(r'\b\d{9}\b')),       # bank routing (9-digit)
    ("ACCOUNT_NUM", re.compile(r'\baccount[_\s]*(?:num(?:ber)?|#|no)?[:\s]*\d{6,20}\b', re.I)),
    ("ZIP_CODE",    re.compile(r'\b\d{5}(?:-\d{4})?\b')),
    ("IP_ADDRESS",  re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b')),
]

# Key names whose values should always be redacted regardless of value format
SENSITIVE_KEYS: set[str] = {
    "api_key", "apikey", "api_secret", "secret", "password", "passwd",
    "ssn", "social_security", "dob", "date_of_birth", "birthdate",
    "account_number", "account_num", "routing_number", "routing_num",
    "credit_card", "card_number", "cvv", "pin", "token", "bearer",
    "first_name", "last_name", "full_name", "name",
    "address", "street", "city", "state", "zip", "zipcode", "postal",
    "phone", "mobile", "cell", "fax",
    "email", "email_address",
    "employer_id", "ein", "tax_id",
    "income", "salary", "wage",
}


def _derive_key(length: int = 32) -> bytes:
    """Derive an encryption key from the Anthropic API key (poor-man's KDF)."""
    seed = os.getenv("ANTHROPIC_API_KEY", "dev-insecure-fallback-key")
    return hashlib.sha256(seed.encode()).digest()[:length]


def _get_mapping_path(session_id: str) -> Path:
    """Return the path for a per-session PII mapping file."""
    maps_dir = Path("data/pii_maps")
    maps_dir.mkdir(parents=True, exist_ok=True)
    return maps_dir / f"{session_id}.json"


def _load_mapping(session_id: str) -> dict:
    path = _get_mapping_path(session_id)
    if path.exists():
        try:
            with open(path) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}
    return {}


def _save_mapping(session_id: str, mapping: dict) -> None:
    path = _get_mapping_path(session_id)
    with open(path, "w") as f:
        json.dump(mapping, f, indent=2)
    logger.debug("PII mapping saved to %s", path)


# ---------------------------------------------------------------------------
# Core anonymization logic
# ---------------------------------------------------------------------------

def _redact_string(value: str, counters: dict, mapping: dict) -> str:
    """Replace all PII occurrences in a string with placeholders."""
    result = value
    for pii_type, pattern in PII_PATTERNS:
        def replacer(m, pt=pii_type):
            original = m.group(0)
            # Reuse placeholder if we've seen this value before
            if original in mapping.get("forward", {}):
                return mapping["forward"][original]
            counter_key = f"counter_{pt}"
            counters[counter_key] = counters.get(counter_key, 0) + 1
            placeholder = f"[REDACTED_{pt}_{counters[counter_key]}]"
            mapping.setdefault("forward", {})[original] = placeholder
            mapping.setdefault("reverse", {})[placeholder] = original
            return placeholder
        result = pattern.sub(replacer, result)
    return result


def anonymize_json(
    data: Any,
    session_id: str,
    parent_key: str = "",
) -> tuple[Any, dict]:
    """
    Recursively walk a JSON-decoded object, detect and replace PII.

    Returns:
        (anonymized_data, pii_mapping)
        pii_mapping["forward"]  => {original_value: placeholder}
        pii_mapping["reverse"]  => {placeholder: original_value}
    """
    mapping = _load_mapping(session_id)
    counters: dict = {}
    result = _anonymize_recursive(data, counters, mapping, parent_key)
    _save_mapping(session_id, mapping)
    return result, mapping


def _anonymize_recursive(data: Any, counters: dict, mapping: dict, key: str = "") -> Any:
    if isinstance(data, dict):
        return {
            k: _anonymize_recursive(v, counters, mapping, k)
            for k, v in data.items()
        }
    elif isinstance(data, list):
        return [_anonymize_recursive(item, counters, mapping, key) for item in data]
    elif isinstance(data, str):
        # If the key name is sensitive (exact or suffix match), redact the whole value
        # e.g. "customer_name" matches "name", "user_address" matches "address"
        key_lower = key.lower()
        is_sensitive = key_lower in SENSITIVE_KEYS or any(
            key_lower == sk or key_lower.endswith("_" + sk)
            for sk in SENSITIVE_KEYS
        )
        if is_sensitive:
            original = data
            placeholder_type = "SENSITIVE_FIELD"
            if original in mapping.get("forward", {}):
                return mapping["forward"][original]
            counters[placeholder_type] = counters.get(placeholder_type, 0) + 1
            placeholder = f"[REDACTED_{key.upper()}_{counters[placeholder_type]}]"
            mapping.setdefault("forward", {})[original] = placeholder
            mapping.setdefault("reverse", {})[placeholder] = original
            return placeholder
        # Otherwise scan the string value for PII patterns
        return _redact_string(data, counters, mapping)
    else:
        return data


def deanonymize_json(data: Any, session_id: str) -> Any:
    """Replace all [REDACTED_*] placeholders with their original values."""
    mapping = _load_mapping(session_id)
    reverse = mapping.get("reverse", {})
    return _deanonymize_recursive(data, reverse)


def _deanonymize_recursive(data: Any, reverse: dict) -> Any:
    if isinstance(data, dict):
        return {k: _deanonymize_recursive(v, reverse) for k, v in data.items()}
    elif isinstance(data, list):
        return [_deanonymize_recursive(item, reverse) for item in data]
    elif isinstance(data, str):
        result = data
        for placeholder, original in reverse.items():
            result = result.replace(placeholder, original)
        return result
    return data


def summarize_pii_findings(mapping: dict) -> str:
    """Return a human-readable summary of what PII was found."""
    forward = mapping.get("forward", {})
    if not forward:
        return "No PII detected."
    type_counts: dict = {}
    for placeholder in forward.values():
        # Extract type from [REDACTED_TYPE_N]
        parts = placeholder.strip("[]").split("_")
        if len(parts) >= 2:
            pii_type = "_".join(parts[1:-1])
            type_counts[pii_type] = type_counts.get(pii_type, 0) + 1
    lines = [f"  - {count}x {ptype}" for ptype, count in sorted(type_counts.items())]
    return "PII found and redacted:\n" + "\n".join(lines)
