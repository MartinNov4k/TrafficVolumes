import json
import os
import tempfile
import unittest

from trafficvolumes import exporters, importers, visum_att
from trafficvolumes.model import LinkDirection, ValueField
from trafficvolumes.storage import Project


class ExportTestCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.project = Project.create(
            os.path.join(self.dir.name, "p.tvol"),
            [
                LinkDirection("1", "10", "11", [(14.4, 50.1), (14.5, 50.2)], name="Husova"),
                LinkDirection("1", "11", "10", [(14.5, 50.2), (14.4, 50.1)], name="Husova"),
                LinkDirection("2", "11", "12", [(14.5, 50.2), (14.5, 50.3)], name="Sokolská"),
            ],
            fields=[ValueField("VOL_MANUAL", "Intenzita", "int", "voz/den")],
            name="Sčítání",
            crs="EPSG:4326",
            coord_mode="geographic",
        )
        self.project.set_values("1|10|11", {"VOL_MANUAL": "12500"}, surveyor="Novák", note="ok")
        self.project.set_values("1|11|10", {"VOL_MANUAL": "9800"})

    def tearDown(self):
        self.project.close()
        self.dir.cleanup()


class AttExportTest(ExportTestCase):
    def test_writes_visum_key_columns(self):
        text = exporters.to_string(exporters.export_att, self.project)
        table = visum_att.find_table(visum_att.parse(text), "LINK")
        self.assertEqual(table.columns, ["NO", "FROMNODENO", "TONODENO", "VOL_MANUAL"])

    def test_only_filled_directions_by_default(self):
        text = exporters.to_string(exporters.export_att, self.project)
        table = visum_att.find_table(visum_att.parse(text), "LINK")
        self.assertEqual(len(table.rows), 2)

    def test_include_empty(self):
        text = exporters.to_string(exporters.export_att, self.project, include_empty=True)
        table = visum_att.find_table(visum_att.parse(text), "LINK")
        self.assertEqual(len(table.rows), 3)
        empty = [r for r in table.rows if r["NO"] == "2"][0]
        self.assertEqual(empty["VOL_MANUAL"], "")

    def test_both_directions_keep_their_own_value(self):
        text = exporters.to_string(exporters.export_att, self.project)
        table = visum_att.find_table(visum_att.parse(text), "LINK")
        values = {(r["FROMNODENO"], r["TONODENO"]): r["VOL_MANUAL"] for r in table.rows}
        self.assertEqual(values[("10", "11")], "12500")
        self.assertEqual(values[("11", "10")], "9800")

    def test_header_explains_the_user_attribute(self):
        text = exporters.to_string(exporters.export_att, self.project)
        self.assertIn("VOL_MANUAL", text)
        self.assertIn("Integer", text)
        self.assertTrue(text.startswith("$VISION"))

    def test_round_trips_through_the_value_reader(self):
        path = os.path.join(self.dir.name, "out.att")
        exporters.export_att_file(self.project, path)
        records = importers.read_value_records(path)
        self.assertEqual(
            sorted(records),
            [("1", "10", "11", {"VOL_MANUAL": "12500"}), ("1", "11", "10", {"VOL_MANUAL": "9800"})],
        )

    def test_float_field_uses_a_dot(self):
        project = Project.create(
            os.path.join(self.dir.name, "f.tvol"),
            [LinkDirection("1", "10", "11", [(0.0, 0.0), (1.0, 1.0)])],
            fields=[ValueField("SPEED", "Rychlost", "float")],
        )
        project.set_values("1|10|11", {"SPEED": "48,5"})
        text = exporters.to_string(exporters.export_att, project)
        self.assertIn("1;10;11;48.5", text)
        project.close()

    def test_cp1250_file_is_readable_again(self):
        path = os.path.join(self.dir.name, "cz.att")
        exporters.export_att_file(self.project, path)
        with open(path, "rb") as fh:
            raw = fh.read()
        self.assertIn("Sčítání", raw.decode("cp1250"))
        self.assertIn(b"\r\n", raw)


class CsvExportTest(ExportTestCase):
    def test_columns_and_rows(self):
        text = exporters.to_string(exporters.export_csv, self.project)
        lines = text.strip().splitlines()
        self.assertEqual(
            lines[0],
            "NO;FROMNODENO;TONODENO;NAME;VOL_MANUAL;NOTE;SURVEYOR;UPDATED_AT",
        )
        self.assertEqual(len(lines), 3)
        self.assertIn("Novák", text)


class GeoJsonExportTest(ExportTestCase):
    def test_feature_collection(self):
        data = json.loads(exporters.to_string(exporters.export_geojson, self.project))
        self.assertEqual(data["type"], "FeatureCollection")
        self.assertEqual(len(data["features"]), 3)
        first = data["features"][0]
        self.assertEqual(first["geometry"]["type"], "LineString")
        self.assertIn("VOL_MANUAL", first["properties"])

    def test_refuses_local_coordinates(self):
        project = Project.create(
            os.path.join(self.dir.name, "loc.tvol"),
            [LinkDirection("1", "10", "11", [(0.0, 0.0), (1.0, 1.0)])],
            coord_mode="local",
        )
        with self.assertRaises(ValueError):
            exporters.to_string(exporters.export_geojson, project)
        project.close()


class VisumSnippetTest(ExportTestCase):
    def test_snippet_is_valid_python_and_names_the_attribute(self):
        code = exporters.visum_snippet(self.project, "out.att")
        compile(code, "snippet.py", "exec")
        self.assertIn("VOL_MANUAL", code)
        self.assertIn("AddUserDefinedAttribute", code)
        self.assertIn("LoadAttributeFile", code)


if __name__ == "__main__":
    unittest.main()
