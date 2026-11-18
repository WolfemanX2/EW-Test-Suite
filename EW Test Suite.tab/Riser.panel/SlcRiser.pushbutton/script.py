# -*- coding: utf-8 -*-
# SLC Riser script - version v18
__title__ = "SLC\nRiser v18"
__doc__ = ("Draws a one-line SLC riser diagram in a new drafting view named "
           "<LEVEL> - SLC RISER - <PANEL #> (the panel's level and its Panel # parameter, in capitals).\n\n"
           "Steps: select the head end panel (FACU, NCP, APS ...), then the first device in the circuit "
           "(either can be picked by its tag), choose the conduit types to trace, then check the device "
           "count and adjust spacing / wrapping, then choose to generate a new drafting view or add the circuit to "
           "an existing one (it goes 10' above what is already there) before the riser is drawn. The circuit is followed along "
           "its conduit starting at the first device, away from the panel, so that device decides the "
           "order. Press Esc instead of picking a first device to follow every conduit run leaving the "
           "panel. The tool draws every Fire Alarm Device that has an SLC address (SLC Address, SLC Address 2 ... 24) "
           "in order of connection, one row per conduit run leaving the panel, with its full address "
           "(N#L#M# / N#L#D#) underneath; a device with several addresses shows the first and last on two "
           "lines (first- / last). The address text is at 45 degrees, right justified, hanging below "
           "the riser line, its top corner 1\" under its device; devices are 6' apart, and the riser line runs unbroken through the devices. Each row is labeled with its loop as a letter (L1 = A, L2 = B ...), read from those addresses. "
           "The head end panel is drawn with the NEX2-DETAIL-RISER detail item (Panel # and Location - the "
           "room name and number - filled in from the panel); every run comes out of its right side, the first "
           "device one device spacing away. Each loop leaves the panel in line with the family's reference line "
           "whose subcategory is that loop number (N1L3 -> reference line 3). "
           "When a row wraps, the next line runs the opposite way (left to right, then right to left, and so "
           "on), with the devices following it. Where the conduit splits, the shorter side is drawn as its own T-tap row.\n\n"
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
    ElementId, BuiltInParameter, IndependentTag, ElementTransformUtils
)
from System.Collections.Generic import List
try:
    from Autodesk.Revit.DB import VerticalTextAlignment
except ImportError:
    VerticalTextAlignment = None    # older Revit: text is placed by its top already
from Autodesk.Revit.DB.Electrical import Conduit
from Autodesk.Revit.DB import BuiltInCategory, FamilySymbol, CurveElement
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
PANEL_FAMILY = "NEX2-DETAIL-RISER"  # detail item drawn for the head end panel
PANEL_EXIT_FROM_TOP_FT = 10.0       # a loop with no reference line leaves the panel's right side this far
                                    # below its top
PANEL_EXIT_LOW_FT = 6.0             # extra runs below the panel leave its right side this far above its bottom
NO_ROOM_TEXT = "(Room ##)"          # Location when the panel is not in a room
STACK_GAP_FT = 10.0     # adding to an existing view: lowest point of the new circuit to the highest point
                        # of what is already in the view, in feet
NEW_VIEW = "Generate New Drafting View"
EXISTING_VIEW = "Add to Existing Drafting View"
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
    forms.alert("Select Head End Panel", sub_msg="EX: FACU, NCP, APS, etc.", title=TITLE)
    try:
        ref = uidoc.Selection.PickObject(ObjectType.Element, ElementOrTagFilter(is_conduit_source),
                                         "Select Head End Panel (or its tag) - EX: FACU, NCP, APS, etc.")
    except OperationCanceledException:
        return None
    return resolve(doc.GetElement(ref.ElementId), is_conduit_source)


