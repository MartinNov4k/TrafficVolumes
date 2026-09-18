import json
import os
import tempfile
import unittest

from trafficvolumes import importers
from trafficvolumes.model import LinkDirection


def write(suffix, text, encoding="utf-8"):
    handle = tempfile.NamedTemporaryFile("wb", suffix=suffix, delete=False)
    handle.write(text.encode(encoding))
    handle.close()
    return handle.name


class WktTest(unittest.TestCase):
    def test_linestring(self):
        self.assertEqual(
            importers.parse_wkt("LINESTRING(1 2, 3 4)"), [(1.0, 2.0), (3.0, 4.0)]
        )

    def test_multilinestring_is_flattened(self):
        self.assertEqual(
            importers.parse_wkt("MULTILINESTRING((0 0, 1 1),(1 1, 2 2))"),
            [(0.0, 0.0), (1.0, 1.0), (2.0, 2.0)],
        )

    def test_z_coordinates_are_dropped(self):
        self.assertEqual(importers.parse_wkt("LINESTRING Z (0 0 5, 1 1 6)"), [(0.0, 0.0), (1.0, 1.0)])

    def test_garbage(self):
        self.assertEqual(importers.parse_wkt("nonsense"), [])
        self.assertEqual(importers.parse_wkt(""), [])


class AttImportTest(unittest.TestCase):
    def test_geometry_from_wktpoly(self):
        path = write(".att", (
            "$LINK:NO;FROMNODENO;TONODENO;NAME;WKTPOLY\n"
            "1;10;11;Husova;LINESTRING(0 0, 5 5)\n"
        ))
        try:
            result = importers.import_att(path)
            self.assertEqual(result.geometry_source, "WKTPOLY")
            self.assertEqual(result.links[0].geometry, [(0.0, 0.0), (5.0, 5.0)])
            self.assertEqual(result.links[0].name, "Husova")
        finally:
            os.unlink(path)

    def test_geometry_from_node_table(self):
        path = write(".att", (
            "$NODE:NO;XCOORD;YCOORD\n10;0;0\n11;100;50\n"
            "$LINK:NO;FROMNODENO;TONODENO\n1;10;11\n"
        ))
        try:
            result = importers.import_att(path)
            self.assertEqual(result.geometry_source, "$NODE")
            self.assertEqual(result.links[0].geometry, [(0.0, 0.0), (100.0, 50.0)])
        finally:
            os.unlink(path)

    def test_intermediate_points_from_linkpoly(self):
        path = write(".att", (
            "$NODE:NO;XCOORD;YCOORD\n10;0;0\n11;100;0\n"
            "$LINK:NO;FROMNODENO;TONODENO\n1;10;11\n"
            "$LINKPOLY:LINKNO;FROMNODENO;TONODENO;INDEX;XCOORD;YCOORD\n"
            "1;10;11;2;70;20\n1;10;11;1;30;20\n"
        ))
        try:
            result = importers.import_att(path)
            self.assertEqual(result.geometry_source, "$LINKPOLY")
            self.assertEqual(
                result.links[0].geometry,
                [(0.0, 0.0), (30.0, 20.0), (70.0, 20.0), (100.0, 0.0)],
            )
        finally:
            os.unlink(path)

    def test_relation_coordinate_columns(self):
        path = write(".att", (
            "$LINK:NO;FROMNODENO;TONODENO;FROMNODE\\XCOORD;FROMNODE\\YCOORD;"
            "TONODE\\XCOORD;TONODE\\YCOORD\n1;10;11;0;0;10;10\n"
        ))
        try:
            result = importers.import_att(path)
            self.assertEqual(result.links[0].geometry, [(0.0, 0.0), (10.0, 10.0)])
        finally:
            os.unlink(path)

    def test_missing_key_columns_explain_themselves(self):
        path = write(".att", "$LINK:NAME;WKTPOLY\nHusova;LINESTRING(0 0, 1 1)\n")
        try:
            with self.assertRaises(importers.ImportError_) as caught:
                importers.import_att(path)
            self.assertIn("FROMNODENO", str(caught.exception))
        finally:
            os.unlink(path)

    def test_missing_link_table(self):
        path = write(".att", "$NODE:NO;XCOORD;YCOORD\n1;0;0\n")
        try:
            with self.assertRaises(importers.ImportError_):
                importers.import_att(path)
        finally:
            os.unlink(path)

    def test_rows_without_geometry_are_reported(self):
        path = write(".att", (
            "$LINK:NO;FROMNODENO;TONODENO;WKTPOLY\n"
            "1;10;11;LINESTRING(0 0, 1 1)\n2;11;12;\n"
        ))
        try:
            result = importers.import_att(path)
            self.assertEqual(len(result.links), 1)
            self.assertTrue(any("skipped" in w for w in result.warnings))
        finally:
            os.unlink(path)


