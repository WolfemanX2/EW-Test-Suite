# -*- coding: utf-8 -*-
# Family Placer script - version v4
# v4 - loaded families by category now come from lib/family_qaqc.py (shared with Family Audit)
# v3 - model families placed 5.5 ft above the level; type name labels removed (family names only)
# v2 - text labels: family name to the left of each row, type name above each instance
__title__ = "Family\nPlacer v4"
__doc__ = ("Places one of every loaded type of a chosen category in a grid, like a table: each row is a family "
           "and each column is one of that family's types. Pick the category, the families to include, the "
           "spacing (6 ft by default) and the top-left corner of the grid in a plan view. Model families are placed 5.5 ft above the level. Each row is labeled with its family name, using the project's default text type. Families that need a "
           "host (wall, ceiling, etc.) or a curve are skipped and listed at the end.")

import re
from pyrevit import revit, forms
from Autodesk.Revit.DB import (
    XYZ, FilteredElementCollector, FamilySymbol, FamilyPlacementType, ViewPlan,
    Transaction, SubTransaction, ElementId, BuiltInParameter, ElementTypeGroup, TextNote, TextNoteType, TextNoteOptions,
    HorizontalTextAlignment, VerticalTextAlignment
)
from Autodesk.Revit.DB.Structure import StructuralType
from Autodesk.Revit.UI.Selection import ObjectSnapTypes
from Autodesk.Revit.Exceptions import OperationCanceledException
from System.Collections.Generic import List
from ew_common import type_name, commit     # shared helpers (lib/ew_common.py)
from family_qaqc import natural, loaded_by_category     # lib/family_qaqc.py

TITLE = "Family Placer"
DEFAULT_SPACING = "6'"
MANY = 300          # ask before placing more instances than this
OFFSET = 5.5        # feet above the level for model families (annotations and detail items stay on the view)
OFFSET_PARAMS = (BuiltInParameter.INSTANCE_ELEVATION_PARAM,          # Elevation from Level
                 BuiltInParameter.INSTANCE_FREE_HOST_OFFSET_PARAM)   # Offset from Host (on the level's plane)

doc = revit.doc
uidoc = revit.uidoc

PLAIN = (FamilyPlacementType.OneLevelBased, FamilyPlacementType.TwoLevelsBased)


# ---------- Picking families ----------
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


# ---------- Labels ----------
def text_type_id():
    """The project's default text type, or any text type. None if there are none."""
    tid = doc.GetDefaultElementTypeId(ElementTypeGroup.TextNoteType)
    if tid is not None and tid != ElementId.InvalidElementId:
        return tid
    tt = FilteredElementCollector(doc).OfClass(TextNoteType).FirstElement()
    return tt.Id if tt is not None else None


def label(view, pt, text, type_id, h_align, v_align, width=None):
    """A text note in view at pt. width is in model feet (wraps the text); None for no wrapping."""
    opts = TextNoteOptions(type_id)
    opts.HorizontalAlignment = h_align
    try:
        opts.VerticalAlignment = v_align
    except Exception:
        pass
    if width:
        try:
            return TextNote.Create(doc, view.Id, pt, width / float(view.Scale), text, opts)
        except Exception:
            pass        # narrower than Revit allows: fall back to a note that doesn't wrap
    return TextNote.Create(doc, view.Id, pt, text, opts)


# ---------- Placing ----------
def set_offset(inst, offset):
    """Sets the instance's height above its level / work plane. Returns False if it has no such parameter."""
    for bip in OFFSET_PARAMS:
        p = inst.get_Parameter(bip)
        if p is not None and not p.IsReadOnly:
            p.Set(offset)
            return True
    return False


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

    cats = loaded_by_category(doc)
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
    labels = [0]
    label_errors = []
    tid = text_type_id()
    no_offset = []

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
                    if sym.Family.FamilyPlacementType != FamilyPlacementType.ViewBased \
                            and not set_offset(inst, OFFSET):
                        no_offset.append("%s : %s" % (fam_name, type_name(sym)))
                    st.Commit()
                    placed.Add(inst.Id)
                except Exception as ex:
                    st.RollBack()
                    skipped.append("%s : %s - %s" % (fam_name, type_name(sym), ex))
                    continue
            if tid is not None:             # family name to the left of the row
                try:
                    row_pt = origin + down.Multiply(row * spacing) - right.Multiply(spacing * 0.6)
                    label(view, row_pt, fam_name, tid, HorizontalTextAlignment.Right, VerticalTextAlignment.Middle)
                    labels[0] += 1
                except Exception as ex:
                    label_errors.append(str(ex))

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
    if no_offset:
        msg += "\n%d placed at the level: no Elevation from Level / Offset parameter (%s%s)." % (
            len(no_offset), ", ".join(no_offset[:5]), ", ..." if len(no_offset) > 5 else "")
    if labels[0]:
        msg += "\nAdded %d text label%s." % (labels[0], "" if labels[0] == 1 else "s")
    if tid is None:
        msg += "\nNo labels were added: this project has no text types."
    elif label_errors:
        msg += "\n%d label%s couldn't be added (%s)." % (len(label_errors), "" if len(label_errors) == 1 else "s",
                                                       label_errors[0])
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
