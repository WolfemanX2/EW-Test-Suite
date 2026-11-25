# -*- coding: utf-8 -*-
"""lib/ew_common.py: the small shared helpers."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import revit_stand_ins  # noqa: F401,E402  (fake Revit modules; puts lib\ on the path)
import ew_common as ec  # noqa: E402


class NewId(object):            # Revit 2024+: .Value
    def __init__(self, n):
        self.Value = n


class OldId(object):            # before 2024: only .IntegerValue
    def __init__(self, n):
        self.IntegerValue = n


class Element(object):
    def __init__(self, i):
        self.Id = i


class ElementIdNumbers(unittest.TestCase):
    def test_any_revit_version(self):
        self.assertEqual(ec.eid_int(NewId(5)), 5)
        self.assertEqual(ec.eid_int(OldId(6)), 6)
        self.assertEqual(ec.eid(Element(NewId(7))), 7)
        self.assertEqual(ec.eid(OldId(8)), 8)


class NoUnits(object):
    def GetUnits(self):
        raise Exception("Revit's unit parser isn't available outside Revit")


class ParseLength(unittest.TestCase):
    def test_plain_numbers_are_feet(self):
        self.assertEqual(ec.parse_length(NoUnits(), " 12.5 "), 12.5)

    def test_blank_or_unreadable_is_none(self):
        for text in ("", None, "   ", "abc"):
            self.assertIsNone(ec.parse_length(NoUnits(), text))


class Symbol(object):
    pass


class ConduitType(object):
    def __init__(self, elbow=None, rules=0, elbow_fails=False):
        self._elbow, self._fails = elbow, elbow_fails
        self.RoutingPreferenceManager = Rules(rules) if rules is not None else None
        self.Document = self

    @property
    def Elbow(self):
        if self._fails:
            raise Exception("no default elbow on this type")
        return self._elbow

    def GetElement(self, part_id):
        return ("part", part_id)


class Rule(object):
    MEPPartId = 42


class Rules(object):
    def __init__(self, n):
        self.n = n

    def GetNumberOfRules(self, group):
        return self.n

    def GetRule(self, group, index):
        return Rule()


class BendFitting(unittest.TestCase):
    def test_the_types_bend(self):
        bend = Symbol()
        self.assertIs(ec.bend_fitting(ConduitType(elbow=bend)), bend)

    def test_an_elbow_rule_in_routing_preferences(self):
        self.assertEqual(ec.bend_fitting(ConduitType(elbow_fails=True, rules=1)), ("part", 42))

    def test_none_when_the_type_has_no_bend(self):
        self.assertIsNone(ec.bend_fitting(ConduitType()))
        self.assertIsNone(ec.bend_fitting(ConduitType(rules=None)))
        self.assertIsNone(ec.bend_fitting(None))


if __name__ == "__main__":
    unittest.main()
