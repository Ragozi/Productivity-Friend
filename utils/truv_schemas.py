"""
Truv API JSON schemas and validation rules.

Derived from: https://docs.truv.com/reference/introduction
Base URL: https://prod.truv.com/v1/

Auth model (HTTP headers, NOT JSON body):
  X-Access-Client-Id: <your client ID>
  X-Access-Secret:    <your access secret>
  Content-Type:       application/json

Key webhook events:
  task-status-updated    — fired when an async task completes or fails
  order-status-updated   — fired when an order status changes

Webhook signing:
  HMAC SHA-256 using your Access Secret as the key.
  Truv sends the signature in the X-WEBHOOK-SIGN header.
  Verify: HMAC-SHA256(raw_body_bytes, access_secret) == X-WEBHOOK-SIGN

Add new endpoint schemas below as you encounter more customer JSON files.
"""

import hashlib
import hmac
import logging
from jsonschema import validate, ValidationError, Draft7Validator

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Re-usable sub-schemas
# ---------------------------------------------------------------------------

_PRODUCTS_ARRAY = {
    "type": "array",
    "minItems": 1,
    "items": {
        "type": "string",
        "enum": [
            "income",
            "employment",
            "direct_deposit_switch",
            "insurance",
            "assets",
            "paycheck_linked_loan",
        ],
    },
    "description": "Array of Truv product types to request",
}

_WEBHOOK_URL = {
    "type": "string",
    "format": "uri",
    "pattern": r"^https?://",
    "description": "URL Truv will POST webhook events to. Must be HTTPS in production.",
}

_USER_OBJECT = {
    "type": "object",
    "required": ["client_user_id"],
    "properties": {
        "client_user_id": {"type": "string", "minLength": 1},
        "email_address": {"type": "string", "format": "email"},
        "phone_number": {"type": "string"},
        "first_name": {"type": "string"},
        "last_name": {"type": "string"},
    },
}

# ---------------------------------------------------------------------------
# Payload schemas (the JSON body sent to each Truv endpoint)
# ---------------------------------------------------------------------------

# POST /v1/users — Create a new Truv user
USERS_SCHEMA = {
    "type": "object",
    "description": "POST /v1/users — Create a Truv user",
    "properties": {
        "external_user_id": {"type": "string"},
        "first_name": {"type": "string"},
        "last_name": {"type": "string"},
        "email": {"type": "string", "format": "email"},
        "phone": {"type": "string"},
    },
}

# POST /v1/users/{user_id}/tokens — Create a bridge token
BRIDGE_TOKEN_SCHEMA = {
    "type": "object",
    "description": "POST /v1/users/{user_id}/tokens — Create bridge token to initialise Truv Bridge",
    "required": ["client_name", "product_type"],
    "properties": {
        "client_name": {
            "type": "string",
            "minLength": 1,
            "description": "Your application name shown to the user in Bridge",
        },
        "product_type": {
            "type": "string",
            "enum": [
                "income",
                "employment",
                "direct_deposit_switch",
                "insurance",
                "assets",
                "paycheck_linked_loan",
            ],
            "description": "The Truv product this bridge session is for",
        },
        "tracking_info": {
            "type": "string",
            "description": "Optional internal tracking reference (max 50 chars)",
            "maxLength": 50,
        },
        "webhook_url": _WEBHOOK_URL,
        "account_link_id": {
            "type": "string",
            "description": "Existing account link ID (use to reconnect an existing link)",
        },
        "template_id": {
            "type": "string",
            "description": "UI customisation template ID",
        },
    },
}

# POST /v1/link/token/create — Legacy bridge token endpoint (some older integrations)
LINK_TOKEN_SCHEMA = {
    "type": "object",
    "description": "POST /v1/link/token/create — Create bridge token (legacy endpoint)",
    "required": ["client_name", "products", "country_codes", "user"],
    "properties": {
        "client_name": {"type": "string", "minLength": 1},
        "products": _PRODUCTS_ARRAY,
        "country_codes": {
            "type": "array",
            "items": {"type": "string", "enum": ["US", "CA"]},
            "minItems": 1,
        },
        "user": _USER_OBJECT,
        "webhook_url": _WEBHOOK_URL,
        "account_link_id": {"type": "string"},
        "template_id": {"type": "string"},
    },
}

