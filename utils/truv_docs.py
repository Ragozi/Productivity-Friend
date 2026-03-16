"""
Truv API documentation fetcher and local cache.

Strategy: Instead of RAG + vector DB, we do targeted per-endpoint fetching.
When the JSON agent detects a Truv endpoint (e.g. "/v1/link/token/create"),
we fetch that endpoint's reference page from docs.truv.com, extract the
schema, and inject it directly into Claude's fix prompt.

This works well because:
- The Truv API doc set is small and focused
- We always know which endpoint to look up (it's in the JSON)
- No embedding model or vector store needed
- Fetched docs are cached locally to avoid repeat network calls

Cache lives at: data/truv_docs/  (gitignored)
"""

import json
import logging
import re
import time
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

DOCS_CACHE_DIR = Path("data/truv_docs")
DOCS_CACHE_DIR.mkdir(parents=True, exist_ok=True)

CACHE_TTL_SECONDS = 60 * 60 * 24 * 7  # 1 week

# Map Truv API endpoint paths → ReadMe.io reference page slugs
# Add to this map as you encounter new customer JSON files
ENDPOINT_DOC_MAP: dict[str, str] = {
    "/v1/link/token/create":            "create-bridge-token",
    "/v1/users":                        "users-list",
    "/v1/users/{user_id}":              "users-retrieve",
    "/v1/users/{user_id}/tokens":       "create-bridge-token",
    "/v1/companies/search":             "companies-search",
    "/v1/account-links":                "account-links-list",
    "/v1/account-links/{link_id}":      "account-links-retrieve",
    "/v1/refresh/tasks":                "data-refresh-create",
    "/v1/verifications/income":         "income-report",
    "/v1/verifications/employment":     "employment-report",
    "/v1/income/pay_stubs":             "pay-statements-list",
    "/v1/income/tax_documents":         "tax-documents-list",
    "/v1/employment":                   "employment-retrieve",
    "/v1/identity":                     "identity-retrieve",
    "/v1/bank-data/accounts":           "accounts",
    "/v1/bank-data/transactions":       "transactions-list",
    "/v1/dds/reports":                  "dds-reports",
    "/v1/dds/bank_accounts":            "bank-accounts-list",
    "/v1/documents/collections":        "document-collections-list",
    "/v1/orders":                       "orders-list",
    "/v1/orders/{order_id}":            "orders-retrieve",
    "/v1/scoring_attributes/reports":   "scoring-attributes-report",
    "/v1/voa/reports":                  "voa-reports",
    # Generic fallback — just the intro page
    "default":                          "introduction",
}

# Hardcoded schema summaries for the most critical endpoints
# These serve as fallback when live fetch fails or for offline use
HARDCODED_SCHEMAS: dict[str, str] = {
    "/v1/link/token/create": """
POST /v1/link/token/create — Create Bridge Token
Required fields:
  - client_name (string): Your application's name shown to the user
  - products (array of strings): e.g. ["income", "employment", "direct_deposit_switch"]
  - country_codes (array of strings): e.g. ["US"]
  - user (object):
      - client_user_id (string, required): Your internal user ID
      - email_address (string, optional)
      - phone_number (string, optional)
Optional fields:
  - webhook_url (string, URI): URL to receive webhook events
  - account_link_id (string): Existing link to reconnect
  - template_id (string): Customization template
Response: { bridge_token: string, user_id: string }
""",
    "/v1/refresh/tasks": """
POST /v1/refresh/tasks — Trigger Data Refresh
Required fields:
  - account_link_id (string): The link to refresh
Optional fields:
  - products (array): Specific products to refresh, e.g. ["income", "employment"]
Response: { task_id: string, status: string }
""",
    "/v1/verifications/income": """
GET /v1/verifications/income — Income Verification Report
Required query params:
  - account_link_id (string): The account link to retrieve income for
Optional:
  - start_date (date): Filter start
  - end_date (date): Filter end
Response: VOIE report with pay statements, employer info, income summary
""",
    "/v1/verifications/employment": """
GET /v1/verifications/employment — Employment Verification
Required query params:
  - account_link_id (string)
Response: Employment status, employer name, start date, job title
""",
    "/v1/bank-data/accounts": """
GET /v1/bank-data/accounts — List Financial Accounts
Required query params:
  - account_link_id (string)
Response: List of accounts with balance, type, mask, nickname
""",
    "/v1/dds/reports": """
POST /v1/dds/reports — Direct Deposit Switch Report
Required fields:
  - account_link_id (string)
Response: DDS status, bank account info, deposit allocation
""",
}


