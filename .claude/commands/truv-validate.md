Validate and fix a Truv API JSON file.

## What to do

1. **Identify the file**: Use the file path provided as an argument, or if none given, ask the user which JSON file to validate.

2. **Read the file**: Read the full contents of the JSON file.

3. **Try Productivity-Friend (Beelink)**: Attempt to POST the JSON to the Productivity-Friend API server. Try these URLs in order until one responds:
   - `http://192.168.50.194:8000/api/process-json` (Beelink on home network)
   - `http://localhost:8000/api/process-json` (local machine)

   Send as:
   ```json
   {
     "json_data": <the parsed JSON>,
     "filename": "<filename>",
     "customer_email": "customer@example.com"
   }
   ```
   Use a 3-second connection timeout. If both fail, proceed to local mode.

4. **Remote mode (server responded)**:
   - Display a summary: how many errors were found, whether Claude fixed them
   - List each validation error clearly, referencing the field name
   - Show the diff summary (what changed)
   - Write the fixed JSON to `<original-filename>.fixed.json` in the same directory
   - Tell the user the file has been saved

5. **Local fallback mode (server unreachable)**:
   - Notify the user: "Productivity-Friend server not reachable — processing locally"
   - Analyze the JSON yourself for common Truv API issues:
     - Auth credentials (`api_key`, `access_secret`, `client_id`) in the JSON body instead of HTTP headers
     - Missing required fields for the detected endpoint type
     - Wrong field formats (SSN with dashes, dates not YYYY-MM-DD, phone not E.164)
     - Empty or null values for required fields
     - `webhook_url` using HTTP instead of HTTPS
   - List all issues found with severity (CRITICAL / WARNING)
   - Produce a corrected version of the JSON with fixes applied
   - Write the corrected JSON to `<original-filename>.fixed.json`

6. **Always output**:
   - A numbered list of issues found (or "No issues found — JSON looks valid")
   - The path to the `.fixed.json` file written
   - A one-paragraph summary suitable for pasting into a customer reply email

## Output format example

```
── Truv JSON Validator ──────────────────────────────
File: customer_payload.json
Mode: Remote (Productivity-Friend at 192.168.50.194)

Issues found (2):
  [CRITICAL] api_key found in JSON body — move to X-Access-Client-Id header
  [WARNING]  ssn format: "123-45-6789" should be "123456789" (no dashes)

Fixes applied: 2
Fixed file saved: customer_payload.fixed.json

Customer reply summary:
  "I've reviewed your integration payload and found 2 issues that would cause
   API errors. I've attached a corrected version — the main change is moving
   your credentials to HTTP headers (X-Access-Client-Id / X-Access-Secret)
   rather than the request body, as required by the Truv API."
────────────────────────────────────────────────────
```
