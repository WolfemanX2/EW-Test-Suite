# -*- coding: utf-8 -*-
# SLC Riser script - version v8
__title__ = "SLC\nRiser v8"
__doc__ = ("Draws a one-line SLC riser diagram in a new drafting view named "
           "<LEVEL> - SLC RISER - <PANEL #> (the panel's level and its Panel # parameter, in capitals).\n\n"
           "Select (or pick) the panel the conduit starts from, then pick the first device of each loop "
           "(Esc when finished). Each loop is followed along its conduit starting at that device, away from "
           "the panel, so the device you pick decides the order. Press Esc without picking any to follow "
           "every conduit run leaving the panel instead. The tool draws every Fire Alarm Device that has an SLC address (SLC Address, SLC Address 2 ... 24) "
           "in order of connection, one row per conduit run leaving the panel, with its full address "
           "(N#L#M# / N#L#D#) underneath; a device with several addresses shows the first and last on two "
           "lines (first- / last). The address text is at 45 degrees, right justified, hanging below "
           "the riser line, its top corner 1\" under its device; devices are 6' apart, and the riser line runs unbroken through the devices. Each row is labeled with its loop (L#), read from those addresses. "
           "Where the conduit splits, the shorter side is drawn as its own T-tap row.\n\n"
           "Each Family : Type is drawn with the symbol set for it in SLC Riser - Config. A type without "
           "one is asked about when the tool runs, and the choice is saved to the table. "
           "Devices on the conduit without an SLC address are passed through and listed afterwards.")

from Autodesk.Revit.DB import (
    XYZ, Line, Transaction, FilteredElementCollector, FamilyInstance, ViewDrafting, ViewFamilyType,
    ViewFamily, TextNote, StorageType, TextNoteType, TextNoteOptions, HorizontalTextAlignment, ElementTypeGroup,
    ElementId, BuiltInParameter
)
try:
    from Autodesk.Revit.DB import VerticalTextAlignment
except ImportError:
    VerticalTextAlignment = None    # older Revit: text is placed by its top already
from Autodesk.Revit.UI.Selection import ObjectType, ISelectionFilter
from Autodesk.Revit.Exceptions import OperationCanceledException
from pyrevit import revit, forms, script

import math

import slc_riser as sr
import riser_layout as rl

doc = revit.doc
uidoc = revit.uidoc
output = script.get_output()

TITLE = "SLC Riser"

# ---------------- Settings ----------------
VIEW_SCALE = 96         # scale of the new drafting view (96 = 1/8" = 1'-0")
PER_LINE = 5           # devices on one line before the row wraps underneath
DEVICE_SPACING_FT = 4.5# device centre to device centre, in feet in the view
LABEL_OFFSET_IN = 1.0       # device address text starts this many inches (in the view) below the riser line
# Sizes on the printed sheet, in inches:
ROW_GAP = 0.5           # extra space between rows
PAD = 0.125             # space above and below each line of devices
TEXT_GAP = 0.06         # between a symbol and the addresses under it
BOX_SIZE = 0.375        # box drawn for a type that has no symbol
PANEL_BOX = (0.75, 0.5) # width, height of the box drawn for a panel that has no symbol
MAX_SYMBOL = 2.0        # a symbol measured larger than this is treated as this size
LINE_SPACING = 1.6      # text line height as a multiple of the text size
PANEL_NUMBER_PARAM = "Panel #"      # the panel's name on the diagram and in the view name
LABEL_ANGLE = math.pi / 4.0         # device address text: 45 degrees


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


class AddressedDeviceFilter(ISelectionFilter):
    """Allows Fire Alarm Devices that have an SLC address."""
    def AllowElement(self, elem):
        try:
            return sr.is_device(elem) and len(sr.slc_addresses(elem)) > 0
        except Exception:
            return False

    def AllowReference(self, ref, pt):
        return False


def first_devices(root):
    """Devices picked as the first of each loop, in pick order. Empty = follow every run from the panel."""
    picked, seen = [], set([sr.eid_int(root.Id)])
    flt = AddressedDeviceFilter()
    while True:
        prompt = ("Pick the FIRST device of loop %d (Esc when finished%s)"
                  % (len(picked) + 1, "" if picked else "; Esc now = follow every run from the panel"))
        try:
            ref = uidoc.Selection.PickObject(ObjectType.Element, flt, prompt)
        except OperationCanceledException:
            return picked
        el = doc.GetElement(ref.ElementId)
        i = sr.eid_int(el.Id)
        if i in seen:
            forms.toast("Already picked.")
            continue
        seen.add(i)
        picked.append(el)


def named_value(el, name):
    """Text of the parameter with that name (case ignored) on the element or its type, or ''."""
    wanted = name.strip().lower()
    holders = [el]
    try:
        holders.append(doc.GetElement(el.GetTypeId()))
    except Exception:
        pass
    for holder in holders:
        if holder is None:
            continue
        for p in holder.Parameters:
            try:
                if p.Definition.Name.strip().lower() != wanted or not p.HasValue:
                    continue
                text = p.AsString() if p.StorageType == StorageType.String else p.AsValueString()
            except Exception:
                continue
            text = (text or "").strip()
            if text:
                return text
    return ""


