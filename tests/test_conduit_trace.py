# -*- coding: utf-8 -*-
"""lib/conduit_trace.py and riser_layout.tee_order: the order devices are reached along conduit.

Networks are built from labels: every link is its own connector on each element, so an element with three links
is a tee. Devices are the labels starting with D."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import revit_stand_ins  # noqa: F401,E402  (fake Revit modules; puts lib\ on the path)
import conduit_trace as ct  # noqa: E402
from riser_layout import tee_order  # noqa: E402


class Net(object):
    def __init__(self, *chains):
        self.links = {}
        for chain in chains:
            for a, b in zip(chain, chain[1:]):
                self.links.setdefault(a, []).append([b])
                self.links.setdefault(b, []).append([a])

    def ports(self, i):
        return self.links.get(i, [])

    def trace(self, conduit, anchor, prefer=None, blocked=(), sort_key=None):
        return ct.trace_downstream(conduit, anchor, self.ports, lambda i: i not in blocked,
                                   lambda i: str(i).startswith("D"), sort_key, prefer)


class TeeOrder(unittest.TestCase):
    def test_main_run_is_the_side_with_most_devices_and_comes_last(self):
        size = {"a": 3, "b": 1, "c": 2}
        self.assertEqual(tee_order(["a", "b", "c"], size.get, lambda s: s), ["b", "c", "a"])

    def test_on_a_tie_the_side_that_sorts_last_is_the_main_run(self):
        self.assertEqual(tee_order([0, 1], lambda s: 1, lambda s: s), [0, 1])
        self.assertEqual(tee_order([1, 0], lambda s: 1, lambda s: s), [0, 1])


class TraceDownstream(unittest.TestCase):
    def test_a_straight_run_in_order_of_connection(self):
        net = Net(["D0", "c0", "D1", "c1", "box", "c2", "D2"])
        self.assertEqual(net.trace("c0", "D0"), (["D1", "D2"], None))

    def test_never_goes_back_past_the_anchor(self):
        net = Net(["Dup", "cx", "D0", "c0", "D1"])
        self.assertEqual(net.trace("c0", "D0"), (["D1"], None))

    def test_a_tee_takes_the_branch_first_and_the_main_run_last(self):
        # D0 - c0 - D1 - c1 - T, T - c2 - D2 (branch: 1 device), T - c3 - D3 - c4 - D4 (main run: 2 devices)
        net = Net(["D0", "c0", "D1", "c1", "T"], ["T", "c3", "D3", "c4", "D4"], ["T", "c2", "D2"])
        self.assertEqual(net.trace("c0", "D0"), (["D1", "D2", "D3", "D4"], None))

    def test_the_side_holding_a_chosen_device_comes_first(self):
        net = Net(["D0", "c0", "D1", "c1", "T"], ["T", "c3", "D3", "c4", "D4"], ["T", "c2", "D2"])
        self.assertEqual(net.trace("c0", "D0", prefer={"D4"}), (["D1", "D3", "D4", "D2"], None))

    def test_a_loop_is_followed_once(self):
        # the run splits at T and both sides meet again at U
        net = Net(["D0", "c0", "T"], ["T", "c1", "D1", "c2", "U"], ["T", "c3", "D2", "c4", "U"], ["U", "c5", "D3"])
        order, problem = net.trace("c0", "D0")
        self.assertIsNone(problem)
        self.assertEqual(sorted(order), ["D1", "D2", "D3"])
        self.assertEqual(len(order), 3)

    def test_conduit_that_is_not_followed_stops_the_run(self):
        net = Net(["D0", "c0", "D1", "other", "D2"])
        self.assertEqual(net.trace("c0", "D0", blocked={"other"}), (["D1"], None))

    def test_a_conduit_that_does_not_lead_to_the_anchor(self):
        net = Net(["D0", "cx"], ["c0", "D1"])
        self.assertEqual(net.trace("c0", "D0"), (None, "not connected"))

    def test_thousands_of_tees_in_a_row(self):
        # a main run with a one-device branch off every third element: no recursion, so no stack limit
        chain = ["D0", "c0"] + ["D%d" % i for i in range(1, 6001)]
        branches = [[chain[i], "b%d" % i, "Db%d" % i] for i in range(5, 6000, 3)]
        net = Net(chain, *branches)
        order, problem = net.trace("c0", "D0")
        self.assertIsNone(problem)
        self.assertEqual(len(order), 6000 + len(branches))
        self.assertEqual(order[:6], ["D1", "D2", "D3", "D4", "Db5", "D5"])


if __name__ == "__main__":
    unittest.main()