def first_devices(root):
    """[the device picked (directly or by its tag) as the first in the circuit], or [] if the user pressed
    Esc to follow every run from the panel. None = cancelled."""
    choice = forms.alert("Select first Device in Circuit",
                         sub_msg="Press Esc while picking to trace every conduit run leaving the panel instead.",
                         title=TITLE, ok=True, cancel=True)
    if not choice:
        return None
    flt = ElementOrTagFilter(is_addressed_device)
    while True:
        try:
            ref = uidoc.Selection.PickObject(ObjectType.Element, flt,
                                             "Select first Device in Circuit (or its tag) - Esc = every run "
                                             "from the panel")
        except OperationCanceledException:
            return []
        el = resolve(doc.GetElement(ref.ElementId), is_addressed_device)
        if el is not None and sr.eid_int(el.Id) != sr.eid_int(root.Id):
            return [el]


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
    """Conduit type ids to follow, or None if the user cancelled."""
    in_network = net.all_conduit_types(root_id)
    if not in_network:
        return in_network
    ticked = (net.conduit_types_at(start_ids) & in_network) or in_network
    choices = sorted((ConduitTypeChoice(tid, conduit_type_name(net, tid)) for tid in in_network),
                     key=lambda c: c.name)
    items = [forms.TemplateListItem(c, checked=(c.tid in ticked), name_attr="name") for c in choices]
    picked = forms.SelectFromList.show(items, title="Which conduit type(s) should be traced? (ticked: at the first device)",
                                       button_name="Trace", multiselect=True)
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


def drafting_views():
    """{name: ViewDrafting} for every drafting view that isn't a template."""
    found = {}
    for v in FilteredElementCollector(doc).OfClass(ViewDrafting).ToElements():
        try:
            if not v.IsTemplate:
                found[v.Name] = v
        except Exception:
            pass
    return found


def choose_target_view(default_name):
    """None = generate a new view, a ViewDrafting = add to it, False = cancelled."""
    views = drafting_views()
    options = [NEW_VIEW, EXISTING_VIEW] if views else [NEW_VIEW]
    choice = forms.CommandSwitchWindow.show(options, message="Where should this circuit be drawn?")
    if not choice:
        return False
    if choice == NEW_VIEW:
        return None
    # SLC riser views first, then the rest, each alphabetical.
    names = sorted(views, key=lambda n: (0 if "SLC RISER" in n.upper() else 1, n.upper()))
    picked = forms.SelectFromList.show(names, title="Add the circuit to which drafting view?",
                                       button_name="Add to View", multiselect=False)
    if not picked:
        return False
    return views[picked]


def view_element_ids(view):
    """{id number: ElementId} of every element drawn in the view."""
    try:
        return dict((sr.eid_int(i), i) for i in FilteredElementCollector(doc, view.Id).ToElementIds())
    except Exception:
        return {}


def y_range(view, ids):
    """(lowest, highest) Y of those elements (ElementIds) in the view, or None if none of them has a size."""
    lo = hi = None
    for i in ids:
        try:
            el = doc.GetElement(i)
        except Exception:
            el = None
        if el is None:
            continue
        try:
            bb = el.get_BoundingBox(view)
        except Exception:
            bb = None
        if bb is None:
            continue
        lo = bb.Min.Y if lo is None else min(lo, bb.Min.Y)
        hi = bb.Max.Y if hi is None else max(hi, bb.Max.Y)
    return None if lo is None else (lo, hi)


def panel_family_symbol():
    """The first type of the NEX2-DETAIL-RISER detail item, or None if it isn't loaded."""
    found = []
    for sym in (FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_DetailComponents)
                .OfClass(FamilySymbol).ToElements()):
        try:
            if sym.FamilyName.strip().upper() == PANEL_FAMILY.upper():
                found.append(sym)
        except Exception:
            pass
    found.sort(key=lambda t: sr.type_name(t))
    return found[0] if found else None


def room_text(el):
    """'ROOM NAME NUMBER' of the room the element is in, or NO_ROOM_TEXT."""
    room = None
    try:
        room = el.Room
    except Exception:
        room = None
    if room is None:
        try:
            room = doc.GetRoomAtPoint(el.Location.Point)
        except Exception:
            room = None
    if room is None:
        return NO_ROOM_TEXT
    try:
        name = (room.get_Parameter(BuiltInParameter.ROOM_NAME).AsString() or "").strip()
    except Exception:
        name = ""
    number = (getattr(room, "Number", "") or "").strip()
    return " ".join(p for p in (name, number) if p) or NO_ROOM_TEXT


