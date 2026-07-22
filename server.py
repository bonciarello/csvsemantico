"""
CSV to JSON-LD Converter — Server
Converts CSV files to structured JSON-LD with semantic mapping.
"""

import csv
import io
import json
import os
import uuid
import threading
import time
from pathlib import Path

from flask import Flask, request, jsonify, send_file, render_template, make_response

app = Flask(__name__, static_folder="static", template_folder="templates")

# ---------------------------------------------------------------------------
# In-memory job store
# ---------------------------------------------------------------------------
jobs: dict = {}           # job_id -> {status, progress, result, error, csv_headers, ...}
jobs_lock = threading.Lock()

CONTEXTS_DIR = Path(__file__).parent / "contexts"

# Predefined contexts
PREDEFINED_CONTEXTS = {
    "schema.org": {
        "label": "Schema.org",
        "description": "Standard vocabulary for structured data on the web (products, events, people, etc.)",
        "contextUrl": "https://schema.org/",
        "file": "schema.org.json",
    },
    "foaf": {
        "label": "FOAF",
        "description": "Friend of a Friend — vocabulary for describing people and their relationships",
        "contextUrl": "http://xmlns.com/foaf/0.1/",
        "file": "foaf.json",
    },
    "dcat": {
        "label": "DCAT",
        "description": "Data Catalog Vocabulary — for describing datasets and data catalogs",
        "contextUrl": "http://www.w3.org/ns/dcat#",
        "file": "dcat.json",
    },
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def load_context_file(filename: str) -> dict | None:
    """Load a predefined context JSON file from the contexts directory."""
    path = CONTEXTS_DIR / filename
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def parse_csv_preview(content: str, delimiter: str = "auto") -> dict:
    """
    Parse CSV content and return a preview with headers and sample rows.
    Auto-detect delimiter if not specified.
    """
    if delimiter == "auto":
        # Try to detect delimiter
        sniffer = csv.Sniffer()
        try:
            dialect = sniffer.sniff(content[:4096], delimiters=",;\t|")
            delimiter = dialect.delimiter
        except csv.Error:
            # Fallback: check common delimiters in first line
            first_line = content.split("\n")[0] if content else ""
            for d in [",", ";", "\t", "|"]:
                if d in first_line:
                    delimiter = d
                    break
            else:
                delimiter = ","

    reader = csv.reader(io.StringIO(content), delimiter=delimiter)
    rows = list(reader)

    if not rows:
        return {"headers": [], "preview": [], "rowCount": 0, "delimiter": delimiter}

    headers = [h.strip() for h in rows[0]]
    data_rows = rows[1:] if len(rows) > 1 else []
    preview_rows = data_rows[:10]  # first 10 rows as preview
    row_count = len(data_rows)

    # Build preview: each row as a dict
    preview = []
    for row in preview_rows:
        row_dict = {}
        for i, header in enumerate(headers):
            row_dict[header] = row[i].strip() if i < len(row) else ""
        preview.append(row_dict)

    return {
        "headers": headers,
        "preview": preview,
        "rowCount": row_count,
        "delimiter": delimiter,
    }


def generate_jsonld(
    rows: list[dict],
    mapping: dict,
    context: dict,
    entity_type: str | None = None,
    base_iri: str = "",
) -> list[dict]:
    """
    Generate JSON-LD from parsed CSV rows and a column-to-property mapping.

    mapping: { "columnName": { "property": "schema:name", "datatype": "string"|"integer"|"float"|"boolean"|"date"|"url" }, ... }
    context: the full context dict from the loaded context file
    entity_type: optional @type for each entity (e.g., "Person", "Dataset")
    base_iri: optional base IRI for entity @id generation

    Returns a list of JSON-LD entity objects.
    """
    # Build the @context for the output
    ctx = context.get("@context", {}).copy()
    # Keep only the mapping (remove @vocab if we want explicit mapping)
    # Actually, we should include @vocab from the context file for completeness

    entities = []
    for idx, row in enumerate(rows):
        entity = {}
        # Generate @id
        if base_iri:
            entity["@id"] = f"{base_iri.rstrip('/')}/item-{idx + 1}"
        else:
            entity["@id"] = f"_:item-{idx + 1}"

        if entity_type:
            entity["@type"] = entity_type

        for col_name, prop_info in mapping.items():
            if col_name not in row:
                continue
            value = row[col_name].strip()
            if not value:
                continue

            prop_name = prop_info.get("property", "").strip()
            datatype = prop_info.get("datatype", "string").strip()

            if not prop_name:
                continue

            # Type coercion
            typed_value = coerce_value(value, datatype)

            # Store with property name (use shorthand if available)
            entity[prop_name] = typed_value

        entities.append(entity)

    return entities


def coerce_value(value: str, datatype: str):
    """Coerce a string value to the specified datatype."""
    if datatype == "integer":
        try:
            return int(value)
        except ValueError:
            return value
    elif datatype == "float":
        try:
            return float(value)
        except ValueError:
            return value
    elif datatype == "boolean":
        v = value.lower().strip()
        if v in ("true", "yes", "1", "y"):
            return True
        elif v in ("false", "no", "0", "n", ""):
            return False
        else:
            return value
    elif datatype == "date":
        # Pass through as string (could do ISO normalization)
        return value
    elif datatype == "url":
        # Pass through as string, but could validate
        return value
    else:
        return value


def build_jsonld_document(entities: list[dict], context: dict) -> dict:
    """Wrap entities into a proper JSON-LD document."""
    ctx = context.get("@context", {})

    if len(entities) == 1:
        doc = {"@context": ctx, **entities[0]}
    else:
        doc = {
            "@context": ctx,
            "@graph": entities,
        }
    return doc


def run_conversion_job(job_id: str):
    """Background job: perform the CSV→JSON-LD conversion."""
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            return
        job["status"] = "processing"
        job["progress"] = 0

    try:
        with jobs_lock:
            content = job["csv_content"]
            delimiter = job.get("delimiter", "auto")
            mapping = job.get("mapping", {})
            context = job.get("context", {})
            entity_type = job.get("entity_type")
            base_iri = job.get("base_iri", "")

        # Parse CSV
        reader = csv.reader(io.StringIO(content), delimiter=delimiter if delimiter != "auto" else ",")
        rows = list(reader)
        if not rows:
            raise ValueError("CSV file is empty")

        # Auto-detect delimiter if needed
        if delimiter == "auto" and len(content) > 0:
            sniffer = csv.Sniffer()
            try:
                dialect = sniffer.sniff(content[:4096], delimiters=",;\t|")
                actual_delimiter = dialect.delimiter
            except csv.Error:
                first_line = content.split("\n")[0] if content else ""
                for d in [",", ";", "\t", "|"]:
                    if d in first_line:
                        actual_delimiter = d
                        break
                else:
                    actual_delimiter = ","
            reader = csv.reader(io.StringIO(content), delimiter=actual_delimiter)
            rows = list(reader)

        headers = [h.strip() for h in rows[0]]
        data_rows = rows[1:]

        with jobs_lock:
            job["progress"] = 10

        # Build row dicts
        row_dicts = []
        total = len(data_rows)
        for i, row in enumerate(data_rows):
            row_dict = {}
            for j, header in enumerate(headers):
                row_dict[header] = row[j].strip() if j < len(row) else ""
            row_dicts.append(row_dict)

            # Update progress
            if total > 0 and i % max(1, total // 10) == 0:
                progress = 10 + int((i / total) * 80)
                with jobs_lock:
                    job["progress"] = min(progress, 90)

        with jobs_lock:
            job["progress"] = 90

        # Generate JSON-LD
        entities = generate_jsonld(row_dicts, mapping, context, entity_type, base_iri)
        document = build_jsonld_document(entities, context)

        # Validate: check all mapped columns actually produced data
        mapped_columns = list(mapping.keys())
        validation = {
            "entityCount": len(entities),
            "mappedColumns": len(mapped_columns),
            "totalRows": len(data_rows),
            "warnings": [],
        }

        # Check for empty entities (no properties beyond @id/@type)
        empty_count = 0
        for entity in entities:
            props = {k: v for k, v in entity.items() if k not in ("@id", "@type")}
            if not props:
                empty_count += 1
        if empty_count > 0:
            validation["warnings"].append(
                f"{empty_count} entities have no mapped properties. Check your column mapping."
            )

        with jobs_lock:
            job["status"] = "completed"
            job["progress"] = 100
            job["result"] = document
            job["validation"] = validation

    except Exception as e:
        with jobs_lock:
            job["status"] = "error"
            job["error"] = str(e)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    """Serve the main page."""
    return render_template("index.html")


@app.route("/api/upload", methods=["POST"])
def upload_csv():
    """Upload a CSV file and return parsed headers + preview."""
    if "file" not in request.files:
        return jsonify({"error": "Nessun file caricato"}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "Nome file vuoto"}), 400

    try:
        content = file.read().decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            content = file.read().decode("latin-1")
        except UnicodeDecodeError:
            return jsonify({"error": "Impossibile decodificare il file. Assicurati che sia in formato UTF-8."}), 400

    delimiter = request.form.get("delimiter", "auto")

    result = parse_csv_preview(content, delimiter)

    # Store the content temporarily for this session
    job_id = str(uuid.uuid4())
    with jobs_lock:
        jobs[job_id] = {
            "status": "uploaded",
            "progress": 0,
            "csv_content": content,
            "delimiter": result["delimiter"],
            "headers": result["headers"],
            "preview": result["preview"],
            "rowCount": result["rowCount"],
            "created_at": time.time(),
        }

    result["job_id"] = job_id
    return jsonify(result)


@app.route("/api/contexts", methods=["GET"])
def list_contexts():
    """Return the list of predefined contexts with their properties."""
    contexts_list = []
    for key, info in PREDEFINED_CONTEXTS.items():
        ctx_data = load_context_file(info["file"])
        if ctx_data:
            # Extract property names (short names) from @context
            ctx_obj = ctx_data.get("@context", {})
            properties = []
            for prop_name, prop_uri in ctx_obj.items():
                if prop_name.startswith("@"):
                    continue
                if isinstance(prop_uri, str) and prop_uri.startswith("http"):
                    properties.append({
                        "name": prop_name,
                        "uri": prop_uri,
                    })

            contexts_list.append({
                "id": key,
                "label": info["label"],
                "description": info["description"],
                "contextUrl": info["contextUrl"],
                "properties": properties,
                "commonTypes": ctx_data.get("commonTypes", []),
            })

    return jsonify({"contexts": contexts_list})


@app.route("/api/context/upload", methods=["POST"])
def upload_context():
    """Upload a custom context JSON file."""
    if "file" not in request.files:
        return jsonify({"error": "Nessun file caricato"}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "Nome file vuoto"}), 400

    try:
        content = file.read().decode("utf-8")
        ctx_data = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        return jsonify({"error": f"File JSON non valido: {str(e)}"}), 400

    if "@context" not in ctx_data:
        return jsonify({"error": "Il file deve contenere una chiave '@context' valida"}), 400

    ctx_obj = ctx_data["@context"]
    properties = []
    for prop_name, prop_uri in ctx_obj.items():
        if prop_name.startswith("@"):
            continue
        if isinstance(prop_uri, str) and prop_uri.startswith("http"):
            properties.append({
                "name": prop_name,
                "uri": prop_uri,
            })

    return jsonify({
        "label": file.filename.rsplit(".", 1)[0],
        "description": "Contesto personalizzato",
        "contextUrl": "",
        "properties": properties,
        "commonTypes": ctx_data.get("commonTypes", []),
        "rawContext": ctx_data,
        "isCustom": True,
    })