# POST /v1/orders — Create a background-check style order (VOE / VOIE)
ORDERS_SCHEMA = {
    "type": "object",
    "description": "POST /v1/orders — Create a Truv verification order",
    "required": ["first_name", "last_name", "products"],
    "properties": {
        "first_name": {
            "type": "string",
            "minLength": 1,
            "description": "Subject's first name (REQUIRED)",
        },
        "last_name": {
            "type": "string",
            "minLength": 1,
            "description": "Subject's last name (REQUIRED)",
        },
        "products": _PRODUCTS_ARRAY,
        "email": {"type": "string", "format": "email"},
        "phone": {"type": "string"},
        "ssn": {
            "type": "string",
            "pattern": r"^\d{3}-?\d{2}-?\d{4}$",
            "description": "Social Security Number (last 4 or full, no dashes required)",
        },
        "date_of_birth": {
            "type": "string",
            "pattern": r"^\d{4}-\d{2}-\d{2}$",
            "description": "ISO 8601 date: YYYY-MM-DD",
        },
        "employer": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "address": {"type": "string"},
            },
        },
        "tracking_info": {"type": "string", "maxLength": 50},
        "webhook_url": _WEBHOOK_URL,
        "callback_url": _WEBHOOK_URL,
    },
}

# GET /v1/verifications/income — Income verification report
# (GET with query params, but customers sometimes send the params as JSON body)
INCOME_VERIFICATION_SCHEMA = {
    "type": "object",
    "description": "GET /v1/verifications/income — VOIE report parameters",
    "required": ["account_link_id"],
    "properties": {
        "account_link_id": {"type": "string", "minLength": 1},
        "start_date": {"type": "string", "format": "date"},
        "end_date": {"type": "string", "format": "date"},
    },
}

# GET /v1/verifications/employment — Employment verification
EMPLOYMENT_VERIFICATION_SCHEMA = {
    "type": "object",
    "description": "GET /v1/verifications/employment — VOE report parameters",
    "required": ["account_link_id"],
    "properties": {
        "account_link_id": {"type": "string", "minLength": 1},
    },
}

# POST /v1/refresh/tasks — Trigger async data refresh
REFRESH_SCHEMA = {
    "type": "object",
    "description": "POST /v1/refresh/tasks — Refresh data for an account link",
    "required": ["account_link_id"],
    "properties": {
        "account_link_id": {"type": "string", "minLength": 1},
        "products": _PRODUCTS_ARRAY,
    },
}

# POST /v1/dds/reports — Direct Deposit Switch report
DDS_REPORT_SCHEMA = {
    "type": "object",
    "description": "POST /v1/dds/reports — Initiate or retrieve DDS report",
    "required": ["account_link_id"],
    "properties": {
        "account_link_id": {"type": "string", "minLength": 1},
    },
}

# Generic fallback — just check it's a JSON object
GENERIC_SCHEMA = {
    "type": "object",
    "description": "Generic Truv API payload (endpoint not recognised — minimal validation)",
}

# ---------------------------------------------------------------------------
# Wrapper schema — customers sometimes send a full "request config" envelope
# e.g. { "endpoint": "/v1/orders", "payload": {...}, "auth": {...} }
# ---------------------------------------------------------------------------

WRAPPER_SCHEMA = {
    "type": "object",
    "description": "Customer integration config wrapper",
    "required": ["endpoint"],
    "properties": {
        "endpoint": {
            "type": "string",
            "pattern": r"^/v1/",
            "description": "Must start with /v1/ — e.g. /v1/orders",
        },
        "payload": {"type": "object"},
        "auth": {
            "type": "object",
            "properties": {
                "client_id": {"type": "string"},
                "access_secret": {"type": "string"},
            },
        },
        # Legacy / incorrect fields — trigger warnings
        "api_key": {
            "type": "string",
            "description": "DEPRECATED: Truv auth is done via X-Access-Client-Id / X-Access-Secret HTTP headers, not JSON body fields.",
        },
    },
}

# ---------------------------------------------------------------------------
# Endpoint → schema map
# ---------------------------------------------------------------------------

ENDPOINT_SCHEMA_MAP: dict[str, dict] = {
    # Bridge / link
    "/v1/users":                        USERS_SCHEMA,
    "/v1/link/token/create":            LINK_TOKEN_SCHEMA,
    # Orders (VOE / VOIE background check)
    "/v1/orders":                       ORDERS_SCHEMA,
    # Data retrieval
    "/v1/verifications/income":         INCOME_VERIFICATION_SCHEMA,
    "/v1/verifications/employment":     EMPLOYMENT_VERIFICATION_SCHEMA,
    # Data refresh
    "/v1/refresh/tasks":                REFRESH_SCHEMA,
    # Direct deposit switch
    "/v1/dds/reports":                  DDS_REPORT_SCHEMA,
}

# Map bridge token endpoint variants to the same schema
ENDPOINT_SCHEMA_MAP["/v1/users/{user_id}/tokens"] = BRIDGE_TOKEN_SCHEMA
ENDPOINT_SCHEMA_MAP["/v1/users/tokens"] = BRIDGE_TOKEN_SCHEMA


