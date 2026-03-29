# JSON_FIX — Truv API JSON Processor

A drag-and-drop web tool that takes customer-submitted JSON files (from any HR/payroll platform) and converts them into clean, valid Truv API payloads.

## What It Does

1. **Accepts** any `.json` file — customer format, any field names
2. **Detects** what kind of Truv payload it should become (user creation, employment report, etc.)
3. **Maps** customer field names → Truv canonical fields (exact + fuzzy matching)
4. **Validates** all field formats (SSN, dates, phone, income, state codes, etc.)
5. **Auto-fixes** common formatting issues (adds dashes to EIN, reformats dates, normalizes phone to E.164, etc.)
6. **Prompts you** for any missing required fields via the UI
7. **Outputs** a clean, Truv API-ready `.json` + an audit log of every change made

## Setup

```bash
cd D:\Projects\JSON_FIX

# Install dependencies
pip install -r requirements.txt

# Start the server
python app.py
```

Then open http://localhost:5000 in your browser.

## Usage

1. Drag and drop one or more `.json` files onto the drop zone
2. Review the field mapping and issues on the right panel
3. Fill in any missing required fields (red CRITICAL items)
4. Click **Generate Fixed JSON**
5. Download the clean output file + audit log

For multiple files: use **Fix All & Download ZIP** in the bulk bar.

## File Structure

```
JSON_FIX/
├── app.py                  # Flask app + all routes
├── config.py               # Truv API settings
├── requirements.txt
├── processors/
│   ├── parser.py           # JSON loading + document type detection
│   ├── mapper.py           # Field name mapping (exact + fuzzy)
│   ├── validator.py        # Format validation + auto-normalization
│   ├── cleaner.py          # Pipeline orchestration
│   └── api_builder.py      # Builds final Truv API payloads
├── templates/index.html    # Frontend UI
├── static/
│   ├── style.css
│   └── app.js
├── output/                 # Generated files (auto-created)
└── logs/                   # Audit logs (auto-created)
```

## Truv Sandbox (Phase 2)

When Truv provides sandbox credentials:
1. Click **⚙ Settings** in the top right
2. Enter your Client ID and Access Secret
3. Set environment to "Sandbox"

Phase 2 will wire these credentials into the generated payloads and add live sandbox testing.

## Field Mapping

The mapper knows ~150+ field name variants across common HR platforms. Examples:
- `firstName`, `fname`, `given_name` → `first_name`
- `salary`, `annual_income`, `base_pay` → `income`
- `hire_date`, `employment_start`, `hiredate` → `start_date`
- `employer`, `company_name`, `organization` → `company.name`

Fields that don't match exactly get fuzzy-matched (85%+ similarity threshold). Anything below that shows as "unrecognized" so you can see what the customer sent.

## Output Format

Each generated file contains:
- `_truv_api` — the correct endpoint, HTTP method, and required headers
- `_environment` — sandbox or production
- `payload` — the clean data, Truv API-ready

Plus a separate `_audit.json` file showing every field mapping decision and change made.
