"""
Tests for CSV → JSON-LD Converter
"""

import io
import json
import os
import sys
import unittest
import tempfile

# Add parent to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server import app, parse_csv_preview, generate_jsonld, build_jsonld_document, load_context_file, coerce_value


class TestCSVParsing(unittest.TestCase):
    """Test CSV parsing functionality."""

    def test_parse_simple_csv(self):
        content = "Name,Age,Email\nAlice,30,alice@example.com\nBob,25,bob@example.com"
        result = parse_csv_preview(content)
        self.assertEqual(result["headers"], ["Name", "Age", "Email"])
        self.assertEqual(result["rowCount"], 2)
        self.assertEqual(len(result["preview"]), 2)
        self.assertEqual(result["preview"][0]["Name"], "Alice")
        self.assertEqual(result["preview"][0]["Age"], "30")
        self.assertEqual(result["delimiter"], ",")

    def test_parse_semicolon_csv(self):
        content = "Name;Age;Email\nAlice;30;alice@example.com\nBob;25;bob@example.com"
        result = parse_csv_preview(content)
        self.assertEqual(result["headers"], ["Name", "Age", "Email"])
        self.assertEqual(result["rowCount"], 2)
        self.assertIn(result["delimiter"], [",", ";"])

    def test_parse_tab_csv(self):
        content = "Name\tAge\tEmail\nAlice\t30\talice@example.com"
        result = parse_csv_preview(content)
        self.assertEqual(result["headers"], ["Name", "Age", "Email"])
        self.assertEqual(result["rowCount"], 1)

    def test_parse_empty_csv(self):
        content = ""
        result = parse_csv_preview(content)
        self.assertEqual(result["headers"], [])
        self.assertEqual(result["rowCount"], 0)
        self.assertEqual(result["preview"], [])

    def test_parse_header_only(self):
        content = "Name,Age,Email"
        result = parse_csv_preview(content)
        self.assertEqual(result["headers"], ["Name", "Age", "Email"])
        self.assertEqual(result["rowCount"], 0)
        self.assertEqual(result["preview"], [])

    def test_parse_with_whitespace_headers(self):
        content = "  Name , Age , Email \nAlice,30,alice@example.com"
        result = parse_csv_preview(content)
        self.assertEqual(result["headers"], ["Name", "Age", "Email"])


class TestJSONLDGeneration(unittest.TestCase):
    """Test JSON-LD generation."""

    def setUp(self):
        self.context = {
            "@context": {
                "name": "https://schema.org/name",
                "birthDate": "https://schema.org/birthDate",
                "url": "https://schema.org/url",
            }
        }

    def test_generate_single_entity(self):
        rows = [{"Name": "Alice", "DateOfBirth": "1990-01-15", "URL": "https://alice.example.com"}]
        mapping = {
            "Name": {"property": "name", "datatype": "string"},
            "DateOfBirth": {"property": "birthDate", "datatype": "date"},
            "URL": {"property": "url", "datatype": "url"},
        }
        entities = generate_jsonld(rows, mapping, self.context, entity_type="Person")
        self.assertEqual(len(entities), 1)
        self.assertEqual(entities[0]["@type"], "Person")
        self.assertEqual(entities[0]["name"], "Alice")
        self.assertEqual(entities[0]["birthDate"], "1990-01-15")
        self.assertEqual(entities[0]["url"], "https://alice.example.com")

    def test_generate_multiple_entities(self):
        rows = [
            {"Name": "Alice", "Age": "30"},
            {"Name": "Bob", "Age": "25"},
            {"Name": "Charlie", "Age": "35"},
        ]
        mapping = {
            "Name": {"property": "name", "datatype": "string"},
            "Age": {"property": "age", "datatype": "integer"},
        }
        entities = generate_jsonld(rows, mapping, self.context)
        self.assertEqual(len(entities), 3)
        self.assertEqual(entities[0]["name"], "Alice")
        self.assertEqual(entities[1]["name"], "Bob")
        self.assertEqual(entities[2]["name"], "Charlie")
        self.assertEqual(entities[0]["age"], 30)       # coerced to int
        self.assertEqual(entities[1]["age"], 25)

    def test_generate_with_base_iri(self):
        rows = [{"Name": "Test"}]
        mapping = {"Name": {"property": "name", "datatype": "string"}}
        entities = generate_jsonld(rows, mapping, self.context, base_iri="https://example.org/data/")
        self.assertEqual(entities[0]["@id"], "https://example.org/data/item-1")

    def test_generate_without_base_iri(self):
        rows = [{"Name": "Test"}]
        mapping = {"Name": {"property": "name", "datatype": "string"}}
        entities = generate_jsonld(rows, mapping, self.context)
        self.assertEqual(entities[0]["@id"], "_:item-1")

    def test_generate_with_no_entity_type(self):
        rows = [{"Name": "Test"}]
        mapping = {"Name": {"property": "name", "datatype": "string"}}
        entities = generate_jsonld(rows, mapping, self.context)
        self.assertNotIn("@type", entities[0])

    def test_generate_skips_unmapped_columns(self):
        rows = [{"Name": "Alice", "Extra": "ignored"}]
        mapping = {"Name": {"property": "name", "datatype": "string"}}
        entities = generate_jsonld(rows, mapping, self.context)
        self.assertEqual(len(entities), 1)
        self.assertNotIn("Extra", entities[0])

    def test_generate_skips_empty_values(self):
        rows = [{"Name": "", "URL": "https://example.com"}]
        mapping = {
            "Name": {"property": "name", "datatype": "string"},
            "URL": {"property": "url", "datatype": "url"},
        }
        entities = generate_jsonld(rows, mapping, self.context)
        self.assertEqual(len(entities), 1)
        self.assertNotIn("name", entities[0])
        self.assertEqual(entities[0]["url"], "https://example.com")


