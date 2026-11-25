# -*- coding: utf-8 -*-
"""lib/circuit_config.py: the Family Defaults Config settings the Auto Circuit tools read."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import revit_stand_ins  # noqa: F401,E402  (fake Revit modules; puts lib\ on the path)
import circuit_config as cc  # noqa: E402


def config():
    cfg = cc.empty()
    cfg["families"]["Horn Strobe"] = {"mounting": cc.WALL, "round_to": 5}
    cfg["types"]["Horn Strobe : Ceiling"] = {"mounting": cc.CEILING}
    cfg["address_groups"] = [("MMS Cabinet", [("Single Zone", 1), ("Dual Zone", 2)]), ("Relay", [("", 1)])]
    return cfg


class Setting(unittest.TestCase):
    def test_a_types_own_value_comes_first(self):
        self.assertEqual(cc.setting(config(), "Horn Strobe : Ceiling", "mounting"), cc.CEILING)

    def test_otherwise_the_familys_value(self):
        self.assertEqual(cc.setting(config(), "Horn Strobe : Wall", "mounting"), cc.WALL)
        self.assertEqual(cc.setting(config(), "Horn Strobe : Ceiling", "round_to"), 5)

    def test_none_when_neither_has_it(self):
        self.assertIsNone(cc.setting(config(), "Smoke : Standard", "mounting"))
        self.assertIsNone(cc.setting(config(), "Horn Strobe : Wall", "device_type"))


class Subgroups(unittest.TestCase):
    def test_a_groups_subgroups_with_their_address_counts(self):
        self.assertEqual(cc.subgroups(config(), "MMS Cabinet"), [("Single Zone", 1), ("Dual Zone", 2)])

    def test_none_for_a_group_that_does_not_exist(self):
        self.assertIsNone(cc.subgroups(config(), "Nothing"))


class Entries(unittest.TestCase):
    def test_only_values_that_make_sense_are_kept(self):
        raw = {"mounting": "Sideways", "device_type": cc.MODULE, "conduit_type": "  EMT  ", "address_group": "",
               "round_to": "10"}
        self.assertEqual(cc._entry(raw), {"device_type": cc.MODULE, "conduit_type": "EMT", "round_to": 10})

    def test_round_to_must_be_more_than_one(self):
        for raw in (1, 0, -5, "x", True):
            self.assertNotIn("round_to", cc._entry({"round_to": raw}))


if __name__ == "__main__":
    unittest.main()
