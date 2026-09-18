import os
import tempfile
import unittest

from trafficvolumes.model import LinkDirection, ValueField
from trafficvolumes.storage import Project, StorageError


def sample_links():
    return [
        LinkDirection("1", "10", "11", [(0.0, 0.0), (1.0, 0.0)], name="Husova"),
        LinkDirection("1", "11", "10", [(1.0, 0.0), (0.0, 0.0)], name="Husova"),
        LinkDirection("2", "11", "12", [(1.0, 0.0), (1.0, 1.0)], name="Sokolská"),
    ]


class ProjectTestCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.dir.name, "p.tvol")
        self.project = Project.create(
            self.path,
            sample_links(),
            fields=[
                ValueField("VOL_MANUAL", "Intenzita", "int", "voz/den"),
                ValueField("VOL_HGV", "Nákladní", "int", "voz/den"),
            ],
            name="Test",
            crs="EPSG:5514",
            coord_mode="geographic",
        )

    def tearDown(self):
        self.project.close()
        self.dir.cleanup()


class CreationTest(ProjectTestCase):
    def test_stores_every_direction(self):
        self.assertEqual(self.project.stats().total, 3)

    def test_refuses_to_clobber_without_force(self):
        with self.assertRaises(StorageError):
            Project.create(self.path, sample_links())

    def test_overwrite_with_force(self):
        other = Project.create(self.path, sample_links()[:1], overwrite=True)
        self.assertEqual(other.stats().total, 1)
        other.close()

    def test_duplicate_directions_are_dropped(self):
        path = os.path.join(self.dir.name, "dup.tvol")
        links = sample_links() + [sample_links()[0]]
        project = Project.create(path, links)
        self.assertEqual(project.stats().total, 3)
        project.close()

    def test_rejects_a_foreign_database(self):
        path = os.path.join(self.dir.name, "not-a-project.tvol")
        with open(path, "wb") as fh:
            fh.write(b"not sqlite at all")
        with self.assertRaises(StorageError):
            Project.open(path)


class ValueTest(ProjectTestCase):
    def test_set_and_read_back(self):
        updated = self.project.set_values("1|10|11", {"VOL_MANUAL": "1500"}, surveyor="Novák")
        self.assertEqual(updated["values"]["VOL_MANUAL"], "1500")
        self.assertEqual(updated["status"], "filled")
        self.assertEqual(self.project.stats().filled, 1)

    def test_directions_are_independent(self):
        self.project.set_values("1|10|11", {"VOL_MANUAL": "1500"})
        self.project.set_values("1|11|10", {"VOL_MANUAL": "900"})
        self.assertEqual(self.project.get_link("1|10|11")["values"]["VOL_MANUAL"], "1500")
        self.assertEqual(self.project.get_link("1|11|10")["values"]["VOL_MANUAL"], "900")

    def test_reverse_key_is_reported(self):
        self.assertEqual(self.project.get_link("1|10|11")["reverse_key"], "1|11|10")
        self.assertIsNone(self.project.get_link("2|11|12")["reverse_key"])

    def test_czech_decimal_comma_is_accepted(self):
        project = Project.create(
            os.path.join(self.dir.name, "f.tvol"),
            sample_links(),
            fields=[ValueField("SPEED", "Rychlost", "float")],
        )
        updated = project.set_values("1|10|11", {"SPEED": "48,5"})
        self.assertEqual(updated["values"]["SPEED"], "48.5")
        project.close()

    def test_rejects_non_numbers(self):
        with self.assertRaises(ValueError):
            self.project.set_values("1|10|11", {"VOL_MANUAL": "abc"})

    def test_rejects_fractional_value_for_integer_field(self):
        with self.assertRaises(ValueError):
            self.project.set_values("1|10|11", {"VOL_MANUAL": "12.5"})

    def test_rejects_unknown_field(self):
        with self.assertRaises(StorageError):
            self.project.set_values("1|10|11", {"NOPE": "1"})

    def test_rejects_unknown_direction(self):
        with self.assertRaises(StorageError):
            self.project.set_values("9|1|2", {"VOL_MANUAL": "1"})

    def test_empty_string_clears_the_value(self):
        self.project.set_values("1|10|11", {"VOL_MANUAL": "1500"})
        self.project.set_values("1|10|11", {"VOL_MANUAL": ""})
        self.assertEqual(self.project.stats().filled, 0)
        self.assertEqual(self.project.get_link("1|10|11")["status"], "empty")

    def test_clear_values(self):
        self.project.set_values("1|10|11", {"VOL_MANUAL": "1500", "VOL_HGV": "80"})
        self.project.clear_values("1|10|11")
        self.assertEqual(self.project.get_link("1|10|11")["values"], {})

    def test_note_and_flag_are_kept(self):
        updated = self.project.set_values(
            "1|10|11", {"VOL_MANUAL": "1500"}, note="odhad", status="flagged"
        )
        self.assertEqual(updated["note"], "odhad")
        self.assertEqual(self.project.stats().flagged, 1)

    def test_history_records_every_change(self):
        self.project.set_values("1|10|11", {"VOL_MANUAL": "1500"}, surveyor="A")
        self.project.set_values("1|10|11", {"VOL_MANUAL": "1600"}, surveyor="B")
        history = self.project.history("1|10|11")
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["new_value"], "1600")
        self.assertEqual(history[0]["old_value"], "1500")
        self.assertEqual(history[0]["surveyor"], "B")

    def test_unchanged_value_does_not_grow_the_history(self):
        self.project.set_values("1|10|11", {"VOL_MANUAL": "1500"})
        self.project.set_values("1|10|11", {"VOL_MANUAL": "1500"})
        self.assertEqual(len(self.project.history("1|10|11")), 1)


