"""
Microsoft Graph API authentication and request helpers.
Uses MSAL ConfidentialClientApplication with client credentials flow.
"""

import os
import logging
import requests
from msal import ConfidentialClientApplication

logger = logging.getLogger(__name__)

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
SCOPES = ["https://graph.microsoft.com/.default"]

# Cache the token to avoid re-authenticating on every call
_token_cache: dict = {}


def get_graph_token() -> str:
    """Acquire an OAuth2 access token for Microsoft Graph API."""
    client_id = os.getenv("CLIENT_ID")
    tenant_id = os.getenv("TENANT_ID")
    client_secret = os.getenv("CLIENT_SECRET")

    if not all([client_id, tenant_id, client_secret]):
        raise EnvironmentError(
            "Missing required env vars: CLIENT_ID, TENANT_ID, CLIENT_SECRET. "
            "Copy .env.example to .env and fill in your Azure app registration values."
        )

    app = ConfidentialClientApplication(
        client_id,
        authority=f"https://login.microsoftonline.com/{tenant_id}",
        client_credential=client_secret,
    )

    # Try cached token first
    result = app.acquire_token_silent(SCOPES, account=None)
    if not result:
        result = app.acquire_token_for_client(scopes=SCOPES)

    if "access_token" not in result:
        error = result.get("error_description", result.get("error", "Unknown auth error"))
        raise RuntimeError(f"Graph API authentication failed: {error}")

    logger.debug("Graph API token acquired successfully.")
    return result["access_token"]


def get_headers() -> dict:
    """Return authorization headers for Graph API requests."""
    return {
        "Authorization": f"Bearer {get_graph_token()}",
        "Content-Type": "application/json",
    }


def graph_get(path: str, params: dict = None) -> dict:
    """Perform a GET request against Microsoft Graph API."""
    url = f"{GRAPH_BASE}{path}"
    resp = requests.get(url, headers=get_headers(), params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def graph_post(path: str, body: dict) -> dict:
    """Perform a POST request against Microsoft Graph API."""
    url = f"{GRAPH_BASE}{path}"
    resp = requests.post(url, headers=get_headers(), json=body, timeout=30)
    resp.raise_for_status()
    return resp.json()


def graph_patch(path: str, body: dict) -> dict:
    """Perform a PATCH request against Microsoft Graph API."""
    url = f"{GRAPH_BASE}{path}"
    resp = requests.patch(url, headers=get_headers(), json=body, timeout=30)
    resp.raise_for_status()
    return resp.json()
