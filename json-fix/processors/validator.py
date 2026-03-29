"""
Validation and format-checking for Truv API fields.
Issues are categorized as CRITICAL, WARNING, or INFO.
"""

import re
from dateutil import parser as dateparser
from config import INCOME_UNITS, JOB_TYPES, PAY_FREQUENCIES

# ---------------------------------------------------------------------------
# Format normalizers — return (normalized_value, info_message | None)
# ---------------------------------------------------------------------------

def normalize_ssn(value) -> tuple:
    if value is None:
        return None, None
    s = str(value).replace("-", "").replace(" ", "").replace(".", "")
    if len(s) == 9 and s.isdigit():
        return s, f"SSN normalized to 9-digit string (removed formatting)"
    return value, None


def normalize_date(value) -> tuple:
    """Try to parse and reformat any date string to YYYY-MM-DD."""
    if value is None:
        return None, None
    if isinstance(value, (int, float)):
        return str(value), None
    s = str(value).strip()
    # Already in correct format
    if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        return s, None
    try:
        parsed = dateparser.parse(s, dayfirst=False)
        formatted = parsed.strftime("%Y-%m-%d")
        return formatted, f"Date reformatted from '{s}' to '{formatted}'"
    except Exception:
        return value, None


def normalize_phone(value) -> tuple:
    """Normalize US phone numbers to E.164 format (+1XXXXXXXXXX)."""
    if value is None:
        return None, None
    s = str(value).strip()
    digits = re.sub(r"\D", "", s)
    if len(digits) == 10:
        result = f"+1{digits}"
        return result, f"Phone normalized to E.164: {result}"
    if len(digits) == 11 and digits.startswith("1"):
        result = f"+{digits}"
        return result, f"Phone normalized to E.164: {result}"
    if s.startswith("+") and len(digits) >= 10:
        return s, None
    return value, None


def normalize_income(value) -> tuple:
    """Ensure income is a decimal string like '70000.00'."""
    if value is None:
        return None, None
    if isinstance(value, (int, float)):
        formatted = f"{float(value):.2f}"
        return formatted, f"Income converted from {type(value).__name__} to string '{formatted}'"
    s = str(value).strip().replace(",", "")
    try:
        formatted = f"{float(s):.2f}"
        if formatted != s:
            return formatted, f"Income normalized to '{formatted}'"
        return formatted, None
    except ValueError:
        return value, None


def normalize_ein(value) -> tuple:
    """Normalize EIN to XX-XXXXXXX format."""
    if value is None:
        return None, None
    s = str(value).strip().replace("-", "").replace(" ", "")
    if len(s) == 9 and s.isdigit():
        formatted = f"{s[:2]}-{s[2:]}"
        return formatted, f"EIN formatted to {formatted}"
    return value, None


def normalize_state(value) -> tuple:
    if value is None:
        return None, None
    s = str(value).strip().upper()
    if len(s) == 2:
        return s, None
    # Common state name → abbreviation (limited set for now)
    state_map = {
        "ALABAMA": "AL", "ALASKA": "AK", "ARIZONA": "AZ", "ARKANSAS": "AR",
        "CALIFORNIA": "CA", "COLORADO": "CO", "CONNECTICUT": "CT", "DELAWARE": "DE",
        "FLORIDA": "FL", "GEORGIA": "GA", "HAWAII": "HI", "IDAHO": "ID",
        "ILLINOIS": "IL", "INDIANA": "IN", "IOWA": "IA", "KANSAS": "KS",
        "KENTUCKY": "KY", "LOUISIANA": "LA", "MAINE": "ME", "MARYLAND": "MD",
        "MASSACHUSETTS": "MA", "MICHIGAN": "MI", "MINNESOTA": "MN", "MISSISSIPPI": "MS",
        "MISSOURI": "MO", "MONTANA": "MT", "NEBRASKA": "NE", "NEVADA": "NV",
        "NEW HAMPSHIRE": "NH", "NEW JERSEY": "NJ", "NEW MEXICO": "NM", "NEW YORK": "NY",
        "NORTH CAROLINA": "NC", "NORTH DAKOTA": "ND", "OHIO": "OH", "OKLAHOMA": "OK",
        "OREGON": "OR", "PENNSYLVANIA": "PA", "RHODE ISLAND": "RI", "SOUTH CAROLINA": "SC",
        "SOUTH DAKOTA": "SD", "TENNESSEE": "TN", "TEXAS": "TX", "UTAH": "UT",
        "VERMONT": "VT", "VIRGINIA": "VA", "WASHINGTON": "WA", "WEST VIRGINIA": "WV",
        "WISCONSIN": "WI", "WYOMING": "WY", "DISTRICT OF COLUMBIA": "DC",
    }
    abbr = state_map.get(s)
    if abbr:
        return abbr, f"State name '{value}' converted to abbreviation '{abbr}'"
    return value, None


