# -*- coding: utf-8 -*-
# Family Placer script - version v1
__title__ = "Family\nPlacer v1"
__doc__ = ("Places one of every loaded type of a chosen category in a grid, like a table: each row is a family "
           "and each column is one of that family's types. Pick the category, the families to include, the "
           "spacing (6 ft by default) and the top-left corner of the grid in a plan view. Families that need a "
           "host (wall, ceiling, etc.) or a curve are skipped and listed at the end.")

import re
from pyrevit import revit, forms
from Autodesk.Revit.DB import (
    XYZ, FilteredElementCollector, FamilySymbol, FamilyPlacementType, CategoryType, ViewPlan,
    Transaction, SubTransaction, ElementId
)
from Autodesk.Revit.DB.Structure import StructuralType
from Autodesk.Revit.UI.Selection import ObjectSnapTypes
from Autodesk.Revit.Exceptions import OperationCanceledException
from System.Collections.Generic import List
from ew_common import type_name, commit     # shared helpers (lib/ew_common.py)

TITLE = "Family Placer"
DEFAULT_SPACING = "6'"
MANY = 300          # ask before placing more instances than this

doc = revit.doc
uidoc = revit.uidoc

PLAIN = (FamilyPlacementType.OneLevelBased, FamilyPlacementType.TwoLevelsBased)


# ---------- Reading the loaded families ----------
def natural(text):
    """Sort key that puts 'Type 2' before 'Type 10'."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", text or "")]


def loaded_by_category():
    """{category name: {family name: [FamilySymbol, ...]}} for every placeable loaded family."""
    out = {}
    for s in FilteredElementCollector(doc).OfClass(FamilySymbol).ToElements():
        try:
            fam = s.Family
            cat = s.Category
            if fam is None or cat is None or fam.IsInPlace:
                continue
            if cat.CategoryType == CategoryType.Annotation and "Tag" in cat.Name:
                continue            # tags are placed on elements, not on their own
            out.setdefault(cat.Name, {}).setdefault(fam.Name, []).append(s)
        except Exception:
            continue
    for fams in out.values():
        for name in fams:
            fams[name].sort(key=lambda s: natural(type_name(s)))
    return out


class FamilyItem(forms.TemplateListItem):
    """A family in the pick list, shown with its type count."""
    def __init__(self, name, count):
        super(FamilyItem, self).__init__(name, checked=True)
        self.count = count

    @property
    def name(self):
        return "%s  (%d type%s)" % (self.item, self.count, "" if self.count == 1 else "s")


# ---------- Spacing ----------
def parse_feet(text):
    """Feet from text like 6, 6', 6 ft, 72", 4'-6", 4' 6" or 1.5m. None if it can't be read."""
    t = (text or "").strip().lower().replace("feet", "'").replace("foot", "'").replace("ft", "'")
    t = t.replace("inches", '"').replace("inch", '"').replace("in", '"')
    try:
        if t.endswith("mm"):
            return float(t[:-2]) / 304.8
        if t.endswith("m"):
            return float(t[:-1]) / 0.3048
        m = re.match(r"^\s*(?:([\d.]+)\s*')?\s*-?\s*(?:([\d.]+)\s*\"?)?\s*$", t)
        if not m or (m.group(1) is None and m.group(2) is None):
            return None
        if m.group(1) is None:                       # one number on its own
            return float(m.group(2)) / 12.0 if t.endswith('"') else float(m.group(2))
        return float(m.group(1)) + (float(m.group(2)) / 12.0 if m.group(2) else 0.0)
    except ValueError:
        return None


def ask_spacing():
    """Spacing in feet, or None if cancelled."""
    text = DEFAULT_SPACING
    while True:
        text = forms.ask_for_string(default=text, prompt="Spacing between rows and columns (default 6'):",
                                    title=TITLE)
        if text is None:
            return None
        ft = parse_feet(text)
        if ft and ft > 0:
            return ft
        forms.alert("Couldn't read '%s' as a distance. Try 6, 6', 72\" or 4'-6\"." % text, title=TITLE)


