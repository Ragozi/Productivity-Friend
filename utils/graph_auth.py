"""
Microsoft Graph API authentication and request helpers.

Supports two auth flows — auto-detected from environment variables:

  1. DEVICE CODE FLOW (personal @outlook.com / any Microsoft account)
     Required env vars: CLIENT_ID only
     How it works: On first run, prints a URL + code. You open the URL,
     enter the code, sign in with your Microsoft account. Token is cached
     in ~/.productivity_friend_token_cache.json for subsequent runs.
     No client secret needed. Requires Delegated permissions in Azure.

  2. CLIENT CREDENTIALS FLOW (corporate M365 / Azure AD accounts)
     Required env vars: CLIENT_ID + TENANT_ID + CLIENT_SECRET
     How it works: App-only auth, no user interaction. Requires
     Application permissions in Azure (Mail.Read, Calendars.Read, etc.).

Setup for personal Outlook (Device Code flow):
  1. Go to https://portal.azure.com (sign in with ANY Microsoft account)
  2. Azure Active Directory → App registrations → New registration
  3. Name: "Productivity-Friend"
  4. Supported account types: "Personal Microsoft accounts only"
     (or "Any Microsoft account" to support both personal + work)
  5. Redirect URI: leave blank (not needed for Device Code flow)
  6. Register → copy the Application (client) ID → set as CLIENT_ID in .env
  7. API Permissions → Add → Microsoft Graph → Delegated permissions:
       Mail.Read, Mail.ReadWrite, Calendars.Read, User.Read
  8. Grant admin consent (for personal accounts you consent during login)
"""

import json
import os
import logging
import requests
from pathlib import Path

from msal import ConfidentialClientApplication, PublicClientApplication, SerializableTokenCache

logger = logging.getLogger(__name__)

GRAPH_BASE = "https://graph.microsoft.com/v1.0"

# Delegated scopes for personal accounts (Device Code flow)
DELEGATED_SCOPES = [
    "https://graph.microsoft.com/Mail.Read",
    "https://graph.microsoft.com/Mail.ReadWrite",
    "https://graph.microsoft.com/Calendars.Read",
    "https://graph.microsoft.com/User.Read",
]

# App-only scopes for client credentials flow
APP_SCOPES = ["https://graph.microsoft.com/.default"]

# Token cache file for Device Code flow (persists across runs)
TOKEN_CACHE_PATH = Path.home() / ".productivity_friend_token_cache.json"

# Module-level cache so we only authenticate once per process
_cached_token: str | None = None


def _load_token_cache() -> SerializableTokenCache:
    cache = SerializableTokenCache()
    if TOKEN_CACHE_PATH.exists():
        cache.deserialize(TOKEN_CACHE_PATH.read_text())
    return cache


def _save_token_cache(cache: SerializableTokenCache) -> None:
    if cache.has_state_changed:
        TOKEN_CACHE_PATH.write_text(cache.serialize())
        TOKEN_CACHE_PATH.chmod(0o600)  # owner read/write only


def _get_token_device_code(client_id: str) -> str:
    """
    Acquire a token via Device Code flow (personal @outlook.com accounts).
    On first run: prints a URL and code for the user to open in a browser.
    On subsequent runs: uses the cached token silently.
    """
    cache = _load_token_cache()

    # Authority for personal Microsoft accounts
    authority = "https://login.microsoftonline.com/consumers"

    app = PublicClientApplication(
        client_id,
        authority=authority,
        token_cache=cache,
    )

    # Try silent auth with cached accounts first
    accounts = app.get_accounts()
    if accounts:
        result = app.acquire_token_silent(DELEGATED_SCOPES, account=accounts[0])
        if result and "access_token" in result:
            _save_token_cache(cache)
            logger.debug("Token refreshed silently from cache.")
            return result["access_token"]

    # First run (or cache expired): trigger Device Code flow
    flow = app.initiate_device_flow(scopes=DELEGATED_SCOPES)

    if "user_code" not in flow:
        raise RuntimeError(f"Device flow initiation failed: {flow.get('error_description', flow)}")

    # Print clear instructions for the user
    print("\n" + "─" * 60)
    print("  Microsoft Sign-In Required")
    print("─" * 60)
    print(f"  1. Open this URL in your browser:")
    print(f"     {flow['verification_uri']}")
    print(f"\n  2. Enter this code when prompted:")
    print(f"     {flow['user_code']}")
    print(f"\n  Waiting for you to sign in... (expires in ~{flow.get('expires_in', 900)//60} min)")
    print("─" * 60 + "\n")

    result = app.acquire_token_by_device_flow(flow)

    if "access_token" not in result:
        error = result.get("error_description", result.get("error", "Unknown error"))
        raise RuntimeError(f"Device Code auth failed: {error}")

    _save_token_cache(cache)
    print("  ✓ Signed in successfully. Token cached for future runs.\n")
    return result["access_token"]


def _get_token_client_credentials(client_id: str, tenant_id: str, client_secret: str) -> str:
    """
    Acquire a token via Client Credentials flow (corporate M365 accounts).
    App-only, no user interaction required.
    """
    app = ConfidentialClientApplication(
        client_id,
        authority=f"https://login.microsoftonline.com/{tenant_id}",
        client_credential=client_secret,
    )

    result = app.acquire_token_silent(APP_SCOPES, account=None)
    if not result:
        result = app.acquire_token_for_client(scopes=APP_SCOPES)

    if "access_token" not in result:
        error = result.get("error_description", result.get("error", "Unknown auth error"))
        raise RuntimeError(f"Client Credentials auth failed: {error}")

    logger.debug("App-only token acquired via Client Credentials.")
    return result["access_token"]


def get_graph_token() -> str:
    """
    Acquire a Microsoft Graph API token.

    Auto-detects the flow based on environment variables:
    - CLIENT_ID only              → Device Code flow (personal @outlook.com)
    - CLIENT_ID + TENANT_ID
      + CLIENT_SECRET             → Client Credentials flow (corporate M365)
    """
    global _cached_token

    client_id     = os.getenv("CLIENT_ID")
    tenant_id     = os.getenv("TENANT_ID")
    client_secret = os.getenv("CLIENT_SECRET")

    if not client_id:
        raise EnvironmentError(
            "CLIENT_ID is not set.\n"
            "  For personal @outlook.com: set only CLIENT_ID in .env\n"
            "  For corporate M365: set CLIENT_ID, TENANT_ID, CLIENT_SECRET in .env\n"
            "  See .env.example for setup instructions."
        )

    if tenant_id and client_secret:
        # Corporate: Client Credentials flow
        return _get_token_client_credentials(client_id, tenant_id, client_secret)
    else:
        # Personal: Device Code flow
        return _get_token_device_code(client_id)


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


def graph_delete(path: str) -> None:
    """Perform a DELETE request against Microsoft Graph API."""
    url = f"{GRAPH_BASE}{path}"
    resp = requests.delete(url, headers=get_headers(), timeout=30)
    resp.raise_for_status()