def set_text_param(inst, name, value):
    """Set a text parameter on the instance. False if it is missing or read-only."""
    p = inst.LookupParameter(name)
    if p is None or p.IsReadOnly:
        return False
    try:
        return bool(p.Set(value))
    except Exception:
        return False


def panel_reference_lines(sym):
    """{loop number: Y in the family} for the family's reference lines whose subcategory is a number.
    Read by opening the family, so it must run outside a transaction. {} if none can be read."""
    found = {}
    fam_doc = None
    try:
        fam_doc = doc.EditFamily(sym.Family)
        for c in FilteredElementCollector(fam_doc).OfClass(CurveElement).ToElements():
            try:
                if not c.IsReferenceLine:
                    continue
            except Exception:
                continue
            name = ""
            try:
                name = c.LineStyle.Name
            except Exception:
                pass
            if not name.strip().isdigit():
                try:
                    p = c.get_Parameter(BuiltInParameter.FAMILY_ELEM_SUBCATEGORY)
                    name = p.AsValueString() if p is not None else name
                except Exception:
                    pass
            name = (name or "").strip()
            if not name.isdigit():
                continue
            curve = c.GeometryCurve
            y = (curve.GetEndPoint(0).Y + curve.GetEndPoint(1).Y) / 2.0
            found[int(name)] = y
    except Exception as ex:
        output.print_md("Could not read the reference lines of %s: %s" % (PANEL_FAMILY, ex))
    finally:
        if fam_doc is not None:
            try:
                fam_doc.Close(False)
            except Exception:
                pass
    return found


def place_panel(view, sym, root):
    """Place the panel detail item at the origin and fill it in.
    Returns (instance, (width, 0, 0, height) from its top right corner, (dx, dy) from that corner to the
    insertion point, Y of that corner in the family's own coordinates, [parameters that couldn't be set])."""
    if not sym.IsActive:
        sym.Activate()
        doc.Regenerate()
    inst = doc.Create.NewFamilyInstance(XYZ(0, 0, 0), sym, view)
    skipped = []
    if not set_text_param(inst, PANEL_NUMBER_PARAM, named_value(root, PANEL_NUMBER_PARAM)):
        skipped.append(PANEL_NUMBER_PARAM)
    if not set_text_param(inst, "Location", room_text(root)):
        skipped.append("Location")
    doc.Regenerate()
    bb = inst.get_BoundingBox(view)
    if bb is None:
        raise Exception("Could not measure the %s detail item." % PANEL_FAMILY)
    ext = (bb.Max.X - bb.Min.X, 0.0, 0.0, bb.Max.Y - bb.Min.Y)
    return inst, ext, (-bb.Max.X, -bb.Max.Y), bb.Max.Y, skipped