class TestValueCoercion(unittest.TestCase):
    """Test datatype coercion."""

    def test_coerce_string(self):
        self.assertEqual(coerce_value("hello", "string"), "hello")

    def test_coerce_integer(self):
        self.assertEqual(coerce_value("42", "integer"), 42)
        self.assertEqual(coerce_value("  42  ", "integer"), 42)

    def test_coerce_integer_invalid(self):
        self.assertEqual(coerce_value("abc", "integer"), "abc")

    def test_coerce_float(self):
        self.assertEqual(coerce_value("3.14", "float"), 3.14)
        self.assertEqual(coerce_value("42", "float"), 42.0)

    def test_coerce_boolean(self):
        self.assertEqual(coerce_value("true", "boolean"), True)
        self.assertEqual(coerce_value("True", "boolean"), True)
        self.assertEqual(coerce_value("TRUE", "boolean"), True)
        self.assertEqual(coerce_value("yes", "boolean"), True)
        self.assertEqual(coerce_value("1", "boolean"), True)
        self.assertEqual(coerce_value("false", "boolean"), False)
        self.assertEqual(coerce_value("False", "boolean"), False)
        self.assertEqual(coerce_value("no", "boolean"), False)
        self.assertEqual(coerce_value("0", "boolean"), False)
        self.assertEqual(coerce_value("", "boolean"), False)

    def test_coerce_date_url(self):
        self.assertEqual(coerce_value("2024-01-15", "date"), "2024-01-15")
        self.assertEqual(coerce_value("https://example.com", "url"), "https://example.com")


class TestBuildDocument(unittest.TestCase):
    """Test document building."""

    def setUp(self):
        self.context = {"@context": {"name": "https://schema.org/name"}}

    def test_single_entity_no_graph(self):
        entities = [{"@id": "_:item-1", "name": "Alice"}]
        doc = build_jsonld_document(entities, self.context)
        self.assertNotIn("@graph", doc)
        self.assertEqual(doc["@context"], {"name": "https://schema.org/name"})
        self.assertEqual(doc["name"], "Alice")

    def test_multiple_entities_with_graph(self):
        entities = [
            {"@id": "_:item-1", "name": "Alice"},
            {"@id": "_:item-2", "name": "Bob"},
        ]
        doc = build_jsonld_document(entities, self.context)
        self.assertIn("@graph", doc)
        self.assertEqual(len(doc["@graph"]), 2)


