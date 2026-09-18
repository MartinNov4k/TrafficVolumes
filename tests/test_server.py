import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request

from trafficvolumes.model import LinkDirection, ValueField
from trafficvolumes.server import content_disposition, serve
from trafficvolumes.storage import Project


class ServerTestCase(unittest.TestCase):
    token = ""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.project = Project.create(
            os.path.join(self.dir.name, "p.tvol"),
            [
                LinkDirection("1", "10", "11", [(14.4, 50.1), (14.5, 50.2)], name="Husova"),
                LinkDirection("1", "11", "10", [(14.5, 50.2), (14.4, 50.1)], name="Husova"),
            ],
            fields=[ValueField("VOL_MANUAL", "Intenzita", "int", "voz/den")],
            name="Sčítání 2026",
            crs="EPSG:4326",
            coord_mode="geographic",
        )
        self.httpd = serve(
            self.project, host="127.0.0.1", port=0, token=self.token,
            read_only=getattr(self, "read_only", False),
        )
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)
        self.project.close()
        self.dir.cleanup()

    def request(self, path, method="GET", body=None, token=None):
        url = self.base + path
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(url, data=data, method=method)
        if data:
            request.add_header("Content-Type", "application/json")
        use_token = self.token if token is None else token
        if use_token:
            request.add_header("X-Auth-Token", use_token)
        with urllib.request.urlopen(request, timeout=10) as response:
            raw = response.read()
            return response.status, response.headers, raw


class ApiTest(ServerTestCase):
    def test_serves_the_page(self):
        status, headers, body = self.request("/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers["Content-Type"])
        self.assertIn(b"TrafficVolumes", body)

    def test_serves_the_scripts(self):
        for path in ("/app.js", "/map.js", "/style.css"):
            status, _, body = self.request(path)
            self.assertEqual(status, 200, path)
            self.assertTrue(body)

    def test_project_metadata(self):
        _, _, body = self.request("/api/project")
        data = json.loads(body)
        self.assertEqual(data["name"], "Sčítání 2026")
        self.assertEqual(data["coord_mode"], "geographic")
        self.assertEqual(data["fields"][0]["name"], "VOL_MANUAL")
        self.assertEqual(data["stats"]["total"], 2)

    def test_links_and_bbox(self):
        _, _, body = self.request("/api/links")
        self.assertEqual(json.loads(body)["count"], 2)
        _, _, body = self.request("/api/links?bbox=20,20,21,21")
        self.assertEqual(json.loads(body)["count"], 0)

    def test_save_and_read_back(self):
        key = urllib.parse.quote("1|10|11", safe="")
        status, _, body = self.request(
            f"/api/link/{key}", "POST", {"values": {"VOL_MANUAL": "1500"}, "surveyor": "N"}
        )
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["values"]["VOL_MANUAL"], "1500")
        _, _, body = self.request("/api/stats")
        self.assertEqual(json.loads(body)["filled"], 1)

    def test_delete_clears_the_values(self):
        key = urllib.parse.quote("1|10|11", safe="")
        self.request(f"/api/link/{key}", "POST", {"values": {"VOL_MANUAL": "1500"}})
        self.request(f"/api/link/{key}", "DELETE")
        _, _, body = self.request("/api/stats")
        self.assertEqual(json.loads(body)["filled"], 0)

    def test_history_endpoint(self):
        key = urllib.parse.quote("1|10|11", safe="")
        self.request(f"/api/link/{key}", "POST", {"values": {"VOL_MANUAL": "1500"}})
        _, _, body = self.request(f"/api/link/{key}/history")
        self.assertEqual(len(json.loads(body)["history"]), 1)

    def test_att_export_with_a_czech_project_name(self):
        """A non-ASCII name must not break the Content-Disposition header."""
        key = urllib.parse.quote("1|10|11", safe="")
        self.request(f"/api/link/{key}", "POST", {"values": {"VOL_MANUAL": "1500"}})
        status, headers, body = self.request("/api/export/att")
        self.assertEqual(status, 200)
        self.assertIn("filename*=UTF-8''", headers["Content-Disposition"])
        self.assertIn("1;10;11;1500", body.decode("cp1250"))

    def test_csv_and_geojson_exports(self):
        _, headers, body = self.request("/api/export/csv")
        self.assertIn("text/csv", headers["Content-Type"])
        _, _, body = self.request("/api/export/geojson")
        self.assertEqual(len(json.loads(body)["features"]), 2)

    def test_visum_script_export(self):
        _, _, body = self.request("/api/export/visum-script")
        compile(body.decode(), "snippet.py", "exec")


