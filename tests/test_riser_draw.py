# -*- coding: utf-8 -*-
"""lib/riser_tool.py: drawing a one-line notes what it creates, measures the loop letters after one regenerate, and
spares are grouped from exactly what was drawn for them."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import revit_stand_ins  # noqa: F401,E402  (fake Revit modules; puts lib\ on the path)
import riser_tool as rt  # noqa: E402


class Id(object):
    count = 0

    def __init__(self):
        Id.count += 1
        self.Value = Id.count

    def __eq__(self, other):
        return isinstance(other, Id) and other.Value == self.Value

    def __hash__(self):
        return self.Value

    def __repr__(self):
        return "Id(%d)" % self.Value


class Element(object):
    def __init__(self, kind, nested=()):
        self.kind, self.Id, self.nested = kind, Id(), list(nested)

    def GetSubComponentIds(self):
        if self.kind != "instance":
            raise AttributeError("only family instances have nested families")
        return [n.Id for n in self.nested]


class Box(object):
    def __init__(self, y):
        self.Min = type("P", (), {"Y": y})()


class Note(Element):
    def __init__(self, y):
        Element.__init__(self, "note")
        self.y = y

    def get_BoundingBox(self, view):
        return Box(self.y - 0.25)          # the letter's bottom


class GroupType(object):
    Name = ""


class Doc(object):
    def __init__(self, nested_per_symbol=0):
        self.log, self.by_id, self.groups = [], {}, []
        self.Create = self
        self.Application = self
        self.ShortCurveTolerance = 0.001
        self.nested = nested_per_symbol

    def _keep(self, el):
        self.by_id[el.Id] = el
        for n in el.nested:
            self._keep(n)
        return el

    def NewDetailCurve(self, view, curve):
        self.log.append("line")
        return self._keep(Element("curve"))

    def NewFamilyInstance(self, point, symbol, view):
        self.log.append("symbol")
        return self._keep(Element("instance", [Element("instance") for _ in range(self.nested)]))

    def NewGroup(self, ids):
        self.log.append("group")
        group = type("G", (), {})()
        group.GroupType = GroupType()
        group.ids = list(ids)
        self.groups.append(group)
        return group

    def GetElement(self, i):
        return self.by_id[i]

    def Regenerate(self):
        self.log.append("regenerate")


class TextNotes(object):
    doc = None

    @staticmethod
    def Create(doc, view_id, point, text, opts):
        TextNotes.doc.log.append("note")
        return TextNotes.doc._keep(Note(TextNotes.y_of[text]))


class Point(object):
    def __init__(self, x, y, z):
        self.X, self.Y, self.Z = x, y, z


class View(object):
    Id = "view"
    Scale = 96


class Saved(object):
    def __init__(self):
        self.saved = {}


class Patched(unittest.TestCase):
    """riser_tool with the fakes above in place of Revit."""
    NAMES = ("doc", "TextNote", "XYZ")

    def setUp(self):
        self.old = dict((n, getattr(rt, n)) for n in self.NAMES)
        self.doc = Doc(nested_per_symbol=1)
        TextNotes.doc = self.doc
        rt.doc, rt.TextNote, rt.XYZ = self.doc, TextNotes, Point

    def tearDown(self):
        for n, v in self.old.items():
            setattr(rt, n, v)


class Draw(Patched):
    def plan(self):
        TextNotes.y_of = {"T": 1, "A": 2, "D": 3, "L1": 5, "L2": 6}
        return {"symbols": [(0, 0, "dev")], "boxes": [(0, 0, 1, 1, 1, 1)], "lines": [((0, 0), (5, 0))],
                "texts": [(1, 1, "T", "L"), (2, 2, "A", "A"), (3, 3, "D", "D")],
                "leader_texts": [(1, 5, "L1", 1, 0), (3, 6, "L2", 3, 0)], "callouts": [], "end_marks": []}

    def test_everything_drawn_is_noted_with_the_families_nested_in_it(self):
        made, created = [], []
        failed = rt.draw(View(), self.plan(), {"dev": "symbol"}, "text type", 0.5, created=created, made=made)
        self.assertEqual(failed, 0)
        self.assertEqual(sorted(made, key=lambda i: i.Value), sorted(self.doc.by_id, key=lambda i: i.Value))
        self.assertEqual(len(made), 2 + 4 + 1 + 3 + 2 + 2)   # symbol + nested, box, line, texts, letters, leaders
        self.assertEqual(len(created), 4 + 1 + 2)

    def test_the_loop_letters_are_measured_after_one_regenerate(self):
        created = []
        rt.draw(View(), self.plan(), {"dev": "symbol"}, "text type", 0.5, created=created)
        self.assertEqual(self.doc.log.count("regenerate"), 1)
        self.assertEqual(self.doc.log[-3:], ["regenerate", "line", "line"])     # letters first, then their leaders
        leaders = [(p, q) for p, q, _c in created[-2:]]
        self.assertEqual(leaders, [((1, 4.75), (1, 0)), ((3, 5.75), (3, 0))])   # from each letter's measured bottom

    def test_nothing_to_measure_means_no_regenerate(self):
        plan = self.plan()
        plan["leader_texts"] = []
        rt.draw(View(), plan, {"dev": "symbol"}, "text type", 0.5)
        self.assertNotIn("regenerate", self.doc.log)


class Spares(Patched):
    NAMES = Patched.NAMES + ("view_onelines", "named_value", "element_name", "Transaction", "text_type", "KIND",
                             "unique_group_name", "save_oneline_data", "BATCH", "references_in_instance",
                             "lock_to_reference", "VIEW_SCALE")

    def setUp(self):
        Patched.setUp(self)
        TextNotes.y_of = {rt.SPARE_TEXT: 1, "N1-1": 2, "N1-3": 2}
        saved = self.saved = []
        rt.view_onelines = lambda view: ([], [])
        rt.named_value = lambda el, name: "FACP-1"
        rt.element_name = lambda el: "panel"
        rt.Transaction = lambda doc, name: type("T", (), {"Start": lambda s: None, "Commit": lambda s: None,
                                                          "HasStarted": lambda s: True, "HasEnded": lambda s: True})()
        rt.text_type = lambda: ("text type", 0.5)
        rt.KIND = type("K", (), {"circuit_label": staticmethod(lambda c: "N%d-%d" % c), "run_word": "Circuit", "title": "NAC Riser"})()
        rt.unique_group_name = lambda name: name
        rt.save_oneline_data = lambda group, data: saved.append((group, data))
        rt.BATCH = type("B", (), {"spares": [], "spare_problems": [], "panel_inst": None})()
        rt.references_in_instance = lambda inst, view, c, y: []
        rt.lock_to_reference = lambda view, refs, curve: None

    def test_each_spare_is_grouped_from_what_was_drawn_for_it_after_one_regenerate(self):
        root = type("R", (), {"UniqueId": "panel-uid"})()
        outputs = [({"supply": 1, "loop": 3, "vx": 0.0}, -2.0), ({"supply": 1, "loop": 1, "vx": 0.0}, -1.0)]
        rt.draw_spares(View(), root, outputs, {})
        log = self.doc.log
        self.assertEqual(log.count("group"), 2)
        first_group = log.index("group")
        self.assertEqual(log[first_group - 1], "regenerate")               # one regenerate before any group ...
        self.assertEqual(log[:first_group].count("regenerate"), 3)         # ... after one per spare's letter
        self.assertEqual(rt.BATCH.spares, ["N1-1", "N1-3"])                # lowest circuit first, as before
        drawn = set(self.doc.by_id)
        grouped = [set(g.ids) for g in self.doc.groups]
        self.assertEqual(grouped[0] | grouped[1], drawn)
        self.assertFalse(grouped[0] & grouped[1])
        self.assertEqual([d["label"] for _g, d in self.saved], ["N1-1", "N1-3"])
        self.assertEqual(rt.BATCH.spare_problems, [])


if __name__ == "__main__":
    unittest.main()