def row_loop(addresses, nodes):
    """The loop number of a row when all its addresses agree on one, else None."""
    loops = set()
    for n in nodes:
        for text in addresses.get(n, []):
            parsed = sr.parse_address(text)
            if parsed:
                loops.add(parsed[1])
    return loops.pop() if len(loops) == 1 else None


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
REVIEW_XAML = """
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="SLC Riser"
        SizeToContent="WidthAndHeight"
        WindowStartupLocation="CenterScreen"
        ResizeMode="NoResize"
        Topmost="True">
    <StackPanel Margin="16" MinWidth="380">
        <TextBlock x:Name="count_text" FontSize="15" FontWeight="SemiBold" Margin="0,0,0,4"/>
        <TextBlock x:Name="detail_text" TextWrapping="Wrap" MaxWidth="400" Margin="0,0,0,12"/>
        <TextBlock Text="Adjust the device spacing and wrapping if needed:" Margin="0,0,0,8"/>
        <Grid Margin="0,0,0,8">
            <Grid.ColumnDefinitions>
                <ColumnDefinition Width="230"/>
                <ColumnDefinition Width="90"/>
            </Grid.ColumnDefinitions>
            <Grid.RowDefinitions>
                <RowDefinition Height="Auto"/>
                <RowDefinition Height="Auto"/>
                <RowDefinition Height="Auto"/>
            </Grid.RowDefinitions>
            <TextBlock Grid.Row="0" Text="Spacing between devices (ft):" VerticalAlignment="Center" Margin="0,0,0,6"/>
            <TextBox x:Name="spacing_box" Grid.Row="0" Grid.Column="1" Margin="0,0,0,6" TextChanged="changed"/>
            <TextBlock Grid.Row="1" Text="Devices before wrapping:" VerticalAlignment="Center" Margin="0,0,0,6"/>
            <TextBox x:Name="per_line_box" Grid.Row="1" Grid.Column="1" Margin="0,0,0,6" TextChanged="changed"/>
            <TextBlock Grid.Row="2" Text="Wrap rounding (devices):" VerticalAlignment="Center"/>
            <TextBox x:Name="rounding_box" Grid.Row="2" Grid.Column="1" TextChanged="changed"/>
        </Grid>
        <TextBlock x:Name="lines_text" TextWrapping="Wrap" MaxWidth="400" Foreground="DimGray" Margin="0,0,0,8"/>
        <CheckBox x:Name="save_check" Content="Save these as my defaults in SLC Riser - Config" Margin="0,0,0,8"/>
        <TextBlock x:Name="error_text" Foreground="Firebrick" TextWrapping="Wrap" MaxWidth="400" Margin="0,0,0,8"/>
        <StackPanel Orientation="Horizontal" HorizontalAlignment="Right">
            <Button Content="Create Riser" Width="100" Margin="0,0,8,0" IsDefault="True" Click="ok_click"/>
            <Button Content="Cancel" Width="80" IsCancel="True" Click="cancel_click"/>
        </StackPanel>
    </StackPanel>
</Window>
"""


def number_text(v):
    """4.5 -> '4.5', 6.0 -> '6'"""
    return ("%.4f" % v).rstrip("0").rstrip(".") if isinstance(v, float) else str(v)


class ReviewDialog(forms.WPFWindow):
    """Device count, with the spacing and wrapping settings to adjust before the riser is drawn.
    self.result = (spacing ft, devices per line, wrap rounding, save as default) or None if cancelled."""
    def __init__(self, rows):
        forms.WPFWindow.__init__(self, REVIEW_XAML, literal_string=True)
        self.rows = rows
        self.result = None
        self._ready = False
        total = sum(len(r["nodes"]) for r in rows)
        runs = [r for r in rows if r["source"] is None]
        taps = len(rows) - len(runs)
        self.count_text.Text = "%d device(s) will be added to the riser." % total
        parts = []
        for r in runs:
            parts.append("%s%d" % (("Loop %s: " % r["label"]) if r.get("label") else "", len(r["nodes"])))
        detail = "%d run(s)" % len(runs)
        if taps:
            detail += " and %d T-tap(s)" % taps
        self.detail_text.Text = detail + (" - " + ", ".join(parts) if parts else "")
        self.spacing_box.Text = number_text(DEVICE_SPACING_FT)
        self.per_line_box.Text = number_text(PER_LINE)
        self.rounding_box.Text = number_text(WRAP_ROUNDING)
        self._ready = True
        self.changed(None, None)

    def _values(self):
        """(spacing, per line, rounding) typed in the window, or an error message."""
        out = []
        for key, box, what, kind in [("device_spacing_ft", self.spacing_box, "Spacing between devices", float),
                                     ("devices_per_line", self.per_line_box, "Devices before wrapping", int),
                                     ("wrap_rounding", self.rounding_box, "Wrap rounding", int)]:
            lo, hi = sr.SETTING_LIMITS[key]
            try:
                value = kind((box.Text or "").strip())
            except Exception:
                value = None
            if value is None or not lo <= value <= hi:
                return "%s must be a %s from %s to %s." % (what, "whole number" if kind is int else "number",
                                                          number_text(lo), number_text(hi))
            out.append(value)
        return tuple(out)

    def changed(self, sender, args):
        if not self._ready:
            return
        values = self._values()
        if isinstance(values, str):
            self.error_text.Text = values
            self.lines_text.Text = ""
            return
        self.error_text.Text = ""
        _, per, rounding = values
        lines = sum(len(rl.split_lines(r["nodes"], per, rounding)) for r in self.rows)
        self.lines_text.Text = "With these settings the riser has %d line(s) of devices." % lines

    def ok_click(self, sender, args):
        values = self._values()
        if isinstance(values, str):
            self.error_text.Text = values
            return
        self.result = values + (bool(self.save_check.IsChecked),)
        self.Close()

    def cancel_click(self, sender, args):
        self.Close()


