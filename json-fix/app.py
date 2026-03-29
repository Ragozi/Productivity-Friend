"""
JSON_FIX — Flask Application
Truv API JSON processor with drag-and-drop UI.
"""

import io
import json
import os
import uuid
import zipfile
from datetime import datetime

from flask import Flask, jsonify, render_template, request, send_file, send_from_directory

from processors.cleaner import generate_output, process_file
from config import OUTPUT_DIR, LOG_DIR, MAX_UPLOAD_MB

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024
app.secret_key = os.urandom(24)

# In-memory session store: file_id → analysis dict
_sessions: dict = {}

os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/upload", methods=["POST"])
def upload():
    """
    Accept one or more JSON files.
    Returns list of analysis results (one per file).
    """
    files = request.files.getlist("files")
    if not files:
        return jsonify({"error": "No files uploaded"}), 400

    results = []
    for f in files:
        if not f.filename:
            continue
        content = f.read()
        analysis = process_file(content, f.filename)
        _sessions[analysis["file_id"]] = analysis

        # Serialize mapping for JSON response
        results.append(_serialize_analysis(analysis))

    return jsonify({"results": results})


@app.route("/fix", methods=["POST"])
def fix():
    """
    Generate a fixed output file for a single file_id with user-provided field overrides.
    Returns download URLs for the output JSON and audit log.
    """
    body = request.get_json()
    if not body:
        return jsonify({"error": "No JSON body"}), 400

    file_id = body.get("file_id")
    user_overrides = body.get("overrides", {})
    doc_type_override = body.get("doc_type")

    session_data = _sessions.get(file_id)
    if not session_data:
        return jsonify({"error": "File session not found. Please re-upload."}), 404

    output_json, audit_json = generate_output(session_data, user_overrides, doc_type_override)

    base_name = os.path.splitext(session_data["filename"])[0]
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    output_filename = f"{base_name}_truv_ready_{ts}.json"
    audit_filename = f"{base_name}_audit_{ts}.json"

    output_path = os.path.join(OUTPUT_DIR, output_filename)
    audit_path = os.path.join(OUTPUT_DIR, audit_filename)

    with open(output_path, "w", encoding="utf-8") as fh:
        fh.write(output_json)
    with open(audit_path, "w", encoding="utf-8") as fh:
        fh.write(audit_json)

    # Update session with output paths
    _sessions[file_id]["output_filename"] = output_filename
    _sessions[file_id]["audit_filename"] = audit_filename

    return jsonify({
        "success": True,
        "output_url": f"/download/{output_filename}",
        "audit_url": f"/download/{audit_filename}",
        "output_filename": output_filename,
        "audit_filename": audit_filename,
        "preview": json.loads(output_json),
    })


@app.route("/bulk_fix", methods=["POST"])
def bulk_fix():
    """
    Fix all provided file_ids and package outputs into a ZIP.
    Body: {"files": [{"file_id": ..., "overrides": {...}, "doc_type": ...}, ...]}
    """
    body = request.get_json()
    if not body:
        return jsonify({"error": "No JSON body"}), 400

    files = body.get("files", [])
    if not files:
        return jsonify({"error": "No file entries provided"}), 400

    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    zip_filename = f"json_fix_bulk_{ts}.zip"
    zip_path = os.path.join(OUTPUT_DIR, zip_filename)

    results = []
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for entry in files:
            file_id = entry.get("file_id")
            overrides = entry.get("overrides", {})
            doc_type_override = entry.get("doc_type")

            session_data = _sessions.get(file_id)
            if not session_data:
                results.append({"file_id": file_id, "error": "Session not found"})
                continue

            try:
                output_json, audit_json = generate_output(session_data, overrides, doc_type_override)
                base_name = os.path.splitext(session_data["filename"])[0]
                out_name = f"{base_name}_truv_ready.json"
                audit_name = f"{base_name}_audit.json"
                zf.writestr(out_name, output_json)
                zf.writestr(audit_name, audit_json)
                results.append({"file_id": file_id, "filename": session_data["filename"], "success": True})
            except Exception as e:
                results.append({"file_id": file_id, "error": str(e)})

    return jsonify({
        "success": True,
        "zip_url": f"/download_zip/{zip_filename}",
        "zip_filename": zip_filename,
        "results": results,
    })


@app.route("/download/<filename>")
def download(filename):
    return send_from_directory(OUTPUT_DIR, filename, as_attachment=True)


@app.route("/download_zip/<filename>")
def download_zip(filename):
    return send_from_directory(OUTPUT_DIR, filename, as_attachment=True)


@app.route("/session/<file_id>")
def get_session(file_id):
    """Return current session data for a file (useful for re-fetching after page reload)."""
    session_data = _sessions.get(file_id)
    if not session_data:
        return jsonify({"error": "Session not found"}), 404
    return jsonify(_serialize_analysis(session_data))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _serialize_analysis(analysis: dict) -> dict:
    """Make analysis dict JSON-serializable (drop non-serializable original_data ref)."""
    mapping_out = {}
    for canonical, info in analysis.get("mapping", {}).items():
        mapping_out[canonical] = {
            "original_key": info.get("original_key"),
            "value": _safe_val(info.get("value")),
            "confidence": info.get("confidence"),
            "method": info.get("method"),
        }

    cleaned_out = {}
    for k, v in analysis.get("cleaned", {}).items():
        cleaned_out[k] = _safe_val(v)

    return {
        "file_id": analysis.get("file_id"),
        "filename": analysis.get("filename"),
        "status": analysis.get("status"),
        "doc_type": analysis.get("doc_type"),
        "doc_type_confidence": analysis.get("doc_type_confidence"),
        "doc_type_reason": analysis.get("doc_type_reason"),
        "mapping": mapping_out,
        "unmapped": {k: _safe_val(v) for k, v in analysis.get("unmapped", {}).items()},
        "issues": analysis.get("issues", []),
        "auto_fixes": analysis.get("auto_fixes", []),
        "cleaned": cleaned_out,
        "critical_count": analysis.get("critical_count", 0),
        "warning_count": analysis.get("warning_count", 0),
        "error": analysis.get("error"),
        "output_filename": analysis.get("output_filename"),
        "audit_filename": analysis.get("audit_filename"),
    }


def _safe_val(v):
    """Convert any value to something JSON-serializable."""
    if isinstance(v, (str, int, float, bool, type(None))):
        return v
    return str(v)


if __name__ == "__main__":
    print("=" * 60)
    print("  JSON_FIX — Truv API JSON Processor")
    print("  http://localhost:5000")
    print("=" * 60)
    app.run(debug=True, host="0.0.0.0", port=5000)
