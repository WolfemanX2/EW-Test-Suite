# -*- coding: utf-8 -*-
# SLC Riser script - version v2
__title__ = "SLC\nRiser"
__doc__ = ("Draws a one-line SLC riser diagram in a new drafting view.\n\n"
           "Select (or pick) the panel the conduit starts from. The tool follows the connected conduit from "
           "it and draws every Fire Alarm Device that has an SLC address (SLC Address, SLC Address 2 ... 24) "
           "in order of connection, one row per conduit run leaving the panel, with its full addresses "
           "(N#L#M# / N#L#D#) underneath. Each row is labeled with its loop (L#), read from those addresses. "
           "Where the conduit splits, the shorter side is drawn as its own T-tap row.\n\n"
           "Each Family : Type is drawn with the symbol set for it in the Riser Symbols tool. "
           "Devices on the conduit without an SLC address are passed through and listed afterwards.")

from Autodesk.Revit.DB import (
    XYZ, Line, Transaction, FilteredElementCollector, FamilyInstance, ViewDrafting, ViewFamilyType,
    ViewFamily, TextNote, TextNoteType, TextNoteOptions, HorizontalTextAlignment, ElementTypeGroup,
    ElementId, BuiltInParameter
)
from Autodesk.Revit.UI.Selection import ObjectType, ISelectionFilter
from Autodesk.Revit.Exceptions import OperationCanceledException
from pyrevit import revit, forms, script

import slc_riser as sr
import riser_layout as rl

doc = revit.doc
uidoc = revit.uidoc
output = script.get_output()

TITLE = "SLC Riser"

# ---------------- Settings ----------------
VIEW_SCALE = 48         # scale of the new drafting view (48 = 1/4" = 1'-0")
PER_LINE = 10           # devices on one line before the row wraps underneath
# Sizes on the printed sheet, in inches:
SPACING = 1.0           # device to device (widened automatically if a symbol is wider than this allows)
ROW_GAP = 0.5           # extra space between rows
PAD = 0.125             # space above and below each line of devices
TEXT_GAP = 0.06         # between a symbol and the addresses under it
BOX_SIZE = 0.375        # box drawn for a type that has no symbol
PANEL_BOX = (0.75, 0.5) # width, height of the box drawn for a panel that has no symbol
MAX_SYMBOL = 2.0        # a symbol measured larger than this is treated as this size
LINE_SPACING = 1.6      # text line height as a multiple of the text size


def paper(inches):
    """Inches on the sheet -> feet in the view."""
    return inches / 12.0 * VIEW_SCALE


# ---------- Starting element ----------
class ConduitSourceFilter(ISelectionFilter):
    """Allows family instances that conduit can connect to."""
    def AllowElement(self, elem):
        try:
            return isinstance(elem, FamilyInstance) and len(sr.conduit_connectors(elem)) > 0
        except Exception:
            return False

    def AllowReference(self, ref, pt):
        return False


def starting_element():
    ids = list(uidoc.Selection.GetElementIds())
    if len(ids) == 1:
        el = doc.GetElement(ids[0])
        if isinstance(el, FamilyInstance) and sr.conduit_connectors(el):
            return el
    try:
        ref = uidoc.Selection.PickObject(ObjectType.Element, ConduitSourceFilter(),
                                         "Pick the panel the SLC conduit starts from")
    except OperationCanceledException:
        return None
    return doc.GetElement(ref.ElementId)


def element_name(el):
    """What a panel is called on the diagram."""
    for bip in (BuiltInParameter.RBS_ELEC_PANEL_NAME, BuiltInParameter.ALL_MODEL_MARK):
        try:
            p = el.get_Parameter(bip)
            text = (p.AsString() or "").strip() if p is not None else ""
        except Exception:
            text = ""
        if text:
            return text
    try:
        return sr.type_name(doc.GetElement(el.GetTypeId()))
    except Exception:
        return "PANEL"


# ---------- Tracing ----------
def trace_from(root):
    """(rows, returns, elements, addresses, unaddressed devices) for the conduit connected to root."""
    elements = {}       # id -> element
    addresses = {}      # id -> [SLC addresses] for fire alarm devices
    port_cache = {}

    def remember(el):
        i = sr.eid_int(el.Id)
        if i not in elements:
            elements[i] = el
            if sr.is_device(el):
                addresses[i] = sr.slc_addresses(el)
        return i

    def ports(i):
        if i not in port_cache:
            port_cache[i] = [[remember(e) for e in group] for group in sr.connected_elements(elements[i])]
        return port_cache[i]

    def is_node(i):
        return bool(addresses.get(i))

    root_id = remember(root)
    children, returns, passed = rl.trace(root_id, ports, is_node)
    rows = rl.build_rows(root_id, children)
    for row in rows:
        row["label"] = sr.loop_label([addresses[n] for n in row["nodes"]])
    unaddressed = [elements[i] for i in passed if i in addresses]
    return rows, returns, elements, addresses, unaddressed