def review_layout(rows):
    """Show the device count and let the user adjust spacing and wrapping. False if cancelled."""
    global DEVICE_SPACING_FT, PER_LINE, WRAP_ROUNDING
    dlg = ReviewDialog(rows)
    dlg.ShowDialog()
    if dlg.result is None:
        return False
    DEVICE_SPACING_FT, PER_LINE, WRAP_ROUNDING, save = dlg.result
    if save:
        try:
            settings = sr.load_settings()
        except Exception:
            settings = dict(sr.DEFAULT_SETTINGS)
        settings.update({"device_spacing_ft": DEVICE_SPACING_FT, "devices_per_line": PER_LINE,
                         "wrap_rounding": WRAP_ROUNDING})
        try:
            sr.save_settings(settings)
        except Exception as ex:
            forms.alert("These settings are used for this riser but could not be saved:\n%s\n\nPath: %s"
                        % (ex, sr.settings_path()), title=TITLE)
    return True


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
    if firsts is None:
        return
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

    # Symbol for each thing drawn. The panel is the NEX2-DETAIL-RISER detail item when it is loaded.
    panel_sym = panel_family_symbol()
    if panel_sym is None:
        go_on = forms.alert("The %s detail item is not loaded in this project, so the head end panel will be "
                            "drawn with the symbol set for it in SLC Riser - Config instead.\n\nContinue?"
                            % PANEL_FAMILY, title=TITLE, yes=True, no=True)
        if not go_on:
            return
    panel_refs = panel_reference_lines(panel_sym) if panel_sym is not None else {}
    drawn = [root_id] + [n for row in rows for n in row["nodes"]]
    keys = dict((n, sr.family_key(doc, elements[n])) for n in drawn)
    chosen, missing = {}, []    # type key -> symbol key; type keys with no usable symbol
    for n in drawn:
        if n == root_id and panel_sym is not None:
            continue
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

    if not review_layout(rows):
        return
    target = choose_target_view(view_name(root))
    if target is False:
        return

    global VIEW_SCALE
    t = Transaction(doc, "Create SLC riser" if target is None else "Add circuit to SLC riser")
    t.Start()
    try:
        before = {}
        if target is None:
            view = new_drafting_view(view_name(root))
        else:
            view = target
            VIEW_SCALE = view.Scale     # sizes on the sheet follow the view being added to
            before = view_element_ids(view)
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
        panel_inst = panel_ext = panel_shift = None
        panel_skipped, unmatched_loops = [], set()
        if panel_sym is not None:
            panel_inst, panel_ext, panel_shift, panel_top_y, panel_skipped = place_panel(view, panel_sym, root)
            for row in rows:
                row.pop("panel_dy", None)
                if row["source"] is not None:
                    continue
                loop = row_loop(addresses, row["nodes"])
                if loop is not None and loop in panel_refs:
                    row["panel_dy"] = panel_refs[loop] - panel_top_y
                elif loop is not None:
                    unmatched_loops.add(loop)

        box = paper(BOX_SIZE) / 2.0
        info = {}
        for n in drawn:
            lines = list(addresses.get(n, []))
            if len(lines) > 1:
                lines = [lines[0] + "-", lines[-1]]     # several addresses: first- / last, on two lines
            if n == root_id:
                lines = [] if panel_inst is not None else [element_name(root)]
            if n == root_id and panel_inst is not None:
                ext = panel_ext
            elif n in node_symbol:
                ext = sizes[sr.eid_int(node_symbol[n].Id)]
            elif n == root_id:
                w, h = paper(PANEL_BOX[0]) / 2.0, paper(PANEL_BOX[1]) / 2.0
                ext = (w, w, h, h)
            else:
                ext = (box, box, box, box)
                lines.insert(0, keys[n].split(" : ")[-1])
            above = named_value(elements[n], PANEL_NUMBER_PARAM) if n != root_id else ""
            info[n] = {"mapped": n in node_symbol, "ext": ext, "lines": lines, "above": above}
        if panel_inst is not None:
            info[root_id]["panel"] = True
            info[root_id]["exit_low"] = PANEL_EXIT_LOW_FT
            info[root_id]["exit_dy"] = min(PANEL_EXIT_FROM_TOP_FT, panel_ext[3] * 0.5)

        char_w = line_h / LINE_SPACING * 0.7    # a character is taken as about 0.7 of the text size wide
        cfg = {"spacing": DEVICE_SPACING_FT, "per_line": PER_LINE, "wrap_rounding": WRAP_ROUNDING, "char_w": char_w,
               "label_offset": LABEL_OFFSET_IN / 12.0, "above_h": above_h,
               "pad": paper(PAD), "text_gap": paper(TEXT_GAP), "line_h": line_h, "row_gap": paper(ROW_GAP)}
        plan = rl.layout(rows, root_id, info, returns, cfg)
        failed = draw(view, plan, node_symbol, type_id, line_h, above_type_id)
        if panel_inst is not None:
            if plan["panel"] is None:
                doc.Delete(panel_inst.Id)
            else:
                px, py = plan["panel"]
                ElementTransformUtils.MoveElement(doc, panel_inst.Id,
                                                  XYZ(px + panel_shift[0], py + panel_shift[1], 0))
        if target is not None:
            # Move the new circuit so its lowest point is STACK_GAP_FT above the highest point already there.
            doc.Regenerate()
            existing = y_range(view, before.values())
            now = view_element_ids(view)
            new_ids = [eid for k, eid in now.items() if k not in before]
            added = y_range(view, new_ids)
            if existing is not None and added is not None and new_ids:
                dy = existing[1] + STACK_GAP_FT - added[0]
                ids = List[ElementId](new_ids)
                ElementTransformUtils.MoveElements(doc, ids, XYZ(0, dy, 0))
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
    msg = "%s '%s': %d device(s) on %d run(s)" % ("Created" if target is None else "Added to",
                                                   view.Name, count, runs)
    if taps:
        msg += " and %d T-tap(s)" % taps
    msg += "."
    if failed:
        msg += "\n\n%d item(s) could not be drawn." % failed
    if unmatched_loops:
        msg += ("\n\n%s has no reference line for loop %s, so it was drawn %g' below the top of the panel."
                % (PANEL_FAMILY, ", ".join(str(n) for n in sorted(unmatched_loops)), PANEL_EXIT_FROM_TOP_FT))
    if panel_skipped:
        msg += ("\n\nThe %s detail item has no editable parameter named %s, so it was left as is."
                % (PANEL_FAMILY, " / ".join(panel_skipped)))
    if unaddressed:
        msg += ("\n\n%d Fire Alarm Device(s) on the conduit have no SLC address and were left off. "
                "They are listed in the output window." % len(unaddressed))
        output.print_md("### %s - devices on the conduit without an SLC address" % TITLE)
        for el in unaddressed:
            output.print_md("- %s %s" % (output.linkify(el.Id), sr.family_key(doc, el)))
    forms.alert(msg, title=TITLE)


main()
