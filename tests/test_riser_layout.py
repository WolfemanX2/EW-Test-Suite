# -*- coding: utf-8 -*-
"""lib/riser_layout.layout: where a one-line's address callouts go."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import revit_stand_ins  # noqa: F401,E402  (fake Revit modules; puts lib\ on the path)
import riser_layout as rl  # noqa: E402

CFG = {"spacing": 6.0, "per_line": 10, "pad": 0.25, "text_gap": 0.1, "line_h": 0.5, "char_w": 0.3,
       "row_gap": 1.0, "label_offset_x": 1.125, "end_text": "NAC RETURN"}


def one_line(callouts):
    """A one-line from the panel (P, its right side at x = 0) through devices 1, 2 ... with callouts
    {device: (left, right, up, down)}."""
    nodes = sorted(callouts)
    info = {"P": {"mapped": False, "ext": (0.0, 0.0, 0.0, 0.0), "lines": [], "panel": True, "exit_dy": 0.0}}
    for n in nodes:
        info[n] = {"mapped": True, "ext": (0.5, 0.5, 0.5, 0.5), "lines": [], "callout": callouts[n]}
    plan = rl.layout([{"nodes": nodes, "label": "N1-1"}], "P", info, set(), CFG)
    symbols = dict((n, (x, y)) for x, y, n in plan["symbols"])
    marks = dict((n, (x, y)) for x, y, n in plan["callouts"])
    return plan, symbols, marks


class Callouts(unittest.TestCase):
    def test_a_small_callout_stays_under_its_device(self):
        plan, symbols, marks = one_line({1: (1.0, 1.0, 0.0, 1.0)})
        self.assertAlmostEqual(marks[1][0], symbols[1][0])

    def test_a_wide_first_callout_is_moved_right_of_the_panel_and_the_device_stays(self):
        plan, symbols, marks = one_line({1: (12.0, 12.0, 0.0, 1.0)})
        px = plan["panel"][0]
        self.assertAlmostEqual(symbols[1][0] - px, 1.125 + 6.0)       # the device: where it always was
        self.assertGreaterEqual(marks[1][0] - 12.0, px)                 # the callout's left edge: clear of the panel
        self.assertGreater(marks[1][0], symbols[1][0])

    def test_the_callouts_after_it_move_on_to_clear_it(self):
        plan, symbols, marks = one_line({1: (12.0, 12.0, 0.0, 1.0), 2: (12.0, 12.0, 0.0, 1.0)})
        self.assertGreaterEqual(marks[2][0] - 12.0, marks[1][0] + 12.0)
        self.assertAlmostEqual(symbols[2][0] - symbols[1][0], 6.0)


if __name__ == "__main__":
    unittest.main()


class KeynoteAndPanelText(unittest.TestCase):
    def layout(self, keynote, above, cfg_extra):
        info = {"P": {"mapped": False, "ext": (0.0, 0.0, 0.0, 0.0), "lines": [], "panel": True, "exit_dy": 0.0},
                1: {"mapped": True, "ext": (0.5, 0.5, 0.5, 0.5), "lines": ["N1L1M001"], "above": above}}
        if keynote:
            info[1]["keynote"] = keynote
        cfg = dict(CFG)
        cfg.update(cfg_extra)
        plan = rl.layout([{"nodes": [1], "label": "A"}], "P", info, set(), cfg)
        sx, sy = [(x, y) for x, y, n in plan["symbols"] if n == 1][0]
        return plan, sx, sy

    def test_the_keynote_sits_its_offset_above_the_symbol(self):
        plan, sx, sy = self.layout((0.3, 0.3, 0.4, 0.2), "", {"keynote_gap": 0.5})
        kx, ky, n = plan["keynotes"][0]
        self.assertEqual(n, 1)
        self.assertAlmostEqual(kx, sx)
        self.assertAlmostEqual((ky - 0.2) - (sy + 0.5), 0.5)       # its bottom 0.5 above the symbol's top

    def test_the_panel_text_goes_its_offset_above_the_keynote(self):
        plan, sx, sy = self.layout((0.3, 0.3, 0.4, 0.2), "FACU-01", {"keynote_gap": 0.5, "above_gap": 0.25})
        top = [(x, y) for x, y, t, how in plan["texts"] if t == "FACU-01"][0][1]
        keynote_top = plan["keynotes"][0][1] + 0.4
        self.assertAlmostEqual(top - keynote_top, 0.25 + CFG["line_h"])    # gap, then one line of text

    def test_without_a_keynote_the_panel_text_is_its_offset_above_the_symbol(self):
        plan, sx, sy = self.layout(None, "FACU-01", {"above_gap": 0.25})
        top = [(x, y) for x, y, t, how in plan["texts"] if t == "FACU-01"][0][1]
        self.assertEqual(plan["keynotes"], [])
        self.assertAlmostEqual(top - (sy + 0.5), 0.25 + CFG["line_h"])