# ---------- Placing ----------
def place(symbol, pt, level, level_ref, view):
    """Places one instance of symbol at pt. Returns the new instance; raises with the reason if it can't."""
    kind = symbol.Family.FamilyPlacementType
    if kind in PLAIN:
        return doc.Create.NewFamilyInstance(pt, symbol, level, StructuralType.NonStructural)
    if kind == FamilyPlacementType.WorkPlaneBased:          # work plane and face based: on the level's plane
        try:
            return doc.Create.NewFamilyInstance(level_ref, pt, XYZ.BasisX, symbol)
        except Exception:
            return doc.Create.NewFamilyInstance(pt, symbol, level, StructuralType.NonStructural)
    if kind == FamilyPlacementType.ViewBased:               # detail items and generic annotations
        return doc.Create.NewFamilyInstance(pt, symbol, view)
    if kind == FamilyPlacementType.OneLevelBasedHosted:
        raise Exception("needs a host (wall, ceiling, floor...)")
    raise Exception("placement type %s isn't supported" % kind)


def main():
    view = doc.ActiveView
    if not isinstance(view, ViewPlan) or view.GenLevel is None:
        forms.alert("Open a floor plan (or other plan view tied to a level) first.", title=TITLE)
        return
    level = view.GenLevel

    cats = loaded_by_category()
    if not cats:
        forms.alert("No placeable families are loaded in this model.", title=TITLE)
        return
    cat = forms.SelectFromList.show(sorted(cats, key=natural), title=TITLE + " - Category",
                                    button_name="Next", multiselect=False)
    if not cat:
        return

    fams = cats[cat]
    names = sorted(fams, key=natural)
    if len(names) > 1:
        picked = forms.SelectFromList.show([FamilyItem(n, len(fams[n])) for n in names],
                                           title=TITLE + " - Families in " + cat,
                                           button_name="Next", multiselect=True)
        if not picked:
            return
        names = [n for n in names if n in picked]

    spacing = ask_spacing()
    if spacing is None:
        return

    total = sum(len(fams[n]) for n in names)
    if total > MANY and not forms.alert("This will place %d instances. Continue?" % total,
                                        title=TITLE, yes=True, no=True):
        return

    try:
        corner = uidoc.Selection.PickPoint(ObjectSnapTypes.Endpoints | ObjectSnapTypes.Intersections |
                                           ObjectSnapTypes.Nearest,
                                           "Pick the top-left corner of the grid (first family, first type)")
    except OperationCanceledException:
        return
    except Exception as ex:
        forms.alert("Could not pick a point in '%s':\n%s" % (view.Name, ex), title=TITLE)
        return

    z = level.ProjectElevation
    origin = XYZ(corner.X, corner.Y, z)
    right = XYZ(view.RightDirection.X, view.RightDirection.Y, 0).Normalize()       # columns: types
    down = XYZ(-view.UpDirection.X, -view.UpDirection.Y, 0).Normalize()            # rows: families
    try:
        level_ref = level.GetPlaneReference()
    except Exception:
        level_ref = None

    placed = List[ElementId]()
    skipped = []

    def work():
        for row, fam_name in enumerate(names):
            for col, sym in enumerate(fams[fam_name]):
                pt = origin + right.Multiply(col * spacing) + down.Multiply(row * spacing)
                st = SubTransaction(doc)
                st.Start()
                try:
                    if not sym.IsActive:
                        sym.Activate()
                        doc.Regenerate()
                    inst = place(sym, pt, level, level_ref, view)
                    st.Commit()
                    placed.Add(inst.Id)
                except Exception as ex:
                    st.RollBack()
                    skipped.append("%s : %s - %s" % (fam_name, type_name(sym), ex))

    err = commit(Transaction(doc, TITLE), work)
    if err:
        forms.alert("Nothing was placed: %s" % err, title=TITLE)
        return

    if placed.Count:
        try:
            uidoc.Selection.SetElementIds(placed)
        except Exception:
            pass
    msg = "Placed %d instance%s of %d famil%s in %s at %s spacing." % (
        placed.Count, "" if placed.Count == 1 else "s", len(names), "y" if len(names) == 1 else "ies", cat,
        feet_text(spacing))
    if skipped:
        shown = skipped[:25]
        more = "\n...and %d more" % (len(skipped) - 25) if len(skipped) > 25 else ""
        forms.alert(msg, sub_msg="Skipped %d:\n%s%s" % (len(skipped), "\n".join(shown), more), title=TITLE)
    else:
        forms.alert(msg, title=TITLE)


def feet_text(ft):
    """4.5 -> 4'-6"."""
    whole = int(ft)
    inches = round((ft - whole) * 12, 2)
    if inches >= 12:
        whole, inches = whole + 1, 0
    return "%d'" % whole if not inches else "%d'-%s\"" % (whole, ("%g" % inches))


if __name__ == "__main__":
    main()