class TestContextLoading(unittest.TestCase):
    """Test loading of predefined contexts."""

    def test_load_schema_org(self):
        ctx = load_context_file("schema.org.json")
        self.assertIsNotNone(ctx)
        self.assertIn("@context", ctx)
        self.assertIn("name", ctx["@context"])
        self.assertIn("description", ctx["@context"])
        self.assertIn("url", ctx["@context"])
        self.assertIn("commonTypes", ctx)
        self.assertIn("Person", ctx["commonTypes"])

    def test_load_foaf(self):
        ctx = load_context_file("foaf.json")
        self.assertIsNotNone(ctx)
        self.assertIn("@context", ctx)
        self.assertIn("name", ctx["@context"])
        self.assertIn("mbox", ctx["@context"])
        self.assertIn("homepage", ctx["@context"])
        self.assertIn("commonTypes", ctx)
        self.assertIn("Person", ctx["commonTypes"])

    def test_load_dcat(self):
        ctx = load_context_file("dcat.json")
        self.assertIsNotNone(ctx)
        self.assertIn("@context", ctx)
        self.assertIn("title", ctx["@context"])
        self.assertIn("description", ctx["@context"])
        self.assertIn("keyword", ctx["@context"])
        self.assertIn("commonTypes", ctx)
        self.assertIn("Dataset", ctx["commonTypes"])

    def test_load_nonexistent(self):
        ctx = load_context_file("nonexistent.json")
        self.assertIsNone(ctx)


class TestAPIEndpoints(unittest.TestCase):
    """Test Flask API endpoints."""

    def setUp(self):
        app.config['TESTING'] = True
        self.client = app.test_client()

    def test_index(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"<!DOCTYPE html>", resp.data)

    def test_health(self):
        resp = self.client.get("/api/health")
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertEqual(data["status"], "ok")

    def test_contexts_list(self):
        resp = self.client.get("/api/contexts")
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertIn("contexts", data)
        self.assertGreaterEqual(len(data["contexts"]), 3)
        ctx_ids = [c["id"] for c in data["contexts"]]
        self.assertIn("schema.org", ctx_ids)
        self.assertIn("foaf", ctx_ids)
        self.assertIn("dcat", ctx_ids)

    def test_upload_csv(self):
        csv_content = "Name,Age,Email\nAlice,30,alice@example.com\nBob,25,bob@example.com"
        data = {"file": (io.BytesIO(csv_content.encode("utf-8")), "test.csv")}
        resp = self.client.post("/api/upload", data=data, content_type="multipart/form-data")
        self.assertEqual(resp.status_code, 200)
        result = json.loads(resp.data)
        self.assertEqual(result["headers"], ["Name", "Age", "Email"])
        self.assertEqual(result["rowCount"], 2)
        self.assertIn("job_id", result)

    def test_upload_no_file(self):
        resp = self.client.post("/api/upload", data={}, content_type="multipart/form-data")
        self.assertEqual(resp.status_code, 400)
        data = json.loads(resp.data)
        self.assertIn("error", data)

    def test_convert_without_upload(self):
        resp = self.client.post("/api/convert", json={"job_id": "nonexistent"})
        self.assertEqual(resp.status_code, 404)

    def test_full_conversion_flow(self):
        """End-to-end test: upload CSV, convert, check result."""
        csv_content = "Name,DateOfBirth,URL\nAlice,1990-01-15,https://alice.example.com\nBob,1985-06-20,https://bob.example.com"
        data = {"file": (io.BytesIO(csv_content.encode("utf-8")), "test.csv")}
        resp = self.client.post("/api/upload", data=data, content_type="multipart/form-data")
        self.assertEqual(resp.status_code, 200)
        result = json.loads(resp.data)
        job_id = result["job_id"]

        # Load context
        ctx = load_context_file("schema.org.json")
        self.assertIsNotNone(ctx)

        # Start conversion
        convert_data = {
            "job_id": job_id,
            "context": ctx,
            "mapping": {
                "Name": {"property": "name", "datatype": "string"},
                "DateOfBirth": {"property": "birthDate", "datatype": "date"},
                "URL": {"property": "url", "datatype": "url"},
            },
            "entity_type": "Person",
            "base_iri": "https://example.org/",
        }
        resp = self.client.post("/api/convert", json=convert_data)
        self.assertEqual(resp.status_code, 200)
        convert_result = json.loads(resp.data)
        self.assertEqual(convert_result["status"], "queued")

        # Poll until complete (with timeout)
        import time
        max_wait = 10
        elapsed = 0
        while elapsed < max_wait:
            resp = self.client.get(f"/api/job/{job_id}")
            self.assertEqual(resp.status_code, 200)
            status = json.loads(resp.data)
            if status["status"] == "completed":
                break
            if status["status"] == "error":
                self.fail(f"Conversion failed: {status.get('error')}")
            time.sleep(0.2)
            elapsed += 0.2

        self.assertLess(elapsed, max_wait, "Conversion timed out")

        # Check result
        resp = self.client.get(f"/api/preview/{job_id}")
        self.assertEqual(resp.status_code, 200)
        doc = json.loads(resp.data)
        self.assertIn("@context", doc)

        # Check entities
        if "@graph" in doc:
            entities = doc["@graph"]
        else:
            entities = [doc]
        self.assertEqual(len(entities), 2)
        self.assertEqual(entities[0]["name"], "Alice")
        self.assertEqual(entities[0]["@type"], "Person")

        # Download
        resp = self.client.get(f"/api/download/{job_id}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.content_type, "application/ld+json")

    def test_robots_txt(self):
        resp = self.client.get("/robots.txt")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Sitemap:", resp.data)

    def test_sitemap_xml(self):
        resp = self.client.get("/sitemap.xml")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"<urlset", resp.data)
        self.assertIn(b"cristianporco.it", resp.data)


