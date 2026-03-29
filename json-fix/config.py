"""
JSON_FIX Configuration
Truv API settings and application config.
"""

TRUV_CONFIG = {
    "base_url": "https://prod.truv.com/v1",
    "sandbox_url": "https://prod.truv.com/v1",  # Same base URL; sandbox vs prod is determined by credentials
    "client_id": "",       # Fill in when sandbox creds are provided
    "access_secret": "",   # Fill in when sandbox creds are provided
    "environment": "sandbox",  # "sandbox" or "production"
}

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

OUTPUT_DIR = "output"
LOG_DIR = "logs"
MAX_UPLOAD_MB = 10