class ErrorTest(ServerTestCase):
    def expect_error(self, path, status, method="GET", body=None):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request(path, method, body)
        self.assertEqual(caught.exception.code, status)
        return json.loads(caught.exception.read())

    def test_unknown_endpoint(self):
        self.expect_error("/api/nope", 404)

    def test_unknown_link(self):
        self.expect_error("/api/link/9%7C1%7C2", 404)

    def test_invalid_value_is_rejected(self):
        key = urllib.parse.quote("1|10|11", safe="")
        payload = self.expect_error(
            f"/api/link/{key}", 400, "POST", {"values": {"VOL_MANUAL": "abc"}}
        )
        self.assertIn("number", payload["error"])

    def test_unknown_field_is_rejected(self):
        key = urllib.parse.quote("1|10|11", safe="")
        self.expect_error(f"/api/link/{key}", 400, "POST", {"values": {"NOPE": "1"}})

    def test_values_must_be_an_object(self):
        key = urllib.parse.quote("1|10|11", safe="")
        self.expect_error(f"/api/link/{key}", 400, "POST", {"values": "1500"})

    def test_bad_bbox(self):
        self.expect_error("/api/links?bbox=1,2", 400)

    def test_directory_traversal_is_refused(self):
        self.expect_error("/../trafficvolumes/cli.py", 404)
        self.expect_error("/%2e%2e/%2e%2e/etc/passwd", 404)

    def test_unknown_export_format(self):
        self.expect_error("/api/export/pdf", 404)


class TokenTest(ServerTestCase):
    token = "s3cret"

    def test_request_without_a_token_is_refused(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request("/api/project", token="")
        self.assertEqual(caught.exception.code, 403)

    def test_request_with_the_token_passes(self):
        status, _, _ = self.request("/api/project")
        self.assertEqual(status, 200)

    def test_wrong_token_is_refused(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request("/api/project", token="wrong")
        self.assertEqual(caught.exception.code, 403)

    def test_token_in_the_query_string_works(self):
        status, _, _ = self.request("/api/project?t=s3cret", token="")
        self.assertEqual(status, 200)

    def test_static_files_stay_public(self):
        status, _, _ = self.request("/", token="")
        self.assertEqual(status, 200)


class ReadOnlyTest(ServerTestCase):
    read_only = True

    def test_saving_is_refused(self):
        key = urllib.parse.quote("1|10|11", safe="")
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request(f"/api/link/{key}", "POST", {"values": {"VOL_MANUAL": "1"}})
        self.assertEqual(caught.exception.code, 403)

    def test_reading_still_works(self):
        status, _, _ = self.request("/api/links")
        self.assertEqual(status, 200)


class ContentDispositionTest(unittest.TestCase):
    def test_ascii_fallback_and_utf8_form(self):
        header = content_disposition("Sčítání_2026.att")
        self.assertIn('filename="Scitani_2026.att"', header)
        self.assertIn("filename*=UTF-8''S%C4%8D", header)
        self.assertEqual(header, header.encode("latin-1").decode("latin-1"))

    def test_name_without_ascii_characters(self):
        header = content_disposition("上海.att")
        self.assertIn('filename="export.att"', header)


if __name__ == "__main__":
    unittest.main()