def get_schema_for_endpoint(endpoint: str) -> dict:
    """
    Return the most specific payload schema for the given Truv endpoint path.
    Normalises the path and falls back to GENERIC_SCHEMA if unknown.
    """
    ep = endpoint.strip().rstrip("/").lower()
    if not ep.startswith("/"):
        ep = "/" + ep

    # Exact match
    if ep in ENDPOINT_SCHEMA_MAP:
        return ENDPOINT_SCHEMA_MAP[ep]

    # Prefix match (handles path params like /v1/users/abc123/tokens)
    for pattern, schema in ENDPOINT_SCHEMA_MAP.items():
        base = pattern.split("{")[0].rstrip("/")
        if ep.startswith(base):
            return schema

    return GENERIC_SCHEMA


# ---------------------------------------------------------------------------
# Webhook configuration validation
# ---------------------------------------------------------------------------

WEBHOOK_EVENTS = {"task-status-updated", "order-status-updated"}


def validate_webhook_config(webhook_cfg: dict) -> list[str]:
    """
    Validate a customer's webhook configuration dict.

    Expected keys (any naming convention):
      - url / webhook_url: the endpoint URL
      - signing_method / algorithm: should be "hmac-sha256" or equivalent
      - events / event_types: list of subscribed event names
      - secret / signing_secret: the key used for HMAC

    Returns a list of error strings (empty = valid).
    """
    errors: list[str] = []

    # Resolve URL key
    url = (
        webhook_cfg.get("url")
        or webhook_cfg.get("webhook_url")
        or webhook_cfg.get("endpoint_url")
        or ""
    )
    if not url:
        errors.append(
            "Webhook URL is missing. Add 'url' or 'webhook_url' with a valid HTTPS endpoint."
        )
    elif not url.startswith("https://"):
        errors.append(
            f"Webhook URL must use HTTPS in production. Got: {url!r}"
        )

    # Check signing algorithm
    algo = (
        webhook_cfg.get("signing_method")
        or webhook_cfg.get("algorithm")
        or webhook_cfg.get("signing_algorithm")
        or ""
    ).lower().replace(" ", "-").replace("_", "-")
    if algo and algo not in ("hmac-sha256", "hmacsha256", "sha256"):
        errors.append(
            f"Webhook signing algorithm must be HMAC SHA-256. Got: {algo!r}. "
            "Truv sends the signature in the X-WEBHOOK-SIGN header."
        )
    elif not algo:
        errors.append(
            "Webhook signing algorithm not specified. Truv uses HMAC SHA-256. "
            "Verify the signature from the X-WEBHOOK-SIGN header."
        )

    # Check event subscriptions
    events = (
        webhook_cfg.get("events")
        or webhook_cfg.get("event_types")
        or webhook_cfg.get("subscriptions")
        or []
    )
    if not events:
        errors.append(
            f"No webhook events specified. Subscribe to at least: {sorted(WEBHOOK_EVENTS)}"
        )
    else:
        missing = WEBHOOK_EVENTS - set(events)
        if missing:
            errors.append(
                f"Missing recommended webhook event subscriptions: {sorted(missing)}. "
                "Add 'task-status-updated' and 'order-status-updated'."
            )

    # Check for signing secret
    secret = (
        webhook_cfg.get("secret")
        or webhook_cfg.get("signing_secret")
        or webhook_cfg.get("hmac_secret")
        or ""
    )
    if not secret:
        errors.append(
            "Webhook signing secret not configured. Use your Truv Access Secret "
            "to verify the X-WEBHOOK-SIGN header with HMAC SHA-256."
        )

    return errors


def verify_webhook_signature(
    raw_body: bytes,
    received_signature: str,
    access_secret: str,
) -> bool:
    """
    Verify a Truv webhook signature.

    Truv signs the raw request body with HMAC SHA-256 using your Access Secret.
    The signature is sent in the X-WEBHOOK-SIGN header.

    Args:
        raw_body:            The raw bytes of the webhook POST body.
        received_signature:  The value of the X-WEBHOOK-SIGN header.
        access_secret:       Your Truv Access Secret (from environment).

    Returns:
        True if the signature is valid, False otherwise.
    """
    expected = hmac.new(
        key=access_secret.encode("utf-8"),
        msg=raw_body,
        digestmod=hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, received_signature.lower())


# ---------------------------------------------------------------------------
# Auth header validation
# ---------------------------------------------------------------------------

