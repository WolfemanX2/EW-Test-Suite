# -*- coding: utf-8 -*-
# SLC Riser script - version v28
__title__ = "SLC\nRiser v28"
__doc__ = ("Draws a one-line SLC riser diagram in a new drafting view named "
           "<LEVEL> - SLC RISER - <PANEL #> (the panel's level and its Panel # parameter, in capitals).\n\n"
           "Steps: select the head end panel (FACU, NCP, APS ...), then the first device in the circuit "
           "(either can be picked by its tag), choose the conduit types to trace, then check the device "
           "count and adjust spacing / wrapping, then choose to generate a new drafting view (with the panel detail) or add the circuit to "
           "an existing one (joined to the panel detail already there; no new panel is placed) before the riser is drawn. "
           "Each loop's one-line is made into a detail group named <PANEL #> - Loop <letter>. The circuit is followed along "
           "its conduit starting at the first device, away from the panel, so that device decides the "
           "order. Press Esc instead of picking a first device to follow every conduit run leaving the "
           "panel. The tool draws every Fire Alarm Device that has an SLC address (SLC Address, SLC Address 2 ... 24) "
           "in order of connection, one row per conduit run leaving the panel, with its full address "
           "(N#L#M# / N#L#D#) underneath; a device with several addresses shows the first and last on two "
           "lines (first- / last). The address text is at 45 degrees, right justified, hanging below "
           "the riser line, its top corner 1\" under its device; devices are 6' apart, and the riser line runs unbroken through the devices. Each row is labeled with its loop as a letter (L1 = A, L2 = B ...), read from those addresses. "
           "The head end panel is drawn with the NEX2-DETAIL-RISER detail item (Panel # and Location - the "
           "room name and number - filled in from the panel); every run comes out of its right side, the first "
           "device one device spacing away from the right end of its reference line. The height of loop N is "
           "read from the placed panel's Loop Spacing N parameter (distance up from the bottom of the panel). "
           "Each loop leaves the panel in line with the family's reference line "
           "(reference line or reference plane) named for that loop number - 3, L3, Loop 3 or Ref Line 3 in its subcategory, "
           "line style or name (N1L3 -> 3). With no match you choose one of the family's reference lines or "
           "pick a start point. The first line of the one-line is locked in alignment with its reference line. "
           "When a row wraps, the next line runs the opposite way (left to right, then right to left, and so "
           "on), with the devices following it. Where the conduit splits, the shorter side is drawn as its own T-tap row.\n\n"
           "Only conduit of the types you choose is followed (the types connected to the first devices are "
           "ticked to start with), so a tee onto conduit of another type (NAC, power) is not a T-tap.\n\n"
           "A type can use a Generic Annotation as its address label instead of the 45 degree text (set in "
           "SLC Riser - Config); the tag is placed under the device and filled in with the device's parameters "
           "(shared parameters by GUID, others by name). "
           "Each Family : Type is drawn with the symbol set for it in SLC Riser - Config. A type without "
           "one is asked about when the tool runs, and the choice is saved to the table. "
           "A device whose Panel # parameter has a value shows it above its symbol (5/64\" text).\n\n"
           "View scale, device spacing, devices per line, wrap rounding and the label offset are set in SLC Riser - Config.\n\n"
           "Devices on the conduit without an SLC address are passed through and listed afterwards.")

from Autodesk.Revit.DB import (
    XYZ, Line, Transaction, FilteredElementCollector, FamilyInstance, ViewDrafting, ViewFamilyType,
    ViewFamily, TextNote, StorageType, TextNoteType, TextNoteOptions, HorizontalTextAlignment, ElementTypeGroup,
    ElementId, BuiltInParameter, IndependentTag, ElementTransformUtils, GroupType, SketchPlane, Plane,
    ReferencePlane, Options, GeometryInstance, SubTransaction, FamilyInstanceReferenceType, Reference
)
from System.Collections.Generic import List
try:
    from Autodesk.Revit.DB import VerticalTextAlignment
except ImportError:
    VerticalTextAlignment = None    # older Revit: text is placed by its top already
from Autodesk.Revit.DB.Electrical import Conduit
from Autodesk.Revit.DB import BuiltInCategory, FamilySymbol, CurveElement
from Autodesk.Revit.UI.Selection import ObjectType, ISelectionFilter, ObjectSnapTypes
from Autodesk.Revit.Exceptions import OperationCanceledException
from pyrevit import revit, forms, script

import math
import re

import clr
import System

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
LOOP_LABEL_RAISE_IN = 5.0   # loop letter (A, B ...) sits this many inches (in the view) higher, with a
                            # detail line from under its centre down to the riser line