# ---------- Drawing ----------
def new_drafting_view(name):
    vft = None
    for t in FilteredElementCollector(doc).OfClass(ViewFamilyType).ToElements():
        if t.ViewFamily == ViewFamily.Drafting:
            vft = t
            break
    if vft is None:
        raise Exception("This project has no drafting view type.")
    view = ViewDrafting.Create(doc, vft.Id)
    view.Scale = VIEW_SCALE
    taken = set(v.Name for v in FilteredElementCollector(doc).OfClass(ViewDrafting).ToElements()
                if v.Id != view.Id)
    candidate, n = name, 1
    while candidate in taken:
        n += 1
        candidate = "%s (%d)" % (name, n)
    try:
        view.Name = candidate
    except Exception:
        pass    # keeps the name Revit gave it
    return view


def text_type():
    """(TextNoteType id, line height in view feet) of the project's default text type."""
    tid = doc.GetDefaultElementTypeId(ElementTypeGroup.TextNoteType)
    tt = doc.GetElement(tid) if tid is not None and tid != ElementId.InvalidElementId else None
    if tt is None:
        tt = FilteredElementCollector(doc).OfClass(TextNoteType).FirstElement()
        if tt is None:
            raise Exception("This project has no text types.")
    size = tt.get_Parameter(BuiltInParameter.TEXT_SIZE).AsDouble()      # feet on the sheet
    return tt.Id, size * VIEW_SCALE * LINE_SPACING


def measure_symbols(view, symbols):
    """{symbol id: (left, right, up, down)} - how far each symbol reaches from its insertion point,
    found by placing one, measuring it and deleting it again."""
    cap = paper(MAX_SYMBOL) / 2.0
    default = paper(BOX_SIZE) / 2.0
    placed = {}
    for key, sym in symbols.items():
        try:
            placed[key] = doc.Create.NewFamilyInstance(XYZ(0, 0, 0), sym, view)
        except Exception:
            pass
    doc.Regenerate()
    sizes = {}
    for key in symbols:
        ext = (default, default, default, default)
        inst = placed.get(key)
        if inst is not None:
            try:
                bb = inst.get_BoundingBox(view)
                if bb is not None:
                    ext = tuple(min(max(v, 0.0), cap) for v in (-bb.Min.X, bb.Max.X, bb.Max.Y, -bb.Min.Y))
            except Exception:
                pass
            doc.Delete(inst.Id)
        sizes[key] = ext
    return sizes


def draw(view, plan, node_symbol, type_id):
    """Create everything in the layout. Returns the number of things that could not be created."""
    failed = [0]
    min_len = doc.Application.ShortCurveTolerance

    def line(p, q):
        if abs(p[0] - q[0]) + abs(p[1] - q[1]) <= min_len:
            return
        try:
            doc.Create.NewDetailCurve(view, Line.CreateBound(XYZ(p[0], p[1], 0), XYZ(q[0], q[1], 0)))
        except Exception:
            failed[0] += 1

    for x, y, n in plan["symbols"]:
        try:
            doc.Create.NewFamilyInstance(XYZ(x, y, 0), node_symbol[n], view)
        except Exception:
            failed[0] += 1
    for x, y, l, r, u, d in plan["boxes"]:
        corners = [(x - l, y - d), (x + r, y - d), (x + r, y + u), (x - l, y + u)]
        for i in range(4):
            line(corners[i], corners[(i + 1) % 4])
    for p, q in plan["lines"]:
        line(p, q)
    align = {"L": HorizontalTextAlignment.Left, "C": HorizontalTextAlignment.Center,
             "R": HorizontalTextAlignment.Right}
    for x, y, text, how in plan["texts"]:
        try:
            opts = TextNoteOptions(type_id)
            opts.HorizontalAlignment = align[how]
            TextNote.Create(doc, view.Id, XYZ(x, y, 0), text, opts)
        except Exception:
            failed[0] += 1
    return failed[0]


