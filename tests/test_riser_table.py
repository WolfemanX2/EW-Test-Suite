# -*- coding: utf-8 -*-
"""lib/slc_riser.py: the riser symbol table (with each type's Keynote / Function symbol) and drawing settings."""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import revit_stand_ins  # noqa: F401,E402  (fake Revit modules; puts lib\ on the path)
import slc_riser as sr  # noqa: E402


class Table(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.path = os.path.join(self.folder, "riser_symbols.json")

    def tearDown(self):
        shutil.rmtree(self.folder, ignore_errors=True)

    def test_the_keynote_is_saved_and_read_back(self):
        sr.save_table({"Smoke : Std": sr.new_entry(["SYM : A"], "KEY : F"),
                       "Heat : Std": sr.new_entry(["SYM : B"])}, self.path)
        table = sr.load_table(self.path)
        self.assertEqual(table["Smoke : Std"], {"symbols": ["SYM : A"], "keynote": "KEY : F"})
        self.assertEqual(table["Heat : Std"]["keynote"], "")

    def test_an_older_table_has_no_keynotes(self):
        with open(self.path, "w") as f:
            f.write('{"Smoke : Std": {"symbol": "SYM : A"}, "Old : One": "SYM : B"}')
        table = sr.load_table(self.path)
        self.assertEqual(table["Smoke : Std"]["keynote"], "")
        self.assertEqual(table["Old : One"]["symbols"], ["SYM : B"])


class Settings(unittest.TestCase):
    def test_the_offsets_have_defaults_and_limits(self):
        out = sr.clean_settings({"keynote_offset_in": 3, "panel_text_offset_in": 500})
        self.assertEqual(out["keynote_offset_in"], 3.0)
        self.assertEqual(out["panel_text_offset_in"], sr.DEFAULT_SETTINGS["panel_text_offset_in"])


if __name__ == "__main__":
    unittest.main()
