# -*- coding: utf-8 -*-
# SLC Riser script - version v13
__title__ = "SLC\nRiser v13"
__doc__ = ("Draws a one-line SLC riser diagram in a new drafting view named "
           "<LEVEL> - SLC RISER - <PANEL #> (the panel's level and its Panel # parameter, in capitals).\n\n"
           "Select (or pick) the panel the conduit starts from, then pick the first device of each loop "
           "(a device or panel can also be picked by its tag) "
           "(Esc when finished). Each loop is followed along its conduit starting at that device, away from "
           "the panel, so the device you pick decides the order. Press Esc without picking any to follow "
           "every conduit run leaving the panel instead. The tool draws every Fire Alarm Device that has an SLC address (SLC Address, SLC Address 2 ... 24) "
           "in order of connection, one row per conduit run leaving the panel, with its full address "
           "(N#L#M# / N#L#D#) underneath; a device with several addresses shows the first and last on two "
           "lines (first- / last). The address text is at 45 degrees, right justified, hanging below "
           "the riser line, its top corner 1\" under its device; devices are 6' apart, and the riser line runs unbroken through the devices. Each row is labeled with its loop as a letter (L1 = A, L2 = B ...), read from those addresses. "
           "Where the conduit splits, the shorter side is drawn as its own T-tap row.\n\n"
           "Only conduit of the types you choose is followed (the types connected to the first devices are "
           "ticked to start with), so a tee onto conduit of another type (NAC, power) is not a T-tap.\n\n"
           "Each Family : Type is drawn with the symbol set for it in SLC Riser - Config. A type without "
           "one is asked about when the tool runs, and the choice is saved to the table. "
           "A device whose Panel # parameter has a value shows it above its symbol (5/64\" text).\n\n"
           "View scale, device spacing, devices per line, wrap rounding and the label offset are set in SLC Riser - Config.\n\n"
           "Devices on the conduit without an SLC address are passed through and listed afterwards.")

from Autodesk.Revit.DB import (
    XYZ, Line, Transaction, FilteredElementCollector, FamilyInstance, ViewDrafting, ViewFamilyType,
    ViewFamily, TextNote, StorageType, TextNoteType, TextNoteOptions, HorizontalTextAlignment, ElementTypeGroup,
    ElementId, BuiltInParameter, IndependentTag
)
try:
    from Autodesk.Revit.DB import VerticalTextAlignment
except ImportError:
    VerticalTextAlignment = None    # older Revit: text is placed by its top already
from Autodesk.Revit.DB.Electrical import Conduit
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
# These four come from SLC Riser - Config (riser_settings.json); the values here are replaced in main().
VIEW_SCALE = 96         # scale of the new drafting view (96 = 1/8" = 1'-0")
PER_LINE = 5            # devices on one line before the row wraps underneath
WRAP_ROUNDING = 0       # a line only wraps when it would have more than PER_LINE + this
DEVICE_SPACING_FT = 4.5 # device centre to device centre, in feet in the view
LABEL_OFFSET_IN = 1.0   # device address text starts this many inches (in the view) below the riser line
ABOVE_TEXT_SIZE_IN = 5.0 / 64.0     # text above a device (its Panel #): size on the sheet, in inches
ABOVE_TEXT_TYPE_NAME = 'SLC Riser 5/64"'    # made from the default text type if no 5/64" type exists
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
def tagged_hosts(tag):
    """Local elements a tag is hosted to (version tolerant)."""
    ids = []
    try:
        ids = list(tag.GetTaggedLocalElementIds())      # Revit 2022+
    except Exception:
        try:
            ids = [tag.TaggedLocalElementId]            # older Revit
        except Exception:
            ids = []
    hosts = []
    for eid in ids:
        try:
            el = doc.GetElement(eid)
        except Exception:
            el = None
        if el is not None:
            hosts.append(el)
    return hosts


def resolve(elem, ok):
    """elem itself if ok(elem), or the first element a picked tag is hosted to that is ok; else None."""
    if elem is None:
        return None
    try:
        if ok(elem):
            return elem
    except Exception:
        pass
    if isinstance(elem, IndependentTag):
        for host in tagged_hosts(elem):
            try:
                if ok(host):
                    return host
            except Exception:
                pass
    return None


def is_conduit_source(el):
    return isinstance(el, FamilyInstance) and len(sr.conduit_connectors(el)) > 0


def is_addressed_device(el):
    return sr.is_device(el) and len(sr.slc_addresses(el)) > 0


class ElementOrTagFilter(ISelectionFilter):
    """Allows elements that pass ok, or tags hosted to one."""
    def __init__(self, ok):
        self.ok = ok

    def AllowElement(self, elem):
        try:
            return resolve(elem, self.ok) is not None
        except Exception:
            return False

    def AllowReference(self, ref, pt):
        return False