# ---------- Main ----------
def main():
    root = starting_element()
    if root is None:
        return
    rows, returns, elements, addresses, unaddressed = trace_from(root)
    root_id = sr.eid_int(root.Id)
    if not rows:
        msg = "No devices with an SLC address are connected by conduit to the selected element."
        if unaddressed:
            msg += ("\n\n%d Fire Alarm Device(s) on that conduit have no value in SLC Address "
                    "(or SLC Address 2 ... %d)." % (len(unaddressed), sr.SLC_ADDRESS_COUNT))
        forms.alert(msg, title=TITLE)
        return

    try:
        table = sr.load_table()
    except Exception as ex:
        forms.alert("Could not read the symbol table:\n%s\n\nPath: %s" % (ex, sr.table_path()), title=TITLE)
        return
    available = sr.available_symbols(doc)

    # Symbol for each thing drawn.
    drawn = [root_id] + [n for row in rows for n in row["nodes"]]
    keys = dict((n, sr.family_key(doc, elements[n])) for n in drawn)
    node_symbol, missing = {}, {}
    for n in drawn:
        wanted = table.get(keys[n], "")
        if wanted in available:
            node_symbol[n] = available[wanted]
        elif n != root_id or wanted:
            missing[keys[n]] = ("symbol '%s' is not loaded in this project" % wanted) if wanted else "no symbol set"
    if missing:
        listing = "\n".join("%s  -  %s" % (k, missing[k]) for k in sorted(missing)[:15])
        if len(missing) > 15:
            listing += "\n... and %d more" % (len(missing) - 15)
        go_on = forms.alert("%d type(s) on this riser have no symbol to draw:\n\n%s\n\n"
                            "Draw them as boxes labeled with the type name? (Choose No to stop and set them "
                            "in Riser Symbols first.)" % (len(missing), listing),
                            title=TITLE, yes=True, no=True)
        if not go_on:
            return

    t = Transaction(doc, "Create SLC riser")
    t.Start()
    try:
        view = new_drafting_view("SLC Riser - %s" % element_name(root))
        type_id, line_h = text_type()
        used = {}
        for sym in node_symbol.values():
            used[sr.eid_int(sym.Id)] = sym
        for sym in used.values():
            if not sym.IsActive:
                sym.Activate()
        doc.Regenerate()
        sizes = measure_symbols(view, used)

        box = paper(BOX_SIZE) / 2.0
        info = {}
        for n in drawn:
            lines = list(addresses.get(n, []))
            if n == root_id:
                lines = [element_name(root)]
            if n in node_symbol:
                ext = sizes[sr.eid_int(node_symbol[n].Id)]
            elif n == root_id:
                w, h = paper(PANEL_BOX[0]) / 2.0, paper(PANEL_BOX[1]) / 2.0
                ext = (w, w, h, h)
            else:
                ext = (box, box, box, box)
                lines.insert(0, keys[n].split(" : ")[-1])
            info[n] = {"mapped": n in node_symbol, "ext": ext, "lines": lines}

        widest = max(i["ext"][0] + i["ext"][1] for n, i in info.items() if n != root_id)
        cfg = {"spacing": max(paper(SPACING), widest + paper(0.375)), "per_line": PER_LINE,
               "pad": paper(PAD), "text_gap": paper(TEXT_GAP), "line_h": line_h, "row_gap": paper(ROW_GAP)}
        plan = rl.layout(rows, root_id, info, returns, cfg)
        failed = draw(view, plan, node_symbol, type_id)
        t.Commit()
    except Exception as ex:
        if t.HasStarted() and not t.HasEnded():
            t.RollBack()
        forms.alert("The riser could not be created:\n%s" % ex, title=TITLE)
        return

    try:
        uidoc.ActiveView = view
    except Exception:
        pass

    count = sum(len(row["nodes"]) for row in rows)
    runs = len([row for row in rows if row["source"] is None])
    taps = len(rows) - runs
    msg = "Created '%s': %d device(s) on %d run(s)" % (view.Name, count, runs)
    if taps:
        msg += " and %d T-tap(s)" % taps
    msg += "."
    if failed:
        msg += "\n\n%d item(s) could not be drawn." % failed
    if unaddressed:
        msg += ("\n\n%d Fire Alarm Device(s) on the conduit have no SLC address and were left off. "
                "They are listed in the output window." % len(unaddressed))
        output.print_md("### %s - devices on the conduit without an SLC address" % TITLE)
        for el in unaddressed:
            output.print_md("- %s %s" % (output.linkify(el.Id), sr.family_key(doc, el)))
    forms.alert(msg, title=TITLE)


main()
