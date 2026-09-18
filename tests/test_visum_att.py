import io
import os
import tempfile
import unittest

from trafficvolumes import visum_att


SAMPLE = """$VISION
* a comment
*
$NODE:NO;XCOORD;YCOORD
1;-743800.000;-1043600.000
2;-743550.000;-1043600.000
*
$LINK:NO;FROMNODENO;TONODENO;NAME;LENGTH
1;1;2;"Husova, horní";0,532km
1;2;1;Husova;0.532km
"""


class ParseTest(unittest.TestCase):
    def test_splits_tables(self):
        tables = visum_att.parse(SAMPLE)
        self.assertEqual([t.name for t in tables], ["NODE", "LINK"])
        self.assertEqual(len(tables[0].rows), 2)
        self.assertEqual(len(tables[1].rows), 2)

    def test_quoted_field_keeps_its_separator(self):
        link = visum_att.find_table(visum_att.parse(SAMPLE), "LINK")
        self.assertEqual(link.rows[0]["NAME"], "Husova, horní")

    def test_comments_and_blank_lines_are_ignored(self):
        tables = visum_att.parse("* only comments\n\n*\n")
        self.assertEqual(tables, [])

    def test_bare_marker_without_columns(self):
        tables = visum_att.parse("$VISION\n$LINK:NO\n7\n")
        self.assertEqual(len(tables), 1)
        self.assertEqual(tables[0].rows[0]["NO"], "7")

    def test_tab_separated_header(self):
        tables = visum_att.parse("$LINK:NO\tFROMNODENO\tTONODENO\n1\t2\t3\n")
        self.assertEqual(tables[0].separator, "\t")
        self.assertEqual(tables[0].rows[0]["TONODENO"], "3")

    def test_short_rows_are_padded(self):
        tables = visum_att.parse("$LINK:NO;FROMNODENO;TONODENO\n1;2\n")
        self.assertEqual(tables[0].rows[0]["TONODENO"], "")

    def test_find_table_is_case_insensitive(self):
        tables = visum_att.parse(SAMPLE)
        self.assertIsNotNone(visum_att.find_table(tables, "link"))
        self.assertIsNone(visum_att.find_table(tables, "ZONE"))


class NumberTest(unittest.TestCase):
    def test_czech_decimal_comma(self):
        self.assertEqual(visum_att.parse_number("0,532km"), 0.532)

    def test_unit_suffix(self):
        self.assertEqual(visum_att.parse_number("50km/h"), 50.0)

    def test_thousands_separator(self):
        self.assertEqual(visum_att.parse_number("1.234,5"), 1234.5)
        self.assertEqual(visum_att.parse_number("1,234.5"), 1234.5)

    def test_non_numbers(self):
        self.assertIsNone(visum_att.parse_number("abc"))
        self.assertIsNone(visum_att.parse_number(""))
        self.assertIsNone(visum_att.parse_number(None))

    def test_formats_without_locale_surprises(self):
        self.assertEqual(visum_att.format_number(1234.0), "1234")
        self.assertEqual(visum_att.format_number(12.5), "12.5")
        self.assertEqual(visum_att.format_number(12.5, decimals=2), "12.50")


class WriteTest(unittest.TestCase):
    def test_round_trip(self):
        buffer = io.StringIO()
        count = visum_att.write_table(
            buffer,
            "LINK",
            ["NO", "FROMNODENO", "TONODENO", "VOL"],
            [["1", "1", "2", 1500], ["1", "2", "1", 900]],
            comments=["written by a test"],
        )
        self.assertEqual(count, 2)
        table = visum_att.find_table(visum_att.parse(buffer.getvalue()), "LINK")
        self.assertEqual(table.columns, ["NO", "FROMNODENO", "TONODENO", "VOL"])
        self.assertEqual(table.rows[0]["VOL"], "1500")

    def test_quotes_values_containing_the_separator(self):
        self.assertEqual(visum_att.quote("a;b"), '"a;b"')
        self.assertEqual(visum_att.quote('say "hi"'), '"say ""hi"""')
        self.assertEqual(visum_att.quote("plain"), "plain")


class EncodingTest(unittest.TestCase):
    def test_reads_cp1250(self):
        with tempfile.NamedTemporaryFile("wb", suffix=".att", delete=False) as fh:
            fh.write("$LINK:NO;NAME\n1;Křižíkova\n".encode("cp1250"))
            path = fh.name
        try:
            table = visum_att.find_table(visum_att.read_file(path), "LINK")
            self.assertEqual(table.rows[0]["NAME"], "Křižíkova")
        finally:
            os.unlink(path)

    def test_reads_utf8_with_bom(self):
        with tempfile.NamedTemporaryFile("wb", suffix=".att", delete=False) as fh:
            fh.write("$LINK:NO;NAME\n1;Křižíkova\n".encode("utf-8-sig"))
            path = fh.name
        try:
            table = visum_att.find_table(visum_att.read_file(path), "LINK")
            self.assertEqual(table.rows[0]["NAME"], "Křižíkova")
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
