"""
Field name mapper.
Translates arbitrary customer field names into canonical Truv field names
using an exact lookup table first, then rapidfuzz for fuzzy matching.
"""

from rapidfuzz import fuzz, process

# Canonical Truv field → list of known customer aliases
FIELD_MAP = {
    # --- Identity / Profile ---
    "first_name":       ["firstname", "fname", "given_name", "givenname", "first", "forename"],
    "last_name":        ["lastname", "lname", "surname", "family_name", "familyname", "last", "second_name"],
    "middle_initials":  ["middle", "middlename", "middle_name", "mi"],
    "email":            ["email_address", "emailaddress", "e_mail", "contact_email", "mail"],
    "ssn":              ["social_security", "social_security_number", "ssn_number", "tax_id", "taxid",
                         "socialsecurity", "sin", "national_id"],
    "date_of_birth":    ["dob", "birthdate", "birth_date", "dateofbirth", "birthday", "born"],
    "phone":            ["phone_number", "phonenumber", "mobile", "cell", "telephone", "contact_phone",
                         "mobile_number", "cell_phone"],

    # --- Employment ---
    "job_title":        ["title", "position", "role", "jobtitle", "job_role", "occupation", "job_position"],
    "job_type":         ["employment_type", "work_type", "type", "jobtype", "position_type"],
    "start_date":       ["hire_date", "employment_start", "startdate", "hiredate", "employment_date",
                         "date_hired", "date_of_hire", "commencement_date"],
    "end_date":         ["termination_date", "separation_date", "enddate", "last_day", "date_terminated",
                         "termdate", "off_date"],
    "original_hire_date": ["original_hire", "first_hire_date", "initial_hire_date", "rehire_date"],
    "is_active":        ["active", "currently_employed", "current", "employed", "current_employee",
                         "still_employed", "employment_status"],
    "income":           ["salary", "annual_salary", "annual_income", "yearly_pay", "compensation",
                         "base_pay", "base_salary", "total_compensation", "wage", "annual_wage"],
    "income_unit":      ["pay_period", "salary_type", "compensation_type", "pay_type", "pay_basis"],
    "pay_frequency":    ["pay_schedule", "payroll_frequency", "payment_frequency", "payfrequency"],
    "manager_name":     ["manager", "supervisor", "supervisor_name", "direct_manager"],
    "dates_from_statements": ["derived_dates"],

    # --- Company ---
    "company.name":     ["employer", "employer_name", "company_name", "organization", "org_name",
                         "company", "firm", "business_name", "workplace"],
    "company.phone":    ["employer_phone", "company_phone", "work_phone", "business_phone"],
    "company.ein":      ["ein", "employer_id", "tax_id_number", "federal_tax_id", "fein",
                         "employer_ein", "company_ein"],

    # --- Address (shared for home_address and company.address) ---
    "street":           ["address", "address1", "street_address", "addr", "address_line1",
                         "street_line", "addr1"],
    "city":             ["city_name", "town", "municipality"],
    "state":            ["state_code", "province", "region", "state_province"],
    "zip":              ["zipcode", "zip_code", "postal_code", "postcode", "postal"],
    "country":          ["country_code", "nation", "country_name"],

    # --- Payroll Statements ---
    "gross_pay":        ["gross", "gross_amount", "gross_earnings", "total_gross", "gross_wages"],
    "net_pay":          ["net", "net_amount", "take_home", "net_earnings", "net_wages", "net_income"],
    "gross_pay_ytd":    ["gross_ytd", "ytd_gross", "year_to_date_gross", "grossytd"],
    "net_pay_ytd":      ["net_ytd", "ytd_net", "year_to_date_net", "netytd"],
    "pay_date":         ["paydate", "check_date", "payment_date", "cheque_date"],
    "period_start":     ["pay_period_start", "period_begin", "start_period", "pay_start"],
    "period_end":       ["pay_period_end", "period_finish", "end_period", "pay_end"],
    "check_number":     ["check_num", "cheque_number", "stub_number", "paystub_number"],
    "basis_of_pay":     ["pay_basis", "pay_type_code", "salary_or_hourly"],
    "hours":            ["hours_worked", "total_hours", "work_hours"],
    "bonus":            ["bonus_pay", "bonus_amount"],
    "commission":       ["commission_pay", "commission_amount"],
    "overtime":         ["overtime_pay", "ot_pay", "ot_amount"],
    "regular":          ["regular_pay", "base_pay_amount", "regular_wages"],

    # --- User creation (top-level) ---
    "external_user_id": ["user_id", "userid", "applicant_id", "borrower_id", "customer_id",
                         "client_id", "id", "reference_id"],
    "tracking_info":    ["tracking", "reference", "case_number", "loan_number", "application_id"],
    "product_type":     ["product", "verification_type", "service_type"],
}

# Build a reverse lookup: alias → canonical
_ALIAS_TO_CANONICAL = {}
for canonical, aliases in FIELD_MAP.items():
    for alias in aliases:
        _ALIAS_TO_CANONICAL[alias.lower().replace("-", "_")] = canonical

# Also map canonicals to themselves
for canonical in FIELD_MAP:
    _ALIAS_TO_CANONICAL[canonical.lower()] = canonical

# Flat list of all known aliases for fuzzy matching
_ALL_ALIASES = list(_ALIAS_TO_CANONICAL.keys())


def normalize_key(key: str) -> str:
    """Lowercase, strip spaces/hyphens, replace with underscores."""
    return key.lower().strip().replace(" ", "_").replace("-", "_")


def map_field(customer_key: str, fuzzy_threshold: int = 82) -> dict:
    """
    Given a customer field name, return a mapping result dict:
    {
        "canonical": str or None,
        "confidence": float (0-100),
        "method": "exact" | "fuzzy" | "none"
    }
    """
    normalized = normalize_key(customer_key)

    # 1. Exact match
    if normalized in _ALIAS_TO_CANONICAL:
        return {
            "canonical": _ALIAS_TO_CANONICAL[normalized],
            "confidence": 100.0,
            "method": "exact",
        }

    # 2. Fuzzy match
    result = process.extractOne(
        normalized,
        _ALL_ALIASES,
        scorer=fuzz.token_sort_ratio,
    )
    if result and result[1] >= fuzzy_threshold:
        matched_alias = result[0]
        canonical = _ALIAS_TO_CANONICAL.get(matched_alias)
        return {
            "canonical": canonical,
            "confidence": float(result[1]),
            "method": "fuzzy",
        }

    return {"canonical": None, "confidence": 0.0, "method": "none"}


def map_all_fields(customer_obj: dict, fuzzy_threshold: int = 82) -> dict:
    """
    Walk a flat or one-level-deep customer dict and attempt to map every key.
    Returns:
    {
        "mapped": {canonical_key: {"original_key": ..., "value": ..., "confidence": ..., "method": ...}},
        "unmapped": {customer_key: value},
    }
    """
    mapped = {}
    unmapped = {}

    for key, value in customer_obj.items():
        result = map_field(key, fuzzy_threshold)
        if result["canonical"]:
            mapped[result["canonical"]] = {
                "original_key": key,
                "value": value,
                "confidence": result["confidence"],
                "method": result["method"],
            }
        else:
            unmapped[key] = value

    return {"mapped": mapped, "unmapped": unmapped}