def validate_auth_config(data: dict) -> list[str]:
    """
    Check for common authentication mistakes in customer JSON config.

    Truv auth is header-based — keys must NOT be in the JSON body.
    Required headers:
      X-Access-Client-Id: <client_id>
      X-Access-Secret:    <access_secret>

    Returns a list of warning/error strings.
    """
    warnings: list[str] = []

    # Check for auth credentials mistakenly placed in the JSON body
    body_auth_keys = {
        "api_key", "apikey", "api_secret", "access_secret",
        "client_id", "client_secret", "x-access-client-id", "x-access-secret",
        "authorization", "bearer_token",
    }
    found_in_body = [k for k in data if k.lower() in body_auth_keys]
    if found_in_body:
        warnings.append(
            f"Found auth credentials in JSON body: {found_in_body}. "
            "Truv authentication uses HTTP headers, not JSON body fields. "
            "Move these to request headers: X-Access-Client-Id and X-Access-Secret."
        )

    # Check for missing endpoint field (if this is a wrapper config)
    if "endpoint" in data:
        endpoint = data.get("endpoint", "")
        if not str(endpoint).startswith("/v1/"):
            warnings.append(
                f"Endpoint '{endpoint}' must start with /v1/ "
                f"(base URL is https://prod.truv.com/v1/)"
            )

    return warnings


# ---------------------------------------------------------------------------
# Main validation entry point
# ---------------------------------------------------------------------------

def validate_truv_json(data: dict) -> list[str]:
    """
    Validate a (potentially anonymised) Truv API JSON payload.

    Detection order:
    1. If the JSON has an 'endpoint' key → treat as wrapper config, validate envelope
       then validate the nested 'payload' (if present) against the endpoint schema.
    2. If the JSON has an 'orders'-like structure (first_name + last_name + products)
       → validate as an orders payload directly.
    3. If the JSON has a 'bridge_token' / 'product_type' key → bridge token schema.
    4. Otherwise → generic minimal validation.

    Returns:
        List of validation error messages. Empty list = valid.
    """
    errors: list[str] = []

    if not isinstance(data, dict):
        return ["JSON root must be an object (dict), not an array or primitive."]

    # Auth-in-body warnings (non-blocking but surfaced as errors for the TAM)
    errors.extend(validate_auth_config(data))

    endpoint = data.get("endpoint", "")

    # ── Wrapper config (has 'endpoint' key) ──────────────────────────────────
    if endpoint:
        # Validate the wrapper itself
        try:
            validate(instance=data, schema=WRAPPER_SCHEMA)
        except ValidationError as exc:
            errors.append(f"Config envelope: {exc.message}")

        # Validate the nested payload against the endpoint's schema
        payload = data.get("payload")
        if payload is not None:
            payload_schema = get_schema_for_endpoint(endpoint)
            payload_errors = _run_validation(payload, payload_schema)
            errors.extend(f"payload.{e}" for e in payload_errors)
        else:
            # Maybe the endpoint-specific fields are at the root level
            payload_schema = get_schema_for_endpoint(endpoint)
            if payload_schema is not GENERIC_SCHEMA:
                root_errors = _run_validation(data, payload_schema)
                # Filter out errors about 'endpoint' field not being in schema
                root_errors = [e for e in root_errors if "endpoint" not in e]
                errors.extend(root_errors)

    # ── Direct orders payload (first_name + last_name + products at root) ────
    elif "first_name" in data or "last_name" in data or (
        "products" in data and "client_name" not in data
    ):
        errors.extend(_run_validation(data, ORDERS_SCHEMA))

    # ── Bridge token payload ──────────────────────────────────────────────────
    elif "client_name" in data or "product_type" in data:
        if "products" in data and "country_codes" in data:
            errors.extend(_run_validation(data, LINK_TOKEN_SCHEMA))
        else:
            errors.extend(_run_validation(data, BRIDGE_TOKEN_SCHEMA))

    # ── Webhook config ────────────────────────────────────────────────────────
    elif any(k in data for k in ("webhook_url", "webhook", "webhooks", "events")):
        webhook_cfg = data.get("webhook") or data.get("webhooks") or data
        if isinstance(webhook_cfg, dict):
            errors.extend(validate_webhook_config(webhook_cfg))

    # ── Generic fallback ──────────────────────────────────────────────────────
    else:
        if not data:
            errors.append("JSON payload is empty.")

    # ── Webhook sub-config validation (if present anywhere in the payload) ───
    for key in ("webhook", "webhook_config", "webhooks"):
        sub = data.get(key) or (data.get("payload") or {}).get(key)
        if isinstance(sub, dict) and key not in ("webhooks",):
            wh_errors = validate_webhook_config(sub)
            if wh_errors:
                errors.extend(f"webhook config: {e}" for e in wh_errors)

    return errors


def _run_validation(data: dict, schema: dict) -> list[str]:
    """
    Run jsonschema validation and return a flat list of error strings.
    Collects ALL errors (not just the first).
    """
    errors: list[str] = []
    validator = Draft7Validator(schema)
    for err in validator.iter_errors(data):
        path = " → ".join(str(p) for p in err.absolute_path) if err.absolute_path else "root"
        errors.append(f"[{path}] {err.message}")
    return errors