@app.route("/api/convert", methods=["POST"])
def start_conversion():
    """Start a JSON-LD conversion job."""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Richiesta JSON non valida"}), 400

    job_id = data.get("job_id")
    context_data = data.get("context")
    mapping = data.get("mapping", {})
    entity_type = data.get("entity_type", "")
    base_iri = data.get("base_iri", "")

    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            return jsonify({"error": "Sessione di upload non trovata. Carica prima un file CSV."}), 404

        if job.get("status") == "processing":
            return jsonify({"error": "Conversione già in corso"}), 409

        job["status"] = "queued"
        job["mapping"] = mapping
        job["context"] = context_data if context_data else {}
        job["entity_type"] = entity_type if entity_type else None
        job["base_iri"] = base_iri if base_iri else ""
        job["progress"] = 0

    # Start background conversion
    thread = threading.Thread(target=run_conversion_job, args=(job_id,), daemon=True)
    thread.start()

    return jsonify({"job_id": job_id, "status": "queued"})


@app.route("/api/job/<job_id>", methods=["GET"])
def job_status(job_id: str):
    """Get the status of a conversion job."""
    with jobs_lock:
        job = jobs.get(job_id)

    if not job:
        return jsonify({"error": "Job non trovato"}), 404

    response = {
        "job_id": job_id,
        "status": job["status"],
        "progress": job.get("progress", 0),
    }
    if job["status"] == "completed":
        response["validation"] = job.get("validation", {})
    elif job["status"] == "error":
        response["error"] = job.get("error", "Errore sconosciuto")

    return jsonify(response)