class QueryTest(ProjectTestCase):
    def test_bbox_filter(self):
        links, _ = self.project.query_links(bbox=(0.9, -0.1, 1.1, 1.1))
        self.assertEqual({link["key"] for link in links}, {"1|10|11", "1|11|10", "2|11|12"})
        links, _ = self.project.query_links(bbox=(1.5, 1.5, 2.0, 2.0))
        self.assertEqual(links, [])

    def test_search_by_name_and_number(self):
        links, _ = self.project.query_links(search="sokol")
        self.assertEqual(len(links), 1)
        links, _ = self.project.query_links(search="12")
        self.assertEqual(len(links), 1)

    def test_only_empty(self):
        self.project.set_values("1|10|11", {"VOL_MANUAL": "1500"})
        links, _ = self.project.query_links(only_empty=True)
        self.assertNotIn("1|10|11", {link["key"] for link in links})

    def test_only_flagged(self):
        self.project.set_values("2|11|12", {"VOL_MANUAL": "1"}, status="flagged")
        links, _ = self.project.query_links(only_flagged=True)
        self.assertEqual([link["key"] for link in links], ["2|11|12"])

    def test_limit_reports_truncation(self):
        links, truncated = self.project.query_links(limit=1)
        self.assertEqual(len(links), 1)
        self.assertTrue(truncated)

    def test_bounds(self):
        self.assertEqual(self.project.bounds(), (0.0, 0.0, 1.0, 1.0))


class FieldTest(ProjectTestCase):
    def test_replacing_fields_drops_orphaned_values(self):
        self.project.set_values("1|10|11", {"VOL_MANUAL": "1500", "VOL_HGV": "80"})
        self.project.set_fields([ValueField("VOL_MANUAL", "Intenzita", "int")])
        link = self.project.get_link("1|10|11")
        self.assertEqual(link["values"], {"VOL_MANUAL": "1500"})

    def test_invalid_attribute_name_is_refused(self):
        with self.assertRaises(ValueError):
            ValueField("2 BAD NAME")


class MergeTest(ProjectTestCase):
    def test_import_values(self):
        updated, missing = self.project.import_values(
            [("1", "10", "11", {"VOL_MANUAL": "1500"}), ("9", "1", "2", {"VOL_MANUAL": "5"})]
        )
        self.assertEqual((updated, missing), (1, 1))

    def test_keep_existing(self):
        self.project.set_values("1|10|11", {"VOL_MANUAL": "1500"})
        self.project.import_values(
            [("1", "10", "11", {"VOL_MANUAL": "9999"})], overwrite=False
        )
        self.assertEqual(self.project.get_link("1|10|11")["values"]["VOL_MANUAL"], "1500")


if __name__ == "__main__":
    unittest.main()
