"""
JSON_FIX Configuration
Truv API settings and application config.
All secrets and environment-specific values load from a .env file.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from json-fix/ directory
load_dotenv(Path(__file__).parent / ".env")

TRUV_CONFIG = {
    "base_url": os.getenv("TRUV_BASE_URL", "https://prod.truv.com/v1"),
    "sandbox_url": os.getenv("TRUV_SANDBOX_URL", "https://sandbox.truv.com/v1"),
    "client_id": os.getenv("TRUV_CLIENT_ID", ""),
    "access_secret": os.getenv("TRUV_ACCESS_SECRET", ""),
    "environment": os.getenv("TRUV_ENV", "sandbox"),
}

# URL of Productivity-Friend api_server (port 8000) for deep schema validation.
# Set to empty string to disable the integration.
PRODUCTIVITY_FRIEND_URL = os.getenv("PRODUCTIVITY_FRIEND_URL", "http://localhost:8000")

PRODUCT_TYPES = [
    "income",
    "employment",
    "deposit_switch",
    "pll",
    "insurance",
    "transactions",
]

JOB_TYPES = {
    "F": "Full-time",
    "P": "Part-time",
    "S": "Seasonal",
    "O": "Other",
}

PAY_FREQUENCIES = {
    "M": "Monthly",
    "S": "Semi-monthly",
    "B": "Bi-weekly",
    "W": "Weekly",
}

INCOME_UNITS = ["YEARLY", "HOURLY", "DAILY", "WEEKLY", "MONTHLY"]

OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", Path(__file__).parent / "output"))
LOG_DIR = Path(os.getenv("LOG_DIR", Path(__file__).parent / "logs"))
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "10"))