def starting_element():
    ids = list(uidoc.Selection.GetElementIds())
    if len(ids) == 1:
        el = resolve(doc.GetElement(ids[0]), is_conduit_source)
        if el is not None:
            return el
    try:
        ref = uidoc.Selection.PickObject(ObjectType.Element, ElementOrTagFilter(is_conduit_source),
                                         "Pick the panel (or its tag) the SLC conduit starts from")
    except OperationCanceledException:
        return None
    return resolve(doc.GetElement(ref.ElementId), is_conduit_source)


def first_devices(root):
    """Devices picked (directly or by their tags) as the first of each loop, in pick order.
    Empty = follow every run from the panel."""
    picked, seen = [], set([sr.eid_int(root.Id)])
    flt = ElementOrTagFilter(is_addressed_device)
    while True:
        prompt = ("Pick the FIRST device (or its tag) of loop %d (Esc when finished%s)"
                  % (len(picked) + 1, "" if picked else "; Esc now = follow every run from the panel"))
        try:
            ref = uidoc.Selection.PickObject(ObjectType.Element, flt, prompt)
        except OperationCanceledException:
            return picked
        el = resolve(doc.GetElement(ref.ElementId), is_addressed_device)
        if el is None:
            continue
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
class Network(object):
    """The conduit connections around the panel, read from the model as they are needed.
    allowed: conduit type ids (ints) that may be followed; None = any conduit."""
    def __init__(self):
        self.elements = {}      # id -> element
        self.addresses = {}     # id -> [SLC addresses] for fire alarm devices
        self.conduit_type = {}  # id -> conduit type id, for conduit
        self.type_elem_ids = {} # conduit type id -> its ElementId
        self._cache = {}
        self.allowed = None

    def remember(self, el):
        i = sr.eid_int(el.Id)
        if i not in self.elements:
            self.elements[i] = el
            if sr.is_device(el):
                self.addresses[i] = sr.slc_addresses(el)
            elif isinstance(el, Conduit):
                tid = el.GetTypeId()
                self.conduit_type[i] = sr.eid_int(tid)
                self.type_elem_ids[sr.eid_int(tid)] = tid
        return i

    def raw_ports(self, i):
        if i not in self._cache:
            self._cache[i] = [[self.remember(e) for e in group]
                              for group in sr.connected_elements(self.elements[i])]
        return self._cache[i]

    def followed(self, i):
        t = self.conduit_type.get(i)
        return t is None or self.allowed is None or t in self.allowed

    def ports(self, i):
        groups = self.raw_ports(i)
        if self.allowed is None:
            return groups
        return [[e for e in g if self.followed(e)] for g in groups]

    def is_node(self, i):
        return bool(self.addresses.get(i))

    def conduit_types_at(self, ids):
        """Conduit type ids joined to these elements, directly or through one fitting / box."""
        found = set()
        for i in ids:
            for g in self.raw_ports(i):
                for e in g:
                    if e in self.conduit_type:
                        found.add(self.conduit_type[e])
                    elif e not in self.addresses:
                        for g2 in self.raw_ports(e):
                            for e2 in g2:
                                if e2 in self.conduit_type:
                                    found.add(self.conduit_type[e2])
        return found

    def all_conduit_types(self, root_id):
        """Conduit type ids used anywhere in the conduit connected to the panel (followed without a filter)."""
        found, seen, queue = set(), set([root_id]), [root_id]
        while queue:
            i = queue.pop()
            if i in self.conduit_type:
                found.add(self.conduit_type[i])
            for g in self.raw_ports(i):
                for e in g:
                    if e not in seen:
                        seen.add(e)
                        queue.append(e)
        return found


class ConduitTypeChoice(object):
    """One conduit type in the list of types to follow."""
    def __init__(self, tid, name):
        self.tid = tid
        self.name = name

    def __str__(self):
        return self.name


def conduit_type_name(net, tid):
    t = None
    try:
        t = doc.GetElement(net.type_elem_ids[tid])
    except Exception:
        pass
    if t is None:
        return "Conduit type %d" % tid
    try:
        return "%s : %s" % (t.FamilyName, sr.type_name(t))
    except Exception:
        return sr.type_name(t)


def choose_conduit_types(net, root_id, start_ids):
    """Conduit type ids to follow, or None if the user cancelled. Asks only when there is a choice."""
    in_network = net.all_conduit_types(root_id)
    if len(in_network) <= 1:
        return in_network
    ticked = (net.conduit_types_at(start_ids) & in_network) or in_network
    choices = sorted((ConduitTypeChoice(tid, conduit_type_name(net, tid)) for tid in in_network),
                     key=lambda c: c.name)
    items = [forms.TemplateListItem(c, checked=(c.tid in ticked), name_attr="name") for c in choices]
    picked = forms.SelectFromList.show(items, title="Follow which conduit types? (ticked: at the first devices)",
                                       button_name="Follow", multiselect=True)
    if not picked:
        return None
    return set(c.tid for c in picked)