class TestAcceptanceCriteria(unittest.TestCase):
    """Test the acceptance criteria from the requirements."""

    def setUp(self):
        app.config['TESTING'] = True
        self.client = app.test_client()

    def test_acceptance_csv_to_jsonld(self):
        """Given a CSV with Name, DateOfBirth, URL columns, user maps them to
        foaf:name, schema:birthDate, schema:url and the tool generates valid JSON-LD."""
        import time

        csv_content = "Name,DateOfBirth,URL\nMario Rossi,1980-03-15,https://mario.example.com\nLuisa Bianchi,1992-07-22,https://luisa.example.com"
        data = {"file": (io.BytesIO(csv_content.encode("utf-8")), "test.csv")}
        resp = self.client.post("/api/upload", data=data, content_type="multipart/form-data")
        self.assertEqual(resp.status_code, 200)
        result = json.loads(resp.data)
        job_id = result["job_id"]

        # Use a context with both foaf and schema properties
        context = {
            "@context": {
                "name": "http://xmlns.com/foaf/0.1/name",
                "birthDate": "https://schema.org/birthDate",
                "url": "https://schema.org/url",
            }
        }

        convert_data = {
            "job_id": job_id,
            "context": context,
            "mapping": {
                "Name": {"property": "name", "datatype": "string"},
                "DateOfBirth": {"property": "birthDate", "datatype": "date"},
                "URL": {"property": "url", "datatype": "url"},
            },
            "entity_type": "Person",
        }
        resp = self.client.post("/api/convert", json=convert_data)
        self.assertEqual(resp.status_code, 200)

        # Wait for completion
        max_wait = 10
        elapsed = 0
        while elapsed < max_wait:
            resp = self.client.get(f"/api/job/{job_id}")
            status = json.loads(resp.data)
            if status["status"] == "completed":
                break
            if status["status"] == "error":
                self.fail(f"Conversion failed: {status.get('error')}")
            time.sleep(0.2)
            elapsed += 0.2

        # Check result validity
        resp = self.client.get(f"/api/preview/{job_id}")
        doc = json.loads(resp.data)
        self.assertIn("@context", doc)

        if "@graph" in doc:
            entities = doc["@graph"]
        else:
            entities = [doc]

        self.assertEqual(len(entities), 2)
        self.assertIn("name", entities[0])
        self.assertIn("birthDate", entities[0])
        self.assertIn("url", entities[0])


if __name__ == "__main__":
    unittest.main()