def normalize_country(value) -> tuple:
    if value is None:
        return "US", "Country defaulted to 'US'"
    s = str(value).strip().upper()
    if len(s) == 2:
        return s, None
    country_map = {
        "UNITED STATES": "US", "UNITED STATES OF AMERICA": "US", "USA": "US",
        "CANADA": "CA", "MEXICO": "MX", "UNITED KINGDOM": "GB", "UK": "GB",
    }
    abbr = country_map.get(s)
    if abbr:
        return abbr, f"Country '{value}' converted to code '{abbr}'"
    return value, None


def normalize_income_unit(value) -> tuple:
    if value is None:
        return None, None
    s = str(value).strip().upper()
    if s in INCOME_UNITS:
        return s, None
    # Map common values
    unit_map = {
        "YEAR": "YEARLY", "ANNUAL": "YEARLY", "ANNUALLY": "YEARLY", "PER YEAR": "YEARLY",
        "HOUR": "HOURLY", "PER HOUR": "HOURLY", "HOURLY RATE": "HOURLY",
        "DAY": "DAILY", "PER DAY": "DAILY",
        "WEEK": "WEEKLY", "PER WEEK": "WEEKLY",
        "MONTH": "MONTHLY", "PER MONTH": "MONTHLY",
    }
    mapped = unit_map.get(s)
    if mapped:
        return mapped, f"Income unit '{value}' normalized to '{mapped}'"
    return value, None


def normalize_job_type(value) -> tuple:
    if value is None:
        return None, None
    s = str(value).strip().upper()
    if s in JOB_TYPES:
        return s, None
    job_map = {
        "FULL TIME": "F", "FULL-TIME": "F", "FULLTIME": "F", "FT": "F",
        "PART TIME": "P", "PART-TIME": "P", "PARTTIME": "P", "PT": "P",
        "SEASONAL": "S", "CONTRACT": "O", "TEMPORARY": "O", "TEMP": "O", "OTHER": "O",
    }
    mapped = job_map.get(s)
    if mapped:
        return mapped, f"Job type '{value}' normalized to '{mapped}'"
    return value, None


def normalize_pay_frequency(value) -> tuple:
    if value is None:
        return None, None
    s = str(value).strip().upper()
    if s in PAY_FREQUENCIES:
        return s, None
    freq_map = {
        "MONTHLY": "M", "MONTH": "M",
        "SEMI-MONTHLY": "S", "SEMIMONTHLY": "S", "TWICE A MONTH": "S", "BIMONTHLY": "S",
        "BI-WEEKLY": "B", "BIWEEKLY": "B", "EVERY TWO WEEKS": "B", "FORTNIGHTLY": "B",
        "WEEKLY": "W", "WEEK": "W", "EVERY WEEK": "W",
    }
    mapped = freq_map.get(s)
    if mapped:
        return mapped, f"Pay frequency '{value}' normalized to '{mapped}'"
    return value, None


def normalize_bool(value) -> tuple:
    if isinstance(value, bool):
        return value, None
    if isinstance(value, str):
        if value.lower() in ("true", "yes", "1", "active", "current", "y"):
            return True, f"'{value}' converted to boolean true"
        if value.lower() in ("false", "no", "0", "inactive", "terminated", "n"):
            return False, f"'{value}' converted to boolean false"
    if isinstance(value, int):
        return bool(value), f"{value} converted to boolean {bool(value)}"
    return value, None


# ---------------------------------------------------------------------------
# Field-level validators — return list of issues
# ---------------------------------------------------------------------------

REQUIRED_USER_CREATE = ["external_user_id", "first_name", "last_name", "email"]
RECOMMENDED_USER_CREATE = ["phone", "ssn"]

REQUIRED_EMPLOYMENT = ["job_title", "start_date", "is_active"]
RECOMMENDED_EMPLOYMENT = [
    "income", "income_unit", "job_type", "pay_frequency",
    "end_date", "original_hire_date",
]

REQUIRED_PROFILE = ["first_name", "last_name"]
RECOMMENDED_PROFILE = ["email", "ssn", "date_of_birth"]

REQUIRED_COMPANY = ["name"]
RECOMMENDED_COMPANY = ["address", "phone", "ein"]

REQUIRED_STATEMENT = ["pay_date", "gross_pay", "net_pay"]
RECOMMENDED_STATEMENT = ["period_start", "period_end", "gross_pay_ytd", "net_pay_ytd", "hours"]


def validate_email(value) -> str | None:
    if not value:
        return None
    pattern = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
    if not re.match(pattern, str(value)):
        return f"'{value}' does not appear to be a valid email address"
    return None


def validate_ssn(value) -> str | None:
    if not value:
        return None
    s = str(value).replace("-", "").replace(" ", "")
    if not (len(s) == 9 and s.isdigit()):
        return f"SSN must be exactly 9 digits (got: '{value}')"
    return None


def validate_income_unit(value) -> str | None:
    if not value:
        return None
    if str(value).upper() not in INCOME_UNITS:
        return f"income_unit must be one of {INCOME_UNITS} (got: '{value}')"
    return None


def validate_job_type(value) -> str | None:
    if not value:
        return None
    if str(value).upper() not in JOB_TYPES:
        return f"job_type must be one of {list(JOB_TYPES.keys())} (F=Full-time, P=Part-time, S=Seasonal, O=Other) (got: '{value}')"
    return None


