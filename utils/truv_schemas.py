"""
Truv API JSON schemas for validation.

These are derived from Truv's public API documentation at truv.com/docs.
Expand this file as more endpoints are encountered in customer emails.
"""

from jsonschema import validate, ValidationError

# ---------------------------------------------------------------------------
# Endpoint schemas
# ---------------------------------------------------------------------------

# Base schema applied to all Truv API requests
_BASE_SCHEMA = {
    "type": "object",
    "required": ["api_key", "endpoint"],
    "properties": {
        "api_key":  {"type": "string", "minLength": 1},
        "endpoint": {"type": "string", "pattern": r"^/v1/.*$"},
    },
}

# /v1/verify — Income/employment verification
VERIFY_SCHEMA = {
    **_BASE_SCHEMA,
    "required": ["api_key", "endpoint", "payload"],
    "properties": {
        **_BASE_SCHEMA["properties"],
        "payload": {
            "type": "object",
            "required": ["account_id"],
            "properties": {
                "account_id":     {"type": "string"},
                "bridge_token":   {"type": "string"},
                "product_type":   {
                    "type": "string",
                    "enum": ["income", "employment", "direct_deposit_switch",
                             "insurance", "assets", "paycheck_linked_loan"],
                },
                "access_token":   {"type": "string"},
                "webhook_url":    {"type": "string", "format": "uri"},
                "metadata":       {"type": "object"},
            },
        },
    },
}

# /v1/link/token/create — Create a bridge token
LINK_TOKEN_SCHEMA = {
    **_BASE_SCHEMA,
    "required": ["api_key", "endpoint", "payload"],
    "properties": {
        **_BASE_SCHEMA["properties"],
        "payload": {
            "type": "object",
            "required": ["client_name", "products", "country_codes", "user"],
            "properties": {
                "client_name":    {"type": "string"},
                "products":       {"type": "array", "items": {"type": "string"}},
                "country_codes":  {"type": "array", "items": {"type": "string"}},
                "user": {
                    "type": "object",
                    "required": ["client_user_id"],
                    "properties": {
                        "client_user_id": {"type": "string"},
                        "email_address":  {"type": "string", "format": "email"},
                        "phone_number":   {"type": "string"},
                    },
                },
                "webhook_url": {"type": "string", "format": "uri"},
            },
        },
    },
}

# /v1/refresh/tasks — Trigger data refresh
REFRESH_SCHEMA = {
    **_BASE_SCHEMA,
    "required": ["api_key", "endpoint", "payload"],
    "properties": {
        **_BASE_SCHEMA["properties"],
        "payload": {
            "type": "object",
            "required": ["access_token"],
            "properties": {
                "access_token": {"type": "string"},
                "products":     {"type": "array", "items": {"type": "string"}},
            },
        },
    },
}

# Generic fallback — minimal validation for unknown endpoints
GENERIC_SCHEMA = _BASE_SCHEMA


ENDPOINT_SCHEMA_MAP: dict = {
    "/v1/verify":            VERIFY_SCHEMA,
    "/v1/link/token/create": LINK_TOKEN_SCHEMA,
    "/v1/refresh/tasks":     REFRESH_SCHEMA,
}


def get_schema_for_endpoint(endpoint: str) -> dict:
    """Return the most specific schema for the given endpoint path."""
    return ENDPOINT_SCHEMA_MAP.get(endpoint, GENERIC_SCHEMA)


def validate_truv_json(data: dict) -> list[str]:
    """
    Validate a (potentially anonymized) JSON object against the appropriate schema.

    Returns:
        List of validation error messages (empty = valid).
    """
    endpoint = data.get("endpoint", "")
    schema = get_schema_for_endpoint(endpoint)
    errors: list[str] = []
    try:
        validate(instance=data, schema=schema)
    except ValidationError as exc:
        errors.append(exc.message)
        # Collect all sub-errors for nested objects
        for sub_err in exc.context:
            errors.append(f"  • {sub_err.message}")
    return errors