ABOVE_TEXT_SIZE_IN = 5.0 / 64.0     # text above a device (its Panel #): size on the sheet, in inches
ABOVE_TEXT_TYPE_NAME = 'SLC Riser 5/64"'    # made from the default text type if no 5/64" type exists
# Sizes on the printed sheet, in inches:
ROW_GAP = 0.5           # extra space between rows
PAD = 0.125             # space above and below each line of devices
TEXT_GAP = 0.06         # between a symbol and the addresses under it
BOX_SIZE = 0.375        # box drawn for a type that has no symbol
MAX_SYMBOL = 2.0        # a symbol measured larger than this is treated as this size
LINE_SPACING = 1.6      # text line height as a multiple of the text size
PANEL_NUMBER_PARAM = "Panel #"      # the panel's name on the diagram and in the view name
PANEL_FAMILY = "NEX2-DETAIL-RISER"  # detail item drawn for the head end panel
PANEL_EXIT_FROM_TOP_FT = 10.0       # a loop with no reference line leaves the panel's right side this far
                                    # below its top
PANEL_EXIT_LOW_FT = 6.0             # extra runs below the panel leave its right side this far above its bottom
NO_ROOM_TEXT = "(Room ##)"          # Location when the panel is not in a room
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


LOOP_SPACING = re.compile(r"^\s*Loop\s*Spacing\s*0*(\d+)\s*$", re.IGNORECASE)
PANEL_FAMILY_INFO = {"spacing": {}, "bottom": None, "x": None}   # filled by panel_reference_lines()
LOOP_LABEL = re.compile(r"^(?:N\s*\d+\s*)?(?:LOOP|L)?\s*[-_.#]?\s*0*(\d+)$", re.IGNORECASE)


LOOP_LABEL_END = re.compile(r"(?:LOOP|REF[A-Z]*(?:\s*LINE)?)\s*[-_.#]?\s*0*(\d+)$", re.IGNORECASE)


def label_loop(text):
    """3 for '3', 'L3', 'Loop 3', 'LOOP-03', 'N1L3', 'Ref Line 3', 'SLC Loop 3'; None otherwise."""
    text = (text or "").strip()
    m = LOOP_LABEL.match(text) or LOOP_LABEL_END.search(text)
    return int(m.group(1)) if m else None


def _labels(fam_doc, el):
    """Every name the element goes by: its name, subcategory and line style."""
    out = []

    def add(text):
        text = (text or "").strip()
        if text and text not in out:
            out.append(text)
    try:
        add(el.Name)
    except Exception:
        pass
    try:
        add(el.LineStyle.Name)
    except Exception:
        pass
    for bip in (BuiltInParameter.FAMILY_ELEM_SUBCATEGORY, BuiltInParameter.DATUM_TEXT):
        try:
            p = el.get_Parameter(bip)
            if p is None:
                continue
            add(p.AsValueString())
            add(p.AsString())
            sub = fam_doc.GetElement(p.AsElementId())
            if sub is not None:
                add(sub.Name)
        except Exception:
            pass
    for pname in ("Subcategory", "Name"):
        try:
            p = el.LookupParameter(pname)
            if p is not None:
                add(p.AsValueString())
                add(p.AsString())
        except Exception:
            pass
    return out


def is_reference_text(el):
    """The element's Is Reference setting as Revit shows it ('Weak Reference', 'Not a Reference' ...), or ''."""
    try:
        p = el.get_Parameter(BuiltInParameter.ELEM_REFERENCE_NAME)
        return (p.AsValueString() or "").strip() if p is not None else ""
    except Exception:
        return ""


