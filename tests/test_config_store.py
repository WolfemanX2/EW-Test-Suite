# -*- coding: utf-8 -*-
"""lib/config_store.py: where settings files live and the safe write."""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import revit_stand_ins  # noqa: F401,E402  (fake Revit modules; puts lib\ on the path)
import config_store as cs  # noqa: E402


class Folder(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def path(self, *parts):
        return os.path.join(self.dir, *parts)


class WriteJson(Folder):
    def test_creates_the_folder_and_the_file(self):
        p = self.path("new", "settings.json")
        cs.write_json(p, {"a": 1})
        self.assertEqual(cs.read_json(p), {"a": 1})

    def test_replaces_an_existing_file(self):
        p = self.path("settings.json")
        cs.write_json(p, {"a": 1})
        cs.write_json(p, {"a": 2, "b": [1, 2]})
        self.assertEqual(cs.read_json(p), {"a": 2, "b": [1, 2]})

    def test_a_failed_write_keeps_the_old_file_and_leaves_no_temporary_file(self):
        p = self.path("settings.json")
        cs.write_json(p, {"a": 1})
        with self.assertRaises(TypeError):
            cs.write_json(p, {"a": object()})       # can't be written as JSON
        self.assertEqual(cs.read_json(p), {"a": 1})
        self.assertEqual(os.listdir(self.dir), ["settings.json"])

    def test_no_indent_writes_one_line(self):
        p = self.path("results.json")
        cs.write_json(p, {"b": 1, "a": 2}, indent=None)
        with open(p) as f:
            self.assertEqual(f.read(), '{"a": 2, "b": 1}')


class ReadJson(Folder):
    def test_missing_or_blank_is_empty(self):
        self.assertEqual(cs.read_json(self.path("none.json"), empty=[]), [])
        p = self.path("blank.json")
        with open(p, "w") as f:
            f.write("  \n")
        self.assertEqual(cs.read_json(p, empty={}), {})

    def test_a_broken_file_raises_so_it_is_never_overwritten_as_empty(self):
        p = self.path("broken.json")
        with open(p, "w") as f:
            f.write("{not json")
        with self.assertRaises(ValueError):
            cs.read_json(p)


class StartFrom(Folder):
    def test_copies_the_first_source_that_exists(self):
        src = self.path("default.json")
        cs.write_json(src, {"office": True})
        p = self.path("user", "settings.json")
        self.assertEqual(cs.start_from(p, [self.path("missing.json"), src]), src)
        self.assertEqual(cs.read_json(p), {"office": True})

    def test_leaves_an_existing_file_alone(self):
        p = self.path("settings.json")
        cs.write_json(p, {"mine": 1})
        src = self.path("default.json")
        cs.write_json(src, {"office": True})
        self.assertIsNone(cs.start_from(p, [src]))
        self.assertEqual(cs.read_json(p), {"mine": 1})


if __name__ == "__main__":
    unittest.main()