class CsvImportTest(unittest.TestCase):
    def test_semicolon_list_export(self):
        path = write(".csv", (
            "NO;FROMNODENO;TONODENO;NAME;WKTPOLY\n"
            "1;10;11;Husova;LINESTRING(0 0, 1 1)\n"
        ))
        try:
            result = importers.import_csv(path)
            self.assertEqual(len(result.links), 1)
            self.assertEqual(result.links[0].link_no, "1")
        finally:
            os.unlink(path)


class GeoJsonImportTest(unittest.TestCase):
    def test_feature_collection(self):
        data = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "LineString", "coordinates": [[14.4, 50.1], [14.5, 50.2]]},
                    "properties": {"NO": "1", "FROMNODENO": "10", "TONODENO": "11"},
                }
            ],
        }
        path = write(".geojson", json.dumps(data))
        try:
            result = importers.import_geojson(path)
            self.assertEqual(result.links[0].geometry, [(14.4, 50.1), (14.5, 50.2)])
            self.assertNotIn("__GEOM__", result.links[0].attrs)
        finally:
            os.unlink(path)


class OrientationTest(unittest.TestCase):
    def test_reverse_direction_is_flipped(self):
        forward = LinkDirection("1", "10", "11", [(0.0, 0.0), (1.0, 1.0), (2.0, 0.0)])
        reverse = LinkDirection("1", "11", "10", [(0.0, 0.0), (1.0, 1.0), (2.0, 0.0)])
        importers.orient_directions([forward, reverse])
        self.assertEqual(reverse.geometry, [(2.0, 0.0), (1.0, 1.0), (0.0, 0.0)])
        self.assertEqual(forward.geometry[0], reverse.geometry[-1])

    def test_already_oriented_geometry_is_left_alone(self):
        forward = LinkDirection("1", "10", "11", [(0.0, 0.0), (2.0, 0.0)])
        reverse = LinkDirection("1", "11", "10", [(2.0, 0.0), (0.0, 0.0)])
        importers.orient_directions([forward, reverse])
        self.assertEqual(reverse.geometry, [(2.0, 0.0), (0.0, 0.0)])

    def test_one_way_link_survives(self):
        only = LinkDirection("1", "10", "11", [(0.0, 0.0), (2.0, 0.0)])
        self.assertEqual(len(importers.orient_directions([only])), 1)


class ValueRecordTest(unittest.TestCase):
    def test_reads_att_values(self):
        path = write(".att", "$LINK:NO;FROMNODENO;TONODENO;VOL_MANUAL\n1;10;11;1500\n1;11;10;\n")
        try:
            records = importers.read_value_records(path)
            self.assertEqual(records, [("1", "10", "11", {"VOL_MANUAL": "1500"})])
        finally:
            os.unlink(path)

    def test_skips_bookkeeping_columns(self):
        path = write(".csv", (
            "NO;FROMNODENO;TONODENO;NAME;VOL_MANUAL;NOTE;SURVEYOR;UPDATED_AT\n"
            "1;10;11;Husova;1500;pozn;Novák;2026-01-01\n"
        ))
        try:
            records = importers.read_value_records(path)
            self.assertEqual(records[0][3], {"VOL_MANUAL": "1500"})
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