@app.route("/api/download/<job_id>", methods=["GET"])
def download_result(job_id: str):
    """Download the JSON-LD result file."""
    with jobs_lock:
        job = jobs.get(job_id)

    if not job or job.get("status") != "completed":
        return jsonify({"error": "Risultato non disponibile"}), 404

    result = job["result"]
    json_str = json.dumps(result, indent=2, ensure_ascii=False)

    # Create a BytesIO response
    buffer = io.BytesIO()
    buffer.write(json_str.encode("utf-8"))
    buffer.seek(0)

    return send_file(
        buffer,
        mimetype="application/ld+json",
        as_attachment=True,
        download_name="output.jsonld",
    )


@app.route("/api/preview/<job_id>", methods=["GET"])
def preview_result(job_id: str):
    """Get a preview of the JSON-LD result."""
    with jobs_lock:
        job = jobs.get(job_id)

    if not job or job.get("status") != "completed":
        return jsonify({"error": "Risultato non disponibile"}), 404

    result = job["result"]
    return jsonify(result)


@app.route("/api/health", methods=["GET"])
def health():
    """Health check endpoint."""
    return jsonify({"status": "ok"})


# ---------------------------------------------------------------------------
# Static files: robots.txt, sitemap.xml
# ---------------------------------------------------------------------------
@app.route("/robots.txt")
def robots_txt():
    content = """User-agent: *
Allow: /
Sitemap: https://github.com/bonciarello/convertitore-di-file-csv-a-json-ld-con-mapping-semantico/sitemap.xml
"""
    response = make_response(content)
    response.headers["Content-Type"] = "text/plain"
    return response


@app.route("/sitemap.xml")
def sitemap_xml():
    content = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>https://github.com/bonciarello/convertitore-di-file-csv-a-json-ld-con-mapping-semantico/</loc>
    <changefreq>monthly</changefreq>
    <priority>0.8</priority>
  </url>
</urlset>"""
    response = make_response(content)
    response.headers["Content-Type"] = "application/xml"
    return response


# ---------------------------------------------------------------------------
# Cleanup old jobs (run periodically)
# ---------------------------------------------------------------------------
def cleanup_old_jobs():
    """Remove jobs older than 30 minutes."""
    while True:
        time.sleep(300)  # every 5 minutes
        now = time.time()
        with jobs_lock:
            to_remove = [
                jid for jid, j in jobs.items()
                if now - j.get("created_at", now) > 1800
            ]
            for jid in to_remove:
                del jobs[jid]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Start cleanup thread
    cleanup_thread = threading.Thread(target=cleanup_old_jobs, daemon=True)
    cleanup_thread.start()

    port = int(os.environ.get("PORT", 4600))
    print(f"🔄 CSV → JSON-LD Converter running on http://0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