def _cache_path(slug: str) -> Path:
    safe = re.sub(r"[^a-z0-9\-]", "_", slug)
    return DOCS_CACHE_DIR / f"{safe}.json"


def _is_cache_fresh(path: Path) -> bool:
    if not path.exists():
        return False
    age = time.time() - path.stat().st_mtime
    return age < CACHE_TTL_SECONDS


def _fetch_doc_page(slug: str) -> str:
    """Fetch a single Truv reference page and return extracted text."""
    url = f"https://docs.truv.com/reference/{slug}"
    try:
        resp = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        if resp.status_code != 200:
            logger.warning("Docs fetch returned %d for %s", resp.status_code, url)
            return ""

        # Strip HTML tags and collapse whitespace
        text = re.sub(r"<[^>]+>", " ", resp.text)
        text = re.sub(r"\s+", " ", text).strip()

        # Extract the most relevant portion (first 4000 chars after "Parameters")
        for marker in ("Parameters", "Request Body", "Body Params", "Required"):
            idx = text.find(marker)
            if idx != -1:
                return text[max(0, idx - 200): idx + 4000]

        return text[:4000]
    except Exception as exc:
        logger.warning("Could not fetch docs for %s: %s", slug, exc)
        return ""


def get_endpoint_docs(endpoint: str) -> str:
    """
    Return schema documentation for a Truv API endpoint path.

    Lookup order:
    1. Local file cache (fresh within 1 week)
    2. Hardcoded schema (offline fallback)
    3. Live fetch from docs.truv.com → cached
    4. Empty string (graceful degradation)
    """
    # Normalize endpoint
    ep = endpoint.strip().lower()
    if not ep.startswith("/"):
        ep = "/" + ep

    # Find best slug match (exact, then prefix)
    slug = ENDPOINT_DOC_MAP.get(ep)
    if not slug:
        for mapped_ep, mapped_slug in ENDPOINT_DOC_MAP.items():
            if ep.startswith(mapped_ep.split("{")[0]):
                slug = mapped_slug
                break
    if not slug:
        slug = ENDPOINT_DOC_MAP["default"]

    cache = _cache_path(slug)

    # 1. Fresh cache hit
    if _is_cache_fresh(cache):
        try:
            data = json.loads(cache.read_text())
            logger.debug("Docs cache hit for %s", slug)
            return data.get("content", "")
        except Exception:
            pass

    # 2. Hardcoded fallback (available immediately, no network)
    hardcoded = HARDCODED_SCHEMAS.get(ep, "")

    # 3. Try live fetch
    logger.info("Fetching Truv docs for endpoint: %s (slug: %s)", ep, slug)
    live_content = _fetch_doc_page(slug)

    if live_content:
        content = live_content
    elif hardcoded:
        logger.info("Using hardcoded schema for %s", ep)
        content = hardcoded
    else:
        content = ""

    # Cache whatever we got
    if content:
        cache.write_text(json.dumps({
            "endpoint": ep,
            "slug": slug,
            "content": content,
            "fetched_at": time.time(),
        }, indent=2))

    return content


def refresh_all_docs() -> dict[str, bool]:
    """
    Pre-warm the docs cache for all known endpoints.
    Call this via: python -m utils.truv_docs
    Returns {endpoint: success} map.
    """
    results = {}
    seen_slugs: set[str] = set()
    for endpoint, slug in ENDPOINT_DOC_MAP.items():
        if slug in seen_slugs or endpoint == "default":
            continue
        seen_slugs.add(slug)
        cache = _cache_path(slug)
        # Force refresh
        if cache.exists():
            cache.unlink()
        content = get_endpoint_docs(endpoint)
        results[endpoint] = bool(content)
        logger.info("%s → %s", endpoint, "✓" if content else "✗")
    return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    print("Refreshing Truv docs cache...\n")
    results = refresh_all_docs()
    ok = sum(1 for v in results.values() if v)
    print(f"\nDone: {ok}/{len(results)} endpoints cached.")