def panel_reference_lines(sym):
    """The horizontal reference lines and reference planes in the panel family, each
    {"kind", "labels", "y" (in the family), "x" (its right end, in the family), "loop" (number its
    labels name, or None), "name"}.
    Read by opening the family, so it must run outside a transaction. [] if none can be read."""
    found = []
    fam_doc = None
    PANEL_FAMILY_INFO.update({"spacing": {}, "bottom": None, "x": None})
    try:
        fam_doc = doc.EditFamily(sym.Family)
        try:
            fm = fam_doc.FamilyManager
            for fp in fm.Parameters:
                m = LOOP_SPACING.match(fp.Definition.Name)
                if m and fm.CurrentType is not None:
                    value = fm.CurrentType.AsDouble(fp)
                    if value is not None:
                        PANEL_FAMILY_INFO["spacing"][int(m.group(1))] = value
        except Exception:
            pass
        for c in FilteredElementCollector(fam_doc).OfClass(CurveElement).ToElements():
            try:
                is_ref = bool(c.IsReferenceLine)
            except Exception:
                is_ref = False
            labels = _labels(fam_doc, c)
            loop = None
            for text in labels:
                loop = label_loop(text)
                if loop is not None:
                    break
            if not is_ref and loop is None:
                continue        # an ordinary line of the panel drawing
            try:
                curve = c.GeometryCurve
                p0, p1 = curve.GetEndPoint(0), curve.GetEndPoint(1)
            except Exception:
                continue
            if abs(p0.Y - p1.Y) > 1e-6:
                continue        # not horizontal
            found.append({"kind": "Reference Line" if is_ref else "Line", "labels": labels,
                          "y": (p0.Y + p1.Y) / 2.0, "x": max(p0.X, p1.X), "loop": loop, "name": None,
                          "is_ref": is_reference_text(c)})
        for rp in FilteredElementCollector(fam_doc).OfClass(ReferencePlane).ToElements():
            try:
                p0, p1 = rp.BubbleEnd, rp.FreeEnd
            except Exception:
                continue
            if abs(p0.Y - p1.Y) > 1e-6:
                continue
            labels = _labels(fam_doc, rp)
            loop = None
            for text in labels:
                loop = label_loop(text)
                if loop is not None:
                    break
            found.append({"kind": "Reference Plane", "labels": labels, "y": (p0.Y + p1.Y) / 2.0,
                          "x": max(p0.X, p1.X), "is_ref": is_reference_text(rp),
                          "loop": loop, "name": (rp.Name or "").strip() or None})
    except Exception as ex:
        output.print_md("Could not read the reference lines of %s: %s" % (PANEL_FAMILY, ex))
    finally:
        if fam_doc is not None:
            try:
                fam_doc.Close(False)
            except Exception:
                pass
    # Reference lines first, then reference planes, then plain lines with a loop name; top to bottom.
    order = {"Reference Line": 0, "Reference Plane": 1, "Line": 2}
    found.sort(key=lambda c: (order.get(c["kind"], 3), -c["y"]))
    # The bottom of the panel in the family: a loop's line height less its Loop Spacing.
    spacing = PANEL_FAMILY_INFO["spacing"]
    bottoms = sorted(c["y"] - spacing[c["loop"]] for c in found
                     if c["loop"] is not None and c["loop"] in spacing and c["kind"] != "Line")
    PANEL_FAMILY_INFO["bottom"] = bottoms[len(bottoms) // 2] if bottoms else None
    xs = [c["x"] for c in found if c["loop"] is not None and c["kind"] != "Line"]
    PANEL_FAMILY_INFO["x"] = max(set(xs), key=xs.count) if xs else None
    return found


def report_reference_lines(placed, top):
    """List what was found in the family, in the output window. placed: [(candidate, y in the view)]."""
    output.print_md("### %s - reference lines found in the family" % PANEL_FAMILY)
    if not placed:
        output.print_md("- none (no horizontal reference lines or reference planes)")
    for c, y in placed:
        output.print_md("- %s at %s below the top - names: %s - loop: %s - Is Reference: %s"
                        % (c["kind"], feet_text(top - y), ", ".join(c["labels"]) or "(none)",
                           c["loop"] if c["loop"] is not None else "not recognised", c.get("is_ref") or "?"))


def feet_text(ft):
    """12.5 -> 12'-6\""""
    inches = int(round(abs(ft) * 12))
    return "%d'-%d\"" % (inches // 12, inches % 12)


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


def split_runs(rows):
    """Rows grouped per run: each run row with the T-tap rows that follow it."""
    runs = []
    for row in rows:
        if row["source"] is None or not runs:
            runs.append([])
        runs[-1].append(row)
    return runs


def run_name(panel_name, run, index):
    """'FACU-01 - Loop A' (or '... - Run 2' when the loop can't be read from the addresses)."""
    label = run[0].get("label")
    return "%s - %s" % (panel_name, ("Loop %s" % label) if label else ("Run %d" % index))


def unique_group_name(name):
    taken = set()
    for gt in FilteredElementCollector(doc).OfClass(GroupType).ToElements():
        try:
            taken.add(gt.Name)
        except Exception:
            pass
    candidate, n = name, 1
    while candidate in taken:
        n += 1
        candidate = "%s (%d)" % (name, n)
    return candidate


def panels_in_view(view):
    """NEX2-DETAIL-RISER instances drawn in the view."""
    found = []
    for el in FilteredElementCollector(doc, view.Id).OfClass(FamilyInstance).ToElements():
        try:
            if el.Symbol.FamilyName.strip().upper() == PANEL_FAMILY.upper():
                found.append(el)
        except Exception:
            pass
    return found


def find_view_panel(view, root):
    """The panel detail already in the view for this panel (its Panel # matches), the only one there, or
    one the user chooses. None if there is none (or the user chose not to use one)."""
    panels = panels_in_view(view)
    if not panels:
        return None
    number = named_value(root, PANEL_NUMBER_PARAM).strip().upper()
    matching = [p for p in panels if number and named_value(p, PANEL_NUMBER_PARAM).strip().upper() == number]
    if len(matching) == 1:
        return matching[0]
    if len(panels) == 1 and not matching:
        return panels[0]
    pool = matching or panels
    names = {}
    for p in pool:
        label = "%s  (id %d)" % (named_value(p, PANEL_NUMBER_PARAM) or "no Panel #", sr.eid_int(p.Id))
        names[label] = p
    picked = forms.SelectFromList.show(sorted(names), title="Join the circuit to which panel detail?",
                                       button_name="Use Panel", multiselect=False)
    return names.get(picked) if picked else None


def loop_spacing_values(panel):
    """{loop number: Loop Spacing N} of the placed panel (instance parameters first, then its type)."""
    found = {}
    holders = [panel]
    try:
        holders.append(panel.Symbol)
    except Exception:
        pass
    for holder in holders:
        try:
            params = list(holder.Parameters)
        except Exception:
            continue
        for p in params:
            try:
                m = LOOP_SPACING.match(p.Definition.Name)
                if m and p.HasValue and int(m.group(1)) not in found:
                    found[int(m.group(1))] = p.AsDouble()
            except Exception:
                pass
    return found


def panel_exit_points(view, panel, cands):
    """(x of the panel's right side, top of the panel, [(candidate, y in the view)]), or (None, None, []).
    A loop's height comes from the placed panel's Loop Spacing N (up from the bottom of the panel); its
    reference line's height in the family is the fallback. Each candidate also gets "vx" (x of its right
    end in the view, where its one-line starts) and "y_eff" (its height in the family as placed).
    Loops with a Loop Spacing but no reference line found get a candidate of their own."""
    if panel is None:
        return None, None, []
    bb = panel.get_BoundingBox(view)
    if bb is None:
        return None, None, []
    tf = panel.GetTransform()
    spacing = loop_spacing_values(panel)
    bottom = PANEL_FAMILY_INFO.get("bottom")
    common_x = PANEL_FAMILY_INFO.get("x")
    cands = list(cands)
    have = set(c["loop"] for c in cands if c["loop"] is not None and c["kind"] != "Line")
    for loop in sorted(spacing):
        if loop not in have:
            cands.append({"kind": "Loop Spacing", "labels": ["Loop Spacing %d" % loop], "y": None,
                          "x": common_x, "loop": loop, "name": None, "is_ref": ""})
    out = []
    for c in cands:
        try:
            y_fam = c["y"]
            if c["loop"] in spacing and bottom is not None:
                y_fam = bottom + spacing[c["loop"]]
            if y_fam is None:
                # No reference line to measure from: up from the bottom of the panel as drawn.
                c["y_eff"] = None
                c["vx"] = bb.Max.X
                out.append((c, bb.Min.Y + spacing[c["loop"]]))
                continue
            c["y_eff"] = y_fam
            p = tf.OfPoint(XYZ(c["x"] if c["x"] is not None else 0.0, y_fam, 0))
            c["vx"] = p.X if c["x"] is not None else bb.Max.X
            out.append((c, p.Y))
        except Exception:
            pass
    return bb.Max.X, bb.Max.Y, out


def choose_reference(name, reason, placed, top):
    """A reference line chosen by the user for a loop: (candidate, y), "pick" to pick a point, or None."""
    PICK = "Pick a start point in the view instead"
    options, by_label = [], {}
    for c, y in placed:
        if c["kind"] == "Line":
            continue
        label = "%s - %s below the top  (%s)" % (", ".join(c["labels"][:3]) or "unnamed", feet_text(top - y),
                                                c["kind"])
        while label in by_label:
            label += " "
        by_label[label] = (c, y)
        options.append(label)
    if not options:
        return "pick"
    picked = forms.SelectFromList.show(options + [PICK],
                                       title="%s - %s Which reference line should it start from?" % (name, reason),
                                       button_name="Use", multiselect=False)
    if not picked:
        return None
    return "pick" if picked == PICK else by_label[picked]


def references_in_instance(panel, view, cand, y):
    """Every Reference the placed panel offers that could be the candidate's line or plane, best first.
    Locking only succeeds with one that is really in line with the riser, so trying them in turn is safe."""
    refs, seen = [], set()

    def add(r):
        if r is None:
            return
        try:
            key = r.ConvertToStableRepresentation(doc)
        except Exception:
            key = None
        if key is not None and key in seen:
            return
        seen.add(key)
        refs.append(r)

    # 1. By name (named reference planes / lines).
    names = ([cand["name"]] if cand.get("name") else []) + list(cand.get("labels", []))
    for n in names:
        try:
            add(panel.GetReferenceByName(n))
        except Exception:
            pass
    # 2. The panel's own references (reference lines and planes with Is Reference set).
    for rtype in System.Enum.GetValues(clr.GetClrType(FamilyInstanceReferenceType)):
        try:
            for r in panel.GetReferences(rtype):
                add(r)
        except Exception:
            pass
    # 3. The line in the family's geometry, turned into a reference to it in this panel.
    opts = Options()
    opts.ComputeReferences = True
    opts.IncludeNonVisibleObjects = True
    opts.View = view
    try:
        geom = list(panel.get_Geometry(opts))
    except Exception:
        geom = []
    for g in geom:
        if not isinstance(g, GeometryInstance):
            continue
        fam_y = cand.get("y_eff", cand["y"])
        for getter, want_y in ((g.GetSymbolGeometry, fam_y), (g.GetInstanceGeometry, y)):
            try:
                items = list(getter())
            except Exception:
                continue
            for item in items:
                try:
                    p0, p1 = item.GetEndPoint(0), item.GetEndPoint(1)
                except Exception:
                    continue
                if want_y is None or abs(p0.Y - p1.Y) > 1e-6 or abs((p0.Y + p1.Y) / 2.0 - want_y) > 1e-4 \
                        or item.Reference is None:
                    continue
                try:
                    stable = item.Reference.ConvertToStableRepresentation(doc)
                except Exception:
                    stable = None
                if stable:
                    for text in ("%s:0:INSTANCE:%s" % (panel.UniqueId, stable), stable):
                        try:
                            add(Reference.ParseFromStableRepresentation(doc, text))
                        except Exception:
                            pass
                add(item.Reference)
    return refs


def lock_to_reference(view, refs, curve):
    """Lock the detail curve in alignment with the first of the references Revit accepts.
    Returns '' or the reason it couldn't."""
    if not refs:
        return ("the reference line could not be found in the placed panel "
                "(set its Is Reference to anything but Not a Reference)")
    line_ref = curve.GeometryCurve.Reference
    errors = []
    for ref in refs:
        st = SubTransaction(doc)
        st.Start()
        try:
            doc.Create.NewAlignment(view, ref, line_ref)
            st.Commit()
            return ""
        except Exception as ex:
            st.RollBack()
            text = " ".join(str(ex).split())
            if text not in errors:
                errors.append(text)
    return "tried %d reference(s): %s" % (len(refs), " | ".join(errors[:3]))


def ensure_sketch_plane(view):
    """PickPoint needs a work plane. Drafting views have their own and refuse a new one, so this only
    sets one on other views, and never stops the tool if it can't."""
    if isinstance(view, ViewDrafting):
        return
    try:
        if view.SketchPlane is not None:
            return
        plane = Plane.CreateByNormalAndOrigin(view.ViewDirection, view.Origin)
        view.SketchPlane = SketchPlane.Create(doc, plane)
    except Exception:
        pass


def pick_origin(view, name, reason):
    """Point picked by the user where a loop's one-line starts, or None if cancelled."""
    try:
        if uidoc.ActiveView.Id != view.Id:
            uidoc.ActiveView = view
    except Exception:
        pass
    forms.alert("Select where the one-line diagram for %s should start." % name, sub_msg=reason, title=TITLE)
    try:
        p = uidoc.Selection.PickPoint(ObjectSnapTypes.Endpoints | ObjectSnapTypes.Nearest |
                                      ObjectSnapTypes.Intersections,
                                      "Pick the start of the one-line for %s" % name)
    except OperationCanceledException:
        return None
    except Exception as ex:
        forms.alert("Could not pick a point in '%s':\n%s" % (view.Name, ex), title=TITLE)
        return None
    return (p.X, p.Y)


def shift_plan(plan, dx, dy):
    """The plan moved by (dx, dy)."""
    out = {"symbols": [(x + dx, y + dy, n) for x, y, n in plan["symbols"]],
           "boxes": [(x + dx, y + dy, l, r, u, d) for x, y, l, r, u, d in plan["boxes"]],
           "lines": [((p[0] + dx, p[1] + dy), (q[0] + dx, q[1] + dy)) for p, q in plan["lines"]],
           "texts": [(x + dx, y + dy, t, how) for x, y, t, how in plan["texts"]],
           "tags": [(x + dx, y + dy, n) for x, y, n in plan.get("tags", [])],
           "leader_texts": [(x + dx, y + dy, t, ex + dx, ey + dy)
                            for x, y, t, ex, ey in plan.get("leader_texts", [])]}
    return out


def measure_tags(view, symbols):
    """{symbol id: (left, right, up, down)} of address label tags from their insertion point (not capped)."""
    placed = {}
    for key, sym in symbols.items():
        try:
            placed[key] = doc.Create.NewFamilyInstance(XYZ(0, 0, 0), sym, view)
        except Exception:
            pass
    if placed:
        doc.Regenerate()
    sizes = {}
    for key in symbols:
        ext = (0.0, 0.0, 0.0, paper(0.5))
        inst = placed.get(key)
        if inst is not None:
            try:
                bb = inst.get_BoundingBox(view)
                if bb is not None:
                    ext = (max(-bb.Min.X, 0.0), max(bb.Max.X, 0.0), max(bb.Max.Y, 0.0), max(-bb.Min.Y, 0.0))
            except Exception:
                pass
            doc.Delete(inst.Id)
        sizes[key] = ext
    return sizes


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


def draw(view, plan, node_symbol, type_id, line_h, above_type_id=None, created=None, tag_symbol=None,
         elements=None):
    """Create everything in the layout. Returns the number of things that could not be created.
    created: a list that gets (start, end, detail curve) for every line drawn."""
    failed = [0]
    min_len = doc.Application.ShortCurveTolerance

    def line(p, q):
        if abs(p[0] - q[0]) + abs(p[1] - q[1]) <= min_len:
            return
        try:
            curve = doc.Create.NewDetailCurve(view, Line.CreateBound(XYZ(p[0], p[1], 0), XYZ(q[0], q[1], 0)))
            if created is not None:
                created.append((p, q, curve))
        except Exception:
            failed[0] += 1

    for x, y, n in plan["symbols"]:
        try:
            doc.Create.NewFamilyInstance(XYZ(x, y, 0), node_symbol[n], view)
        except Exception:
            failed[0] += 1
    for x, y, n in plan.get("tags", []):
        # A Generic Annotation address label, filled in with the device's parameters.
        try:
            tag = doc.Create.NewFamilyInstance(XYZ(x, y, 0), tag_symbol[n], view)
        except Exception:
            failed[0] += 1
            continue
        if elements is not None:
            sr.copy_parameters(elements[n], tag)
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
    for x, y, text, ex, ey in plan.get("leader_texts", []):
        # The loop letter, centred over the riser, with a detail line from under it down to the riser line.
        try:
            opts = TextNoteOptions(type_id)
            opts.HorizontalAlignment = HorizontalTextAlignment.Center
            note = TextNote.Create(doc, view.Id, XYZ(x, y, 0), text, opts)
        except Exception:
            failed[0] += 1
            continue
        bottom = y - line_h / LINE_SPACING * 1.2     # about the letter's height, if it can't be measured
        try:
            doc.Regenerate()
            bb = note.get_BoundingBox(view)
            if bb is not None:
                bottom = bb.Min.Y
        except Exception:
            pass
        if bottom > ey:
            line((x, bottom), (ex, ey))
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
    try:
        labels = sr.load_labels()
    except Exception:
        labels = {}
    available_tags = sr.available_tags(doc)

    # The panel is the NEX2-DETAIL-RISER detail item; the devices use the symbols from the table.
    panel_sym = panel_family_symbol()
    panel_refs = panel_reference_lines(panel_sym) if panel_sym is not None else []
    drawn = [n for row in rows for n in row["nodes"]]
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

    # Address labels: a Generic Annotation where the table sets one, the 45 degree text otherwise.
    tag_symbol, missing_tags = {}, set()
    for n in drawn:
        wanted = labels.get(keys[n])
        if not wanted:
            continue
        if wanted in available_tags:
            tag_symbol[n] = available_tags[wanted]
        else:
            missing_tags.add(wanted)
    if missing_tags:
        go_on = forms.alert("These address label Generic Annotations are set in SLC Riser - Config but are not "
                            "loaded in this project:\n\n%s\n\nThose devices will use the standard 45 degree "
                            "text. Continue?" % "\n".join(sorted(missing_tags)), title=TITLE, yes=True, no=True)
        if not go_on:
            return

    if not review_layout(rows):
        return
    target = choose_target_view(view_name(root))
    if target is False:
        return
    if target is None and panel_sym is None:
        go_on = forms.alert("The %s detail item is not loaded in this project, so no panel will be drawn and "
                            "you will pick where each loop's one-line starts.\n\nContinue?" % PANEL_FAMILY,
                            title=TITLE, yes=True, no=True)
        if not go_on:
            return

    global VIEW_SCALE
    panel_name = (named_value(root, PANEL_NUMBER_PARAM) or element_name(root)).strip()
    runs = split_runs(rows)

    # 1. The view, and the panel detail (a new one in a new view; the one already there otherwise).
    created_view = False
    panel_skipped = []
    t = Transaction(doc, "SLC riser - view and panel")
    t.Start()
    try:
        if target is None:
            view = new_drafting_view(view_name(root))
            created_view = True
            panel_inst = None
            if panel_sym is not None:
                panel_inst, _, shift, _, panel_skipped = place_panel(view, panel_sym, root)
                # Top right corner at the origin, as before.
                ElementTransformUtils.MoveElement(doc, panel_inst.Id, XYZ(shift[0], shift[1], 0))
        else:
            view = target
            VIEW_SCALE = view.Scale     # sizes on the sheet follow the view being added to
            panel_inst = None
        ensure_sketch_plane(view)
        t.Commit()
    except Exception as ex:
        if t.HasStarted() and not t.HasEnded():
            t.RollBack()
        forms.alert("The riser could not be created:\n%s" % ex, title=TITLE)
        return

    def undo_view():
        if created_view:
            t2 = Transaction(doc, "SLC riser - cancelled")
            t2.Start()
            try:
                doc.Delete(view.Id)
                t2.Commit()
            except Exception:
                t2.RollBack()

    if target is not None:
        panel_inst = find_view_panel(view, root)
    exit_x, panel_top, placed_refs = panel_exit_points(view, panel_inst, panel_refs)

    # 2. Where each loop's one-line starts, and the reference line it is locked to.
    origins, lock_refs, reported = [], [], False
    for i, run in enumerate(runs, start=1):
        name = run_name(panel_name, run, i)
        loop = row_loop(addresses, run[0]["nodes"])
        match = None
        if exit_x is not None and loop is not None:
            for c, y in placed_refs:
                if c["loop"] == loop:
                    match = (c, y)
                    break
        if match is None and panel_inst is not None:
            if not reported:
                report_reference_lines(placed_refs, panel_top)
                reported = True
            reason = ("Its loop number could not be read from the device addresses." if loop is None else
                      "No reference line named %d (or L%d / Loop %d) was found in %s." % (loop, loop, loop,
                                                                                          PANEL_FAMILY))
            match = choose_reference(name, reason, placed_refs, panel_top)
            if match is None:
                undo_view()
                return
            if match == "pick":
                match = None
                point = pick_origin(view, name, reason)
                if point is None:
                    undo_view()
                    return
                origins.append(point)
                lock_refs.append(None)
                continue
        if match is not None:
            origins.append((match[0].get("vx", exit_x), match[1]))   # the right end of the reference line
            lock_refs.append(match)
            continue
        point = pick_origin(view, name, "There is no %s panel detail to join it to." % PANEL_FAMILY)
        if point is None:
            undo_view()
            return
        origins.append(point)
        lock_refs.append(None)

    # 3. Draw each loop and group it.
    failed = 0
    groups, not_locked = [], []
    t = Transaction(doc, "Create SLC riser" if target is None else "Add circuit to SLC riser")
    t.Start()
    try:
        type_id, line_h = text_type()
        above_type_id, above_h = None, line_h
        if any(named_value(elements[n], PANEL_NUMBER_PARAM) for n in drawn):
            above_type_id, above_h = small_text_type(type_id)
        used = {}
        for sym in node_symbol.values():
            used[sr.eid_int(sym.Id)] = sym
        for sym in used.values():
            if not sym.IsActive:
                sym.Activate()
        doc.Regenerate()
        sizes = measure_symbols(view, used)
        used_tags = {}
        for sym in tag_symbol.values():
            used_tags[sr.eid_int(sym.Id)] = sym
        for sym in used_tags.values():
            if not sym.IsActive:
                sym.Activate()
        if used_tags:
            doc.Regenerate()
        tag_sizes = measure_tags(view, used_tags)

        box = paper(BOX_SIZE) / 2.0
        # The run starts at its origin; the layout's "panel" is that point.
        info = {root_id: {"mapped": False, "ext": (0.0, 0.0, 0.0, 0.0), "lines": [], "panel": True,
                          "exit_dy": 0.0}}
        for n in drawn:
            lines = list(addresses.get(n, []))
            if len(lines) > 1:
                lines = [lines[0] + "-", lines[-1]]     # several addresses: first- / last, on two lines
            if n in node_symbol:
                ext = sizes[sr.eid_int(node_symbol[n].Id)]
            else:
                ext = (box, box, box, box)
                lines.insert(0, keys[n].split(" : ")[-1])
            above = named_value(elements[n], PANEL_NUMBER_PARAM)
            info[n] = {"mapped": n in node_symbol, "ext": ext, "lines": lines, "above": above}
            if n in tag_symbol:
                info[n]["tag"] = tag_sizes[sr.eid_int(tag_symbol[n].Id)]

        char_w = line_h / LINE_SPACING * 0.7    # a character is taken as about 0.7 of the text size wide
        cfg = {"spacing": DEVICE_SPACING_FT, "per_line": PER_LINE, "wrap_rounding": WRAP_ROUNDING, "char_w": char_w,
               "label_offset": LABEL_OFFSET_IN / 12.0, "above_h": above_h,
               "loop_label_raise": LOOP_LABEL_RAISE_IN / 12.0,
               "pad": paper(PAD), "text_gap": paper(TEXT_GAP), "line_h": line_h, "row_gap": paper(ROW_GAP)}

        for i, (run, origin, lock) in enumerate(zip(runs, origins, lock_refs), start=1):
            plan = rl.layout(run, root_id, info, returns, cfg)
            px, py = plan["panel"]
            plan = shift_plan(plan, origin[0] - px, origin[1] - py)
            before = view_element_ids(view)
            curves = []
            failed += draw(view, plan, node_symbol, type_id, line_h, above_type_id, curves, tag_symbol, elements)
            doc.Regenerate()
            new_ids = [eid for k, eid in view_element_ids(view).items() if k not in before]
            group = None
            if new_ids:
                group = doc.Create.NewGroup(List[ElementId](new_ids))
                gname = unique_group_name(run_name(panel_name, run, i))
                try:
                    group.GroupType.Name = gname
                except Exception:
                    pass
                groups.append(group.GroupType.Name)
            if lock is not None:
                # The first line of the one-line: horizontal, starting at the origin.
                first = None
                for p, q, curve in curves:
                    if abs(p[1] - origin[1]) < 1e-6 and abs(q[1] - origin[1]) < 1e-6 and \
                            abs(min(p[0], q[0]) - origin[0]) < 1e-6:
                        first = curve
                        break
                gname = run_name(panel_name, run, i)
                if first is None:
                    not_locked.append("%s: its first line could not be found" % gname)
                else:
                    why = lock_to_reference(view, references_in_instance(panel_inst, view, lock[0], lock[1]),
                                            first)
                    if why:
                        cand = lock[0]
                        label = ", ".join(cand["labels"][:2]) or cand["kind"].lower()
                        if (cand.get("is_ref") or "").lower().startswith("not a"):
                            why = ("%s '%s' is set to Is Reference = Not a Reference, so Revit can't lock "
                                   "to it from outside the family. Set it to Weak Reference in %s, reload "
                                   "the family and run again." % (cand["kind"], label, PANEL_FAMILY))
                        elif "not geometrically aligned" in why:
                            why = ("none of the panel's references is at the height of %s '%s' (Is Reference: "
                                   "%s). Check it isn't set to Not a Reference and that the panel detail in "
                                   "the view is the current version of %s. (%s)"
                                   % (cand["kind"].lower(), label, cand.get("is_ref") or "unknown",
                                      PANEL_FAMILY, why))
                        not_locked.append("%s: %s The one-line is drawn in line with it; only the lock is "
                                          "missing." % (gname, why))
        t.Commit()
    except Exception as ex:
        if t.HasStarted() and not t.HasEnded():
            t.RollBack()
        undo_view()
        forms.alert("The riser could not be created:\n%s" % ex, title=TITLE)
        return

    try:
        uidoc.ActiveView = view
    except Exception:
        pass

    count = sum(len(row["nodes"]) for row in rows)
    taps = len(rows) - len(runs)
    msg = "%s '%s': %d device(s) on %d run(s)" % ("Created" if target is None else "Added to",
                                                   view.Name, count, len(runs))
    if taps:
        msg += " and %d T-tap(s)" % taps
    msg += "."
    if groups:
        msg += "\n\nGroup(s): " + ", ".join(groups)
    if target is not None and panel_inst is None:
        msg += "\n\nNo %s panel detail was used in this view, so no panel was added." % PANEL_FAMILY
    if failed:
        msg += "\n\n%d item(s) could not be drawn." % failed
    if not_locked:
        msg += "\n\nNot locked to the reference line:\n" + "\n".join(not_locked)
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
