"""
Builds final Truv API-ready JSON payloads from cleaned, mapped field data.
"""

import uuid
from config import TRUV_CONFIG


def _strip_none(d: dict) -> dict:
    """Remove None values from a dict."""
    return {k: v for k, v in d.items() if v is not None}


def build_user_create_payload(cleaned: dict, user_overrides: dict = None) -> dict:
    """
    Build a Truv POST /v1/users/ payload.
    user_overrides: fields the user filled in manually via the UI.
    """
    if user_overrides:
        cleaned = {**cleaned, **user_overrides}

    payload = _strip_none({
        "external_user_id": cleaned.get("external_user_id") or str(uuid.uuid4()),
        "first_name": cleaned.get("first_name"),
        "last_name": cleaned.get("last_name"),
        "email": cleaned.get("email"),
        "phone": cleaned.get("phone"),
        "ssn": cleaned.get("ssn"),
    })

    return payload


def build_bridge_token_payload(cleaned: dict, user_overrides: dict = None) -> dict:
    """
    Build a Truv POST /v1/users/{user_id}/tokens/ payload.
    """
    if user_overrides:
        cleaned = {**cleaned, **user_overrides}

    payload = _strip_none({
        "product_type": cleaned.get("product_type", "income"),
        "tracking_info": cleaned.get("tracking_info", ""),
    })

    return payload


def build_employment_report_payload(cleaned: dict, original_data: dict, user_overrides: dict = None) -> dict:
    """
    Build a structured employment/income report payload.
    This represents the data that would be returned by / submitted to Truv's income report endpoint.
    """
    if user_overrides:
        cleaned = {**cleaned, **user_overrides}

    # Build profile block
    home_address = None
    addr_keys = ["street", "city", "state", "zip", "country"]
    addr_data = {k: cleaned.get(k) for k in addr_keys if cleaned.get(k)}
    if addr_data:
        home_address = _strip_none({
            "street": addr_data.get("street"),
            "city": addr_data.get("city"),
            "state": addr_data.get("state"),
            "zip": addr_data.get("zip"),
            "country": addr_data.get("country", "US"),
        })

    profile = _strip_none({
        "first_name": cleaned.get("first_name"),
        "last_name": cleaned.get("last_name"),
        "middle_initials": cleaned.get("middle_initials"),
        "email": cleaned.get("email"),
        "ssn": cleaned.get("ssn"),
        "date_of_birth": cleaned.get("date_of_birth"),
        "home_address": home_address,
    })

    # Build company block
    # Try to pull company address from original nested data
    company_data = original_data.get("company", {}) if isinstance(original_data, dict) else {}
    company_addr = company_data.get("address") if isinstance(company_data, dict) else None

    company = _strip_none({
        "name": cleaned.get("company.name") or (company_data.get("name") if isinstance(company_data, dict) else None),
        "address": company_addr,
        "phone": cleaned.get("company.phone") or (company_data.get("phone") if isinstance(company_data, dict) else None),
        "ein": cleaned.get("company.ein") or (company_data.get("ein") if isinstance(company_data, dict) else None),
    })

    # Build employment entry
    employment = _strip_none({
        "id": cleaned.get("id") or str(uuid.uuid4()),
        "job_title": cleaned.get("job_title"),
        "job_type": cleaned.get("job_type"),
        "start_date": cleaned.get("start_date"),
        "end_date": cleaned.get("end_date"),
        "original_hire_date": cleaned.get("original_hire_date"),
        "is_active": cleaned.get("is_active"),
        "income": cleaned.get("income"),
        "income_unit": cleaned.get("income_unit"),
        "pay_frequency": cleaned.get("pay_frequency"),
        "manager_name": cleaned.get("manager_name"),
        "profile": profile if profile else None,
        "company": company if company else None,
    })

    # Handle statements array
    statements = []
    raw_statements = original_data.get("statements", []) if isinstance(original_data, dict) else []
    if raw_statements and isinstance(raw_statements, list):
        for s in raw_statements:
            if isinstance(s, dict):
                statements.append(s)
    elif cleaned.get("pay_date") or cleaned.get("gross_pay"):
        # Build a single statement from flat fields
        stmt = _strip_none({
            "id": str(uuid.uuid4()),
            "pay_date": cleaned.get("pay_date"),
            "period_start": cleaned.get("period_start"),
            "period_end": cleaned.get("period_end"),
            "gross_pay": cleaned.get("gross_pay"),
            "net_pay": cleaned.get("net_pay"),
            "gross_pay_ytd": cleaned.get("gross_pay_ytd"),
            "net_pay_ytd": cleaned.get("net_pay_ytd"),
            "hours": cleaned.get("hours"),
            "basis_of_pay": cleaned.get("basis_of_pay"),
            "bonus": cleaned.get("bonus"),
            "commission": cleaned.get("commission"),
            "overtime": cleaned.get("overtime"),
            "regular": cleaned.get("regular"),
            "check_number": cleaned.get("check_number"),
        })
        if stmt:
            statements.append(stmt)

    if statements:
        employment["statements"] = statements

    # Try to preserve existing employments array from original
    employments = []
    raw_employments = original_data.get("employments", []) if isinstance(original_data, dict) else []
    if raw_employments and isinstance(raw_employments, list):
        # Merge cleaned data into first employment if it exists
        if raw_employments:
            merged = {**raw_employments[0], **{k: v for k, v in employment.items() if v is not None}}
            employments.append(merged)
            employments.extend(raw_employments[1:])
        else:
            employments.append(employment)
    else:
        employments.append(employment)

    payload = _strip_none({
        "id": str(uuid.uuid4()),
        "employments": employments,
        "provider": original_data.get("provider") if isinstance(original_data, dict) else None,
        "data_source": original_data.get("data_source", "payroll") if isinstance(original_data, dict) else "payroll",
    })

    return payload