def validate_pay_frequency(value) -> str | None:
    if not value:
        return None
    if str(value).upper() not in PAY_FREQUENCIES:
        return f"pay_frequency must be one of {list(PAY_FREQUENCIES.keys())} (M/S/B/W) (got: '{value}')"
    return None


def validate_date(value, field_name="date") -> str | None:
    if not value:
        return None
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", str(value)):
        return f"{field_name} must be YYYY-MM-DD format (got: '{value}')"
    return None


# ---------------------------------------------------------------------------
# High-level validator
# ---------------------------------------------------------------------------

def validate_and_clean(mapped: dict, doc_type: str) -> dict:
    """
    Given a dict of {canonical_field: {original_key, value, confidence, method}},
    apply normalizers and collect issues.

    Returns:
    {
        "cleaned": {canonical_field: cleaned_value},
        "issues": [{"field": ..., "severity": "CRITICAL"|"WARNING"|"INFO", "message": ...}],
        "auto_fixes": [{"field": ..., "original": ..., "fixed": ..., "note": ...}],
    }
    """
    cleaned = {}
    issues = []
    auto_fixes = []

    def get_val(field):
        entry = mapped.get(field)
        return entry["value"] if entry else None

    def set_cleaned(field, value):
        cleaned[field] = value

    def add_issue(field, severity, message):
        issues.append({"field": field, "severity": severity, "message": message})

    def apply_normalizer(field, normalizer_fn):
        """Apply a normalizer, record auto-fix if value changed."""
        val = get_val(field)
        if val is None:
            return None
        normalized, note = normalizer_fn(val)
        if note:
            auto_fixes.append({
                "field": field,
                "original": val,
                "fixed": normalized,
                "note": note,
            })
        return normalized

    # --- Auto-clean all values that have normalizers ---
    normalizers = {
        "ssn": normalize_ssn,
        "date_of_birth": normalize_date,
        "start_date": normalize_date,
        "end_date": normalize_date,
        "original_hire_date": normalize_date,
        "pay_date": normalize_date,
        "period_start": normalize_date,
        "period_end": normalize_date,
        "phone": normalize_phone,
        "income": normalize_income,
        "gross_pay": normalize_income,
        "net_pay": normalize_income,
        "gross_pay_ytd": normalize_income,
        "net_pay_ytd": normalize_income,
        "ein": normalize_ein,
        "state": normalize_state,
        "country": normalize_country,
        "income_unit": normalize_income_unit,
        "job_type": normalize_job_type,
        "pay_frequency": normalize_pay_frequency,
        "is_active": normalize_bool,
    }

    for field, entry in mapped.items():
        raw_val = entry["value"]
        if field in normalizers:
            norm_val = apply_normalizer(field, normalizers[field])
            set_cleaned(field, norm_val)
        else:
            set_cleaned(field, raw_val)

    # --- Required field checks ---
    if doc_type in ("user_create", "unknown", "employment_report"):
        for field in REQUIRED_USER_CREATE:
            val = cleaned.get(field) or get_val(field)
            if not val:
                add_issue(field, "CRITICAL",
                          f"Required field '{field}' is missing. Truv user creation will fail without it.")

        for field in RECOMMENDED_USER_CREATE:
            val = cleaned.get(field) or get_val(field)
            if not val:
                add_issue(field, "WARNING",
                          f"Recommended field '{field}' is missing. Verification may be incomplete.")

    if doc_type in ("employment_report", "unknown"):
        for field in REQUIRED_EMPLOYMENT:
            val = cleaned.get(field) or get_val(field)
            if not val and val is not False:
                add_issue(field, "CRITICAL",
                          f"Required employment field '{field}' is missing.")
        for field in RECOMMENDED_EMPLOYMENT:
            val = cleaned.get(field) or get_val(field)
            if not val and val is not False:
                add_issue(field, "WARNING",
                          f"Recommended employment field '{field}' is missing or empty.")

    # --- Format validation on cleaned values ---
    format_validators = {
        "email": validate_email,
        "ssn": validate_ssn,
        "income_unit": validate_income_unit,
        "job_type": validate_job_type,
        "pay_frequency": validate_pay_frequency,
    }
    date_fields = [
        "start_date", "end_date", "original_hire_date", "date_of_birth",
        "pay_date", "period_start", "period_end",
    ]
    for df in date_fields:
        val = cleaned.get(df)
        if val:
            err = validate_date(val, df)
            if err:
                add_issue(df, "WARNING", err)

    for field, fn in format_validators.items():
        val = cleaned.get(field)
        if val is not None:
            err = fn(val)
            if err:
                severity = "CRITICAL" if field in REQUIRED_USER_CREATE else "WARNING"
                add_issue(field, severity, err)

    # Add INFO notices for auto-fixes
    for fix in auto_fixes:
        add_issue(fix["field"], "INFO", fix["note"])

    return {
        "cleaned": cleaned,
        "issues": issues,
        "auto_fixes": auto_fixes,
    }
