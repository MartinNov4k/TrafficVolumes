import unittest

from trafficvolumes import projection


class KrovakTest(unittest.TestCase):
    def test_matches_epsg_guidance_note(self):
        """The projection alone must reproduce the EPSG 9819 worked example.

        The published point is rounded to 0.0001", so agreement to five decimal
        places of a degree (about a metre) is all the example can demonstrate;
        in practice we land within a few centimetres of it.
        """
        lon, lat = projection.krovak_to_bessel(1050538.63, 568991.00)
        self.assertAlmostEqual(lat, 50.20901222, places=5)
        self.assertAlmostEqual(lon, 16.84977194, places=5)
        self.assertLess(abs(lat - 50.20901222) * 111320, 0.2)
        self.assertLess(abs(lon - 16.84977194) * 71500, 0.2)

    def test_datum_shift_matches_pyproj(self):
        """With the datum shift applied we must agree with PROJ within centimetres."""
        lon, lat = projection.krovak_to_wgs84(1050538.63, 568991.00)
        self.assertAlmostEqual(lat, 50.2082971, places=5)
        self.assertAlmostEqual(lon, 16.8483268, places=5)

    def test_round_trip(self):
        for southing, westing in [(1050538.63, 568991.0), (1043000.0, 742000.0)]:
            lon, lat = projection.krovak_to_wgs84(southing, westing)
            back = projection.wgs84_to_krovak(lon, lat)
            self.assertAlmostEqual(back[0], southing, places=2)
            self.assertAlmostEqual(back[1], westing, places=2)

    def test_east_north_axis_order(self):
        """EPSG:5514 keeps both ordinates negative and swapped."""
        projector = projection.get_projector("epsg:5514")
        lon, lat = projector(-742000.0, -1043000.0)
        self.assertAlmostEqual(lat, 50.0885718, places=5)
        self.assertAlmostEqual(lon, 14.4324382, places=5)

    def test_southing_westing_axis_order(self):
        projector = projection.get_projector("epsg:5513")
        lon, lat = projector(1043000.0, 742000.0)
        self.assertAlmostEqual(lat, 50.0885718, places=5)
        self.assertAlmostEqual(lon, 14.4324382, places=5)


class ProjectorTest(unittest.TestCase):
    def test_wgs84_is_identity(self):
        projector = projection.get_projector("wgs84")
        self.assertEqual(projector.mode, "geographic")
        self.assertEqual(projector(14.5, 50.1), (14.5, 50.1))

    def test_local_passes_coordinates_through(self):
        projector = projection.get_projector("local")
        self.assertEqual(projector.mode, "local")
        self.assertEqual(projector(123456.0, -9.5), (123456.0, -9.5))

    def test_web_mercator(self):
        projector = projection.get_projector("epsg:3857")
        lon, lat = projector(*projection.wgs84_to_web_mercator(14.42, 50.08))
        self.assertAlmostEqual(lon, 14.42, places=7)
        self.assertAlmostEqual(lat, 50.08, places=7)

    def test_unknown_crs_without_pyproj_explains_itself(self):
        try:
            import pyproj  # noqa: F401
        except ImportError:
            with self.assertRaises(projection.ProjectionError) as caught:
                projection.get_projector("epsg:32633")
            self.assertIn("pyproj", str(caught.exception))


class DetectCrsTest(unittest.TestCase):
    def test_detects_wgs84(self):
        self.assertEqual(projection.detect_crs([(14.42, 50.08), (14.5, 50.1)]), "wgs84")

    def test_detects_east_north_krovak(self):
        samples = [(-742000.0, -1043000.0), (-743000.0, -1044000.0)]
        self.assertEqual(projection.detect_crs(samples), "epsg:5514")

    def test_detects_southing_westing_krovak(self):
        samples = [(1043000.0, 742000.0), (1044000.0, 743000.0)]
        self.assertEqual(projection.detect_crs(samples), "epsg:5513")

    def test_falls_back_to_local(self):
        self.assertEqual(projection.detect_crs([(1000.0, 2000.0)]), "local")
        self.assertEqual(projection.detect_crs([]), "local")


if __name__ == "__main__":
    unittest.main()
