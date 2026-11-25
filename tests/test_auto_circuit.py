# -*- coding: utf-8 -*-
"""lib/auto_circuit.py: a Readdress run is one Undo."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import revit_stand_ins  # noqa: F401,E402  (fake Revit modules; puts lib\ on the path)
import auto_circuit  # noqa: E402


class Group(object):
    """A TransactionGroup that remembers what happened to it."""
    made = []

    def __init__(self, doc, name):
        self.name, self.state = name, "new"
        Group.made.append(self)

    def Start(self):
        self.state = "started"

    def HasStarted(self):
        return self.state != "new"

    def HasEnded(self):
        return self.state in ("merged", "rolled back")

    def Assimilate(self):
        self.state = "merged"

    def RollBack(self):
        self.state = "rolled back"


class Finishes(object):
    def __init__(self, *args):
        pass

    def run(self):
        Finishes.seen = Group.made[-1].state


class Fails(object):
    def __init__(self, *args):
        pass

    def run(self):
        raise RuntimeError("stopped part way")


class OneUndoPerRun(unittest.TestCase):
    def setUp(self):
        self.saved = (auto_circuit.TransactionGroup, auto_circuit.SlcReaddress, auto_circuit.NacReaddress)
        auto_circuit.TransactionGroup = Group
        del Group.made[:]

    def tearDown(self):
        auto_circuit.TransactionGroup, auto_circuit.SlcReaddress, auto_circuit.NacReaddress = self.saved

    def test_the_run_happens_inside_one_group_that_is_merged(self):
        auto_circuit.SlcReaddress = Finishes
        auto_circuit.readdress("SLC", {}, False)
        self.assertEqual(Finishes.seen, "started")
        self.assertEqual([(g.name, g.state) for g in Group.made], [(auto_circuit.TITLES["SLC"], "merged")])

    def test_nac_and_voice_too(self):
        auto_circuit.NacReaddress = Finishes
        for kind in ("N", "V"):
            auto_circuit.readdress(kind, {}, True)
        self.assertEqual([(g.name, g.state) for g in Group.made],
                         [(auto_circuit.TITLES["N"], "merged"), (auto_circuit.TITLES["V"], "merged")])

    def test_a_run_that_stops_keeps_what_it_saved(self):
        auto_circuit.SlcReaddress = Fails
        with self.assertRaises(RuntimeError):
            auto_circuit.readdress("SLC", {}, False)
        self.assertEqual(Group.made[-1].state, "merged")


if __name__ == "__main__":
    unittest.main()