def trace_from(root, firsts):
    """(rows, returns, elements, addresses, unaddressed devices) for the conduit connected to root, or None
    if the user cancelled. firsts: the first device of each loop (empty = every run leaving root)."""
    net = Network()
    root_id = net.remember(root)
    starts = [net.remember(el) for el in firsts]
    allowed = choose_conduit_types(net, root_id, starts or [root_id])
    if allowed is None:
        return None
    net.allowed = allowed
    children, returns, passed = rl.trace(root_id, net.ports, net.is_node, starts or None)
    rows = rl.build_rows(root_id, children)
    for row in rows:
        row["label"] = sr.loop_label([net.addresses[n] for n in row["nodes"]])
    unaddressed = [net.elements[i] for i in passed if i in net.addresses]
    return rows, returns, net.elements, net.addresses, unaddressed


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


def small_text_type(base_id):
    """(TextNoteType id, line height in view feet) for the 5/64" text above devices: an existing text type of
    that size (the default one's font first), else a copy of the default type set to that size."""
    want = ABOVE_TEXT_SIZE_IN / 12.0
    base = doc.GetElement(base_id)

    def font(t):
        try:
            return t.get_Parameter(BuiltInParameter.TEXT_FONT).AsString()
        except Exception:
            return None

    found = None
    for t in FilteredElementCollector(doc).OfClass(TextNoteType).ToElements():
        try:
            size = t.get_Parameter(BuiltInParameter.TEXT_SIZE).AsDouble()
        except Exception:
            continue
        if abs(size - want) < 1e-6:
            if found is None or font(t) == font(base):
                found = t
            if font(t) == font(base):
                break
    if found is None:
        found = base.Duplicate(ABOVE_TEXT_TYPE_NAME)
        found.get_Parameter(BuiltInParameter.TEXT_SIZE).Set(want)
    return found.Id, want * VIEW_SCALE * LINE_SPACING


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


def draw(view, plan, node_symbol, type_id, line_h, above_type_id=None):
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
            if how == "A":
                opts = TextNoteOptions(above_type_id or type_id)
                opts.HorizontalAlignment = HorizontalTextAlignment.Center
                TextNote.Create(doc, view.Id, XYZ(x, y, 0), text, opts)
                continue
            opts = TextNoteOptions(type_id)
            opts.HorizontalAlignment = align[how]
            TextNote.Create(doc, view.Id, XYZ(x, y, 0), text, opts)
        except Exception:
            failed[0] += 1
    return failed[0]


# ---------- Main ----------
def apply_settings():
    """Use the drawing settings saved in SLC Riser - Config. False if the file can't be read and the user
    chose to stop."""
    global VIEW_SCALE, PER_LINE, WRAP_ROUNDING, DEVICE_SPACING_FT, LABEL_OFFSET_IN
    try:
        settings = sr.load_settings()
    except Exception as ex:
        go_on = forms.alert("Could not read the riser settings, so the defaults will be used:\n%s\n\nPath: %s"
                            "\n\nContinue?" % (ex, sr.settings_path()), title=TITLE, yes=True, no=True)
        if not go_on:
            return False
        settings = dict(sr.DEFAULT_SETTINGS)
    VIEW_SCALE = settings["view_scale"]
    PER_LINE = settings["devices_per_line"]
    WRAP_ROUNDING = settings["wrap_rounding"]
    DEVICE_SPACING_FT = settings["device_spacing_ft"]
    LABEL_OFFSET_IN = settings["label_offset_in"]
    return True


def main():
    if not apply_settings():
        return
    root = starting_element()
    if root is None:
        return
    firsts = first_devices(root)
    traced = trace_from(root, firsts)
    if traced is None:
        return
    rows, returns, elements, addresses, unaddressed = traced
    root_id = sr.eid_int(root.Id)
    if not rows:
        msg = ("No devices with an SLC address are connected to the selected element by conduit of the "
               "chosen type(s).")
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
        above_type_id, above_h = None, line_h
        if any(named_value(elements[n], PANEL_NUMBER_PARAM) for n in drawn if n != root_id):
            above_type_id, above_h = small_text_type(type_id)
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
            above = named_value(elements[n], PANEL_NUMBER_PARAM) if n != root_id else ""
            info[n] = {"mapped": n in node_symbol, "ext": ext, "lines": lines, "above": above}

        char_w = line_h / LINE_SPACING * 0.7    # a character is taken as about 0.7 of the text size wide
        cfg = {"spacing": DEVICE_SPACING_FT, "per_line": PER_LINE, "wrap_rounding": WRAP_ROUNDING, "char_w": char_w,
               "label_offset": LABEL_OFFSET_IN / 12.0, "above_h": above_h,
               "pad": paper(PAD), "text_gap": paper(TEXT_GAP), "line_h": line_h, "row_gap": paper(ROW_GAP)}
        plan = rl.layout(rows, root_id, info, returns, cfg)
        failed = draw(view, plan, node_symbol, type_id, line_h, above_type_id)
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