def element_name(el):
    """What a panel is called on the diagram: its Panel #, else its panel name, Mark or type name."""
    text = named_value(el, PANEL_NUMBER_PARAM)
    if text:
        return text
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


def level_name(el):
    """Name of the level the element is hosted on, or ''."""
    ids = []
    try:
        ids.append(el.LevelId)
    except Exception:
        pass
    for bip in (BuiltInParameter.FAMILY_LEVEL_PARAM, BuiltInParameter.INSTANCE_SCHEDULE_ONLY_LEVEL_PARAM,
                BuiltInParameter.INSTANCE_REFERENCE_LEVEL_PARAM):
        try:
            p = el.get_Parameter(bip)
            if p is not None:
                ids.append(p.AsElementId())
        except Exception:
            pass
    try:
        ids.append(el.Host.LevelId)     # hosted on a wall, floor or ceiling
    except Exception:
        pass
    for lid in ids:
        try:
            if lid is None or lid == ElementId.InvalidElementId:
                continue
            level = doc.GetElement(lid)
            if level is not None and level.Name:
                return level.Name
        except Exception:
            pass
    return ""


def view_name(root):
    """LEVEL 1 - SLC RISER - FACU-01"""
    parts = [level_name(root), "SLC Riser", element_name(root)]
    name = " - ".join(p for p in parts if p).upper()
    for ch in "\\:{}[]|;<>?`~":      # characters Revit does not allow in a view name
        name = name.replace(ch, "-")
    return name


# ---------- Tracing ----------
def trace_from(root, firsts):
    """(rows, returns, elements, addresses, unaddressed devices) for the conduit connected to root.
    firsts: the first device of each loop (empty = every run leaving root)."""
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
    starts = [remember(el) for el in firsts]
    children, returns, passed = rl.trace(root_id, ports, is_node, starts or None)
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


def device_label(view, x, y, text, type_id):
    """A device's address text: 45 degrees, right justified, hanging down to the left, with its uppermost
    corner (the top right one) on the riser line at the device centreline (x, y)."""
    opts = TextNoteOptions(type_id)
    opts.HorizontalAlignment = HorizontalTextAlignment.Right
    opts.Rotation = LABEL_ANGLE
    if VerticalTextAlignment is not None:
        try:
            opts.VerticalAlignment = VerticalTextAlignment.Top
        except Exception:
            pass
    TextNote.Create(doc, view.Id, XYZ(x, y, 0), text, opts)


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


def draw(view, plan, node_symbol, type_id, line_h):
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
            if how == "D":
                device_label(view, x, y, text, type_id)
                continue
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
    firsts = first_devices(root)
    rows, returns, elements, addresses, unaddressed = trace_from(root, firsts)
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
    chosen, missing = {}, []    # type key -> symbol key; type keys with no usable symbol
    for n in drawn:
        key = keys[n]
        wanted = table.get(key, "")
        if wanted in available:
            chosen[key] = wanted
        elif key not in missing:
            missing.append(key)
    if missing:
        names = sorted(available.keys())
        if not names:
            go_on = forms.alert("No Generic Annotation or Detail Item types are loaded in this project, so "
                                "there are no symbols to choose from.\n\nDraw every device as a box labeled "
                                "with its type name?", title=TITLE, yes=True, no=True)
            if not go_on:
                return
        else:
            picked_any = False
            for i, key in enumerate(missing, start=1):
                wanted = table.get(key, "")
                if wanted:
                    forms.toast("Saved symbol '%s' for %s is not loaded in this project." % (wanted, key))
                picked = forms.SelectFromList.show(
                    names, title="Symbol for %s  (%d of %d without one)" % (key, i, len(missing)),
                    button_name="Use Symbol", multiselect=False)
                if picked:
                    chosen[key] = picked
                    table[key] = picked
                    picked_any = True
                    continue
                go_on = forms.alert("No symbol chosen for:\n%s\n\nDraw it as a box labeled with the type name? "
                                    "(Choose No to stop without creating the riser.)" % key,
                                    title=TITLE, yes=True, no=True)
                if not go_on:
                    break
            else:
                go_on = True
            if picked_any:      # remembered for next time, even if this run was stopped
                try:
                    sr.save_table(table)
                except Exception as ex:
                    forms.alert("The symbols you chose are used for this riser but could not be saved:\n%s"
                                "\n\nPath: %s" % (ex, sr.table_path()), title=TITLE)
            if not go_on:
                return
    node_symbol = dict((n, available[chosen[keys[n]]]) for n in drawn if keys[n] in chosen)

    t = Transaction(doc, "Create SLC riser")
    t.Start()
    try:
        view = new_drafting_view(view_name(root))
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
            if len(lines) > 1:
                lines = [lines[0] + "-", lines[-1]]     # several addresses: first- / last, on two lines
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

        char_w = line_h / LINE_SPACING * 0.7    # a character is taken as about 0.7 of the text size wide
        cfg = {"spacing": DEVICE_SPACING_FT, "per_line": PER_LINE, "char_w": char_w,
               "label_offset": LABEL_OFFSET_IN / 12.0,
               "pad": paper(PAD), "text_gap": paper(TEXT_GAP), "line_h": line_h, "row_gap": paper(ROW_GAP)}
        plan = rl.layout(rows, root_id, info, returns, cfg)
        failed = draw(view, plan, node_symbol, type_id, line_h)
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