def build_full_output(
    doc_type: str,
    cleaned: dict,
    original_data: dict,
    user_overrides: dict = None,
) -> dict:
    """
    Master builder — delegates to the right payload builder based on doc type.
    Also wraps with API metadata/instructions.
    """
    user_overrides = user_overrides or {}

    if doc_type == "user_create":
        payload = build_user_create_payload(cleaned, user_overrides)
        api_info = {
            "method": "POST",
            "url": f"{TRUV_CONFIG['base_url']}/users/",
            "headers": {
                "X-Access-Client-Id": TRUV_CONFIG.get("client_id") or "{{YOUR_CLIENT_ID}}",
                "X-Access-Secret": TRUV_CONFIG.get("access_secret") or "{{YOUR_ACCESS_SECRET}}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        }
    elif doc_type == "bridge_token":
        payload = build_bridge_token_payload(cleaned, user_overrides)
        api_info = {
            "method": "POST",
            "url": f"{TRUV_CONFIG['base_url']}/users/{{user_id}}/tokens/",
            "headers": {
                "X-Access-Client-Id": TRUV_CONFIG.get("client_id") or "{{YOUR_CLIENT_ID}}",
                "X-Access-Secret": TRUV_CONFIG.get("access_secret") or "{{YOUR_ACCESS_SECRET}}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            "note": "Replace {user_id} with the actual user_id returned from the create user call.",
        }
    else:
        # employment_report or unknown — default to full report
        payload = build_employment_report_payload(cleaned, original_data, user_overrides)
        api_info = {
            "method": "GET",
            "url": f"{TRUV_CONFIG['base_url']}/links/{{link_id}}/income/report",
            "headers": {
                "X-Access-Client-Id": TRUV_CONFIG.get("client_id") or "{{YOUR_CLIENT_ID}}",
                "X-Access-Secret": TRUV_CONFIG.get("access_secret") or "{{YOUR_ACCESS_SECRET}}",
                "Accept": "application/json",
            },
            "note": "This represents the expected Truv report structure. Replace {link_id} with the actual link_id.",
        }

    return {
        "_truv_api": api_info,
        "_environment": TRUV_CONFIG.get("environment", "sandbox"),
        "payload": payload,
    }
