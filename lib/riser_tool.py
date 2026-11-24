# -*- coding: utf-8 -*-
# riser_tool module - version v18
# Change log (last change first):
#   v18 - NAC Riser v15: a kind with select_runs offers 'Trace Selected Circuits' instead of 'Trace Every Run From
#         Panel' - a list of every circuit in the project (N1-2 (5 devices)); the chosen ones are traced from the
#         panel, one one-line each (choose_circuits, split_rows_by_circuit).
#   v17 - VESDA Pipe Swap v3 (no riser change): named_value now calls the shared copy in ew_common.
#   v16 - SLC Riser v51 / NAC Riser v14: devices on a circuit that no conduit reaches are no longer marked NOT
#         CONNECTED; the user chooses to add them in address order, add them at the end, or leave them off.
#         Callouts are measured filled in from their device and without the symbol size cap, so callouts side by
#         side no longer overlap.
#   v15 - SLC Riser v50 / NAC Riser v13: fix - adding a circuit below one already locked to the panel (Loop 1 after
#         Loop 3) broke the lock: raising a Loop Spacing moves the locked circuits above with their reference
#         lines, and they were then moved again. Now each circuit is only moved by what it hasn't moved already.
#   v14 - SLC Riser v49 / NAC Riser v12: the automatic Loop Spacing adjustment never leaves Loop Spacing 1 below
#         10' (MIN_LOOP_SPACING_1_FT); it is raised first, and the circuits move up with it.
"""The one-line riser engine: pick the head end and the first device, trace the conduit, check the device count,
choose the view, place the head end detail (NEX2-DETAIL-RISER), draw each circuit's one-line, group it and lock it
to the head end's numbered reference line.

run(kind) draws a riser for one circuit kind. The kind supplies (see nac_riser.CircuitKind for one):
  title, riser_name, view_tag, config_name   'NAC Riser', 'NAC Riser' (in the view name), 'NAC RISER', the config
  run_word, address_label, address_phrase    'Circuit' (group names, prompts), 'NAC Address', 'a NAC Address'
  head_prompt, head_example                  'Select NAC Power Supply', 'EX: FACU, NAC Panel ...'
  new_reader(), addresses(el, reader)        the device's addresses ([] = not on this riser)
  sort_key(addresses), groups(addresses)     order at a split; the circuits named in them, e.g. {(1, 2)}
  row_label(address_lists), row_number(...)  'N1-2' over the row; 2 = the head end's reference line / Loop Spacing 2
  devices_on_groups(doc, groups)             [(element, addresses)] on those circuits, in address order
  no_address_hint                            why a device on the conduit was left off
  return_text                                'NAC RETURN', written after the last device of every one-line
  load_table, save_table, table_path, load_settings, save_settings, settings_path, DEFAULT_SETTINGS, SETTING_LIMITS

Run from a drafting view, it offers Update Selected One-Line instead: the picked one-line group's circuit is traced
again from what the group remembers (or, for older groups, from its name and address text) and redrawn in place.

Used by SLC Riser (slc_riser.LoopKind) and NAC Riser (nac_riser.CircuitKind)."""
from Autodesk.Revit.DB import (
    XYZ, Line, Transaction, FilteredElementCollector, FamilyInstance, ViewDrafting, ViewFamilyType,
    ViewFamily, TextNote, StorageType, TextNoteType, TextNoteOptions, HorizontalTextAlignment, ElementTypeGroup,
    ElementId, BuiltInParameter, ElementTransformUtils, GroupType, SketchPlane, Plane,
    ReferencePlane, Options, GeometryInstance, SubTransaction, FamilyInstanceReferenceType, Reference,
    Outline, BoundingBoxIntersectsFilter, Group
)
from System.Collections.Generic import List
try:
    from Autodesk.Revit.DB import VerticalTextAlignment
except ImportError:
    VerticalTextAlignment = None    # older Revit: text is placed by its top already
from Autodesk.Revit.DB.Electrical import Conduit
from Autodesk.Revit.DB import BuiltInCategory, FamilySymbol, CurveElement
from Autodesk.Revit.UI.Selection import ObjectType, ObjectSnapTypes, ISelectionFilter
from Autodesk.Revit.Exceptions import OperationCanceledException
from Autodesk.Revit.DB.ExtensibleStorage import Schema, SchemaBuilder, AccessLevel, Entity
from pyrevit import revit, forms, script

import json
import math
import re

import clr
import System

import slc_riser as sr        # Revit helpers and the symbol table entries shared by the risers
import riser_layout as rl
import ew_common as ec        # shared helpers (lib/ew_common.py)
import circuit_config as cc   # Family Defaults Config: Head End types, Address Groups (lib/circuit_config.py)

doc = revit.doc
uidoc = revit.uidoc
output = script.get_output()

KIND = None         # the circuit kind being drawn, set by run()
TITLE = "Riser"     # the kind's title, set by run()

# ---------------- Settings ----------------
# These come from the kind's tab in Riser - Config; the values here are replaced in run().
VIEW_SCALE = 96         # scale of the new drafting view (96 = 1/8" = 1'-0")
PER_LINE = 5            # devices on one line before the row wraps underneath
WRAP_ROUNDING = 0       # a line only wraps when it would have more than PER_LINE + this
DEVICE_SPACING_FT = 4.5 # device centre to device centre, in feet in the view
LABEL_OFFSET_IN = 1.0   # device address text starts this many inches (in the view) below the riser line
ADDRESS_CALLOUTS = {}   # {Address Group: {subgroup: callout symbol}} from the kind's settings (SLC only)
LOOP_LABEL_RAISE_IN = 5.0   # loop letter (A, B ...) sits this many inches (in the view) higher, with a
                            # detail line from under its centre down to the riser line
ABOVE_TEXT_SIZE_IN = 5.0 / 64.0     # text above a device (its Panel #): size on the sheet, in inches
ABOVE_TEXT_TYPE_NAME = 'Riser 5/64"'    # made from the default text type if no 5/64" type exists; set by run()
                                        # to '<title> 5/64"'
# Sizes on the printed sheet, in inches:
ROW_GAP = 0.5           # extra space between rows
LOOP_CLEARANCE = 0.125  # least space between two circuits on the panel detail; more Loop Spacing is added to keep it
MIN_LOOP_SPACING_1_FT = 10.0    # the automatic adjustment never leaves Loop Spacing 1 smaller than this
PAD = 0.125             # space above and below each line of devices
TEXT_GAP = 0.06         # between a symbol and the addresses under it
BOX_SIZE = 0.375        # box drawn for a type that has no symbol
MAX_SYMBOL = 2.0        # a symbol measured larger than this is treated as this size
LINE_SPACING = 1.6      # text line height as a multiple of the text size
UNCONNECTED_BY_ADDRESS = "Add Them in Address Order"     # devices on the circuit that no conduit reaches
UNCONNECTED_AT_END = "Add Them at the End of the Line"
UNCONNECTED_LEAVE_OFF = "Leave Them Off"
PANEL_NUMBER_PARAM = "Panel #"      # the panel's name on the diagram and in the view name
PANEL_FAMILY = "NEX2-DETAIL-RISER"  # detail item drawn for the head end panel
NO_ROOM_TEXT = "(Room ##)"          # Location when the panel is not in a room
HEAD_SEARCH_RADIUS_FT = 5.0    # a head end with no conduit: look this far around it for an element with conduit
GUTTER_NAME = "GUTTERBOX"      # family names like GUTTER-BOX / Gutter Box come first (letters and digits compared)
GUTTER_ABOVE_FT = (0.0, 3.0)   # ... and, among those, one this far above the top of the panel (typically 1-2 ft)
FIRST_PICK = "Select First Device"
FIRST_ALL_RUNS = "Trace Every Run From Panel"
FIRST_SELECTED = "Trace Selected Circuits"      # instead of FIRST_ALL_RUNS for a kind with select_runs (NAC)
CIRCUIT_LABELS = {}     # circuit (KIND.groups) -> 'N1-2', filled by choose_circuits()
ORIGIN_PICK = "Pick Start Point"
HEAD_FROM_LIST = "Select from List"
HEAD_IN_MODEL = "Select in Model"
HEAD_END_CATEGORIES = [BuiltInCategory.OST_FireAlarmDevices, BuiltInCategory.OST_ElectricalEquipment]
UPDATE_ONELINE = "Update Selected One-Line"
ONELINE_SCHEMA_GUID = "6f3f0a52-6c1e-4b5e-9a57-2f1d8c4e7b31"    # extensible storage on each one-line group
PANEL_MODEL_PARAM = "Panel Model"   # the panel detail's field, filled from the panel's Model
NEW_VIEW = "Generate New Drafting View"
EXISTING_VIEW = "Add to Existing Drafting View"
LABEL_ANGLE = math.pi / 4.0         # device address text: 45 degrees


def paper(inches):
    """Inches on the sheet -> feet in the view."""
    return inches / 12.0 * VIEW_SCALE


# ---------- Starting element ----------


resolve = ec.resolve_pick                   # from ew_common: elem, or the element its tag is hosted to


def is_conduit_source(el):
    return isinstance(el, FamilyInstance) and len(sr.conduit_connectors(el)) > 0


def is_head_candidate(el):
    """What can be picked as the head end: anything conduit connects to, or a panel in a head end category (its
    conduit may land on a gutter box above it instead)."""
    if not isinstance(el, FamilyInstance):
        return False
    if is_conduit_source(el):
        return True
    try:
        cid = sr.eid_int(el.Category.Id)
        return any(cid == int(c) for c in HEAD_END_CATEGORIES)
    except Exception:
        return False


def has_conduit_connected(el):
    """True when at least one of the element's conduit connectors is connected."""
    for c in sr.conduit_connectors(el):
        try:
            if c.IsConnected:
                return True
        except Exception:
            pass
    return False


def _gutter_like(el):
    try:
        name = ec.family_key(doc, el).split(" : ")[0]
    except Exception:
        return False
    return GUTTER_NAME in re.sub(r"[^A-Z0-9]", "", name.upper())


def conduit_entry(panel):
    """The element to trace from: the panel itself when conduit is connected to it; otherwise the best element
    with conduit connected within HEAD_SEARCH_RADIUS_FT of it - a GUTTER-BOX family first, preferably 1-2 ft above
    the panel, then the closest. The panel itself when there is none."""
    if has_conduit_connected(panel):
        return panel
    bb = panel.get_BoundingBox(None)
    if bb is None:
        return panel
    r = HEAD_SEARCH_RADIUS_FT
    box = Outline(XYZ(bb.Min.X - r, bb.Min.Y - r, bb.Min.Z - r), XYZ(bb.Max.X + r, bb.Max.Y + r, bb.Max.Z + r))
    centre = (bb.Min + bb.Max) * 0.5
    reader = KIND.new_reader()
    ranked = []
    for el in (FilteredElementCollector(doc).OfClass(FamilyInstance)
               .WherePasses(BoundingBoxIntersectsFilter(box)).ToElements()):
        if el.Id == panel.Id or not has_conduit_connected(el):
            continue
        try:
            if sr.is_device(el) and KIND.addresses(el, reader):
                continue        # a device on the circuit is not the way in to the panel
        except Exception:
            pass
        ebb = el.get_BoundingBox(None)
        if ebb is None:
            continue
        gap = ebb.Min.Z - bb.Max.Z                  # how far above the top of the panel it starts
        above = GUTTER_ABOVE_FT[0] - 0.5 <= gap <= GUTTER_ABOVE_FT[1]
        distance = ((ebb.Min + ebb.Max) * 0.5).DistanceTo(centre)
        ranked.append(((0 if _gutter_like(el) else 1, 0 if above else 1, distance), el, gap))
    if not ranked:
        ec.alert("No conduit is connected to the selected panel, and no element within %g' of it has conduit "
                    "connected either." % HEAD_SEARCH_RADIUS_FT,
                    sub_msg="Connect the conduit to the panel or its gutter box and run the tool again.",
                    title=TITLE)
        return panel
    ranked.sort(key=lambda t: t[0])
    _, best, gap = ranked[0]
    where = ("%s above the panel" % feet_text(gap)) if gap >= 0 else "next to the panel"
    forms.toast("No conduit on the panel - tracing from %s (%s)." % (ec.family_key(doc, best), where), title=TITLE)
    output.print_md("%s: no conduit is connected to the panel, so the conduit is traced from %s %s (%s)."
                    % (TITLE, output.linkify(best.Id), ec.family_key(doc, best), where))
    return best


def is_addressed_device(el):
    return sr.is_device(el) and len(KIND.addresses(el, KIND.new_reader())) > 0


ElementOrTagFilter = ec.PickFilter          # from ew_common


def has_parameter(el, name):
    """True when the element or its type has a parameter with that name (case ignored), with or without a value."""
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
                if p.Definition.Name.strip().lower() == wanted:
                    return True
            except Exception:
                pass
    return False


def head_end_panels():
    """Panels in the model for the head end list. The criteria: the type is set to Head End in Family Defaults
    Config, it has a Panel # parameter and - when the kind gives head_list_keywords - its family name contains one
    of them (case ignored). A panel is listed when it meets head_list_min_matches of them (default: all); with
    head_list_keywords_required, the name must always contain one of the keywords.
    Raises if Family Defaults Config can't be read."""
    cfg = cc.load()
    keywords = [k.upper() for k in (getattr(KIND, "head_list_keywords", None) or [])]
    total = 3 if keywords else 2
    needed = getattr(KIND, "head_list_min_matches", None) or total
    name_required = bool(keywords) and bool(getattr(KIND, "head_list_keywords_required", False))
    found = []
    for cat in HEAD_END_CATEGORIES:
        for el in (FilteredElementCollector(doc).OfCategory(cat).WhereElementIsNotElementType()
                   .OfClass(FamilyInstance).ToElements()):
            key = ec.family_key(doc, el)
            met = 0
            try:
                if cc.setting(cfg, key, "device_type") == cc.HEAD_END:
                    met += 1
            except Exception:
                pass
            if has_parameter(el, PANEL_NUMBER_PARAM):
                met += 1
            if keywords:
                family = key.split(" : ")[0].upper()
                if any(k in family for k in keywords):
                    met += 1
                elif name_required:
                    continue
            if met >= needed:
                found.append(el)
    return found


def choose_head_end_from_list():
    """A head end chosen from the list, None if cancelled, or "model" to select it in the model instead."""
    try:
        panels = head_end_panels()
    except Exception as ex:
        go_on = ec.alert("Could not read Family Defaults Config:\n%s\n\nSelect the panel in the model instead?"
                            % ex, title=TITLE, yes=True, no=True)
        return "model" if go_on else None
    if not panels:
        go_on = ec.alert("No panels in this model meet the head end list's criteria (Head End in Family "
                            "Defaults Config, a Panel # parameter%s)." %
                            (", " + " / ".join(getattr(KIND, "head_list_keywords", None) or []) + " in the family name"
                             if getattr(KIND, "head_list_keywords", None) else ""),
                            sub_msg="Select the panel in the model instead?",
                            title=TITLE, yes=True, no=True)
        return "model" if go_on else None
    by_label = {}
    for el in panels:
        number = named_value(el, PANEL_NUMBER_PARAM) or "(no Panel #)"
        level = level_name(el)
        label = "%s  -  %s%s" % (number, ec.family_key(doc, el), ("  (%s)" % level) if level else "")
        if label in by_label:
            label += "  [id %d]" % sr.eid_int(el.Id)
        by_label[label] = el
    picked = forms.SelectFromList.show(sorted(by_label, key=lambda t: t.upper()),
                                       title="%s - %s" % (KIND.head_prompt, KIND.head_example),
                                       button_name="Use Panel", multiselect=False)
    if not picked:
        return None
    return by_label[picked]


def starting_element():
    ids = list(uidoc.Selection.GetElementIds())
    if len(ids) == 1:
        el = resolve(doc.GetElement(ids[0]), is_head_candidate)
        if el is not None:
            return el
    how = forms.CommandSwitchWindow.show([HEAD_FROM_LIST, HEAD_IN_MODEL],
                                         message="%s (%s)" % (KIND.head_prompt, KIND.head_example))
    if not how:
        return None
    if how == HEAD_FROM_LIST:
        el = choose_head_end_from_list()
        if el != "model":
            return el
    try:
        ref = uidoc.Selection.PickObject(ObjectType.Element, ElementOrTagFilter(is_head_candidate),
                                         "%s (or its tag) - %s" % (KIND.head_prompt, KIND.head_example))
    except OperationCanceledException:
        return None
    return resolve(doc.GetElement(ref.ElementId), is_head_candidate)


def choose_circuits():
    """The circuits (KIND.groups) chosen from a list of every circuit in the project, shown as 'N1-2 (5 devices)'.
    None when cancelled or there are none."""
    counts, labels = {}, {}
    reader = KIND.new_reader()
    for el in (FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_FireAlarmDevices)
               .WhereElementIsNotElementType().ToElements()):
        try:
            addresses = KIND.addresses(el, reader)
        except Exception:
            continue
        seen = set()
        for text in addresses or []:
            for g in KIND.groups([text]):
                if g not in labels:
                    labels[g] = KIND.row_label([[text]]) or str(g)
                seen.add(g)
        for g in seen:
            counts[g] = counts.get(g, 0) + 1
    if not counts:
        ec.alert("No devices in this project have %s." % KIND.address_phrase, title=TITLE)
        return None
    CIRCUIT_LABELS.clear()
    CIRCUIT_LABELS.update(labels)
    by_label = {}
    for g in sorted(counts):
        by_label["%s (%d device%s)" % (labels[g], counts[g], "" if counts[g] == 1 else "s")] = g
    picked = forms.SelectFromList.show([k for k in sorted(by_label, key=lambda k: by_label[k])],
                                       title="%s - %s" % (TITLE, FIRST_SELECTED), button_name="Trace",
                                       multiselect=True)
    if not picked:
        return None
    return set(by_label[k] for k in picked)


def split_rows_by_circuit(rows, addresses, circuits):
    """One row per chosen circuit, its devices in the order they were traced (across every run that reached them).
    Returns (rows, [circuits no device of which was reached])."""
    order = sorted(circuits)
    by = dict((c, []) for c in order)
    for row in rows:
        for n in row["nodes"]:
            for c in sorted(KIND.groups(addresses.get(n))):
                if c in by:
                    by[c].append(n)
                    break
    out = []
    for c in order:
        if by[c]:
            new_row = {"nodes": by[c], "source": None}
            new_row["label"] = KIND.row_label([addresses.get(n) for n in by[c]])
            out.append(new_row)
    return out, [c for c in order if not by[c]]


def first_devices(root):
    """([the device picked (directly or by its tag) as the first in the circuit], None), ([], None) if the user
    pressed Esc to follow every run from the panel, or ([], {circuits}) for Trace Selected Circuits.
    None = cancelled."""
    other = FIRST_SELECTED if getattr(KIND, "select_runs", False) else FIRST_ALL_RUNS
    choice = forms.CommandSwitchWindow.show(
        [FIRST_PICK, other],
        message="Select first Device in Circuit (or its tag). Esc while picking = trace every run from the panel.")
    if not choice:
        return None
    if choice == FIRST_ALL_RUNS:
        return [], None
    if choice == FIRST_SELECTED:
        circuits = choose_circuits()
        if circuits is None:
            return None
        return [], circuits
    flt = ElementOrTagFilter(is_addressed_device)
    while True:
        try:
            ref = uidoc.Selection.PickObject(ObjectType.Element, flt,
                                             "Select first Device in Circuit (or its tag) - Esc = every run "
                                             "from the panel")
        except OperationCanceledException:
            return [], None
        el = resolve(doc.GetElement(ref.ElementId), is_addressed_device)
        if el is not None and sr.eid_int(el.Id) != sr.eid_int(root.Id):
            return [el], None


def named_value(el, name):
    """Text of the parameter with that name (case ignored) on the element or its type, or '' (ew_common)."""
    return ec.named_value(el, name)


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
    """LEVEL 1 - NAC RISER - NAC-01"""
    parts = [level_name(root), KIND.riser_name, element_name(root)]
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
        self.addresses = {}     # id -> [addresses of the kind] for fire alarm devices
        self.conduit_type = {}  # id -> conduit type id, for conduit
        self.type_elem_ids = {} # conduit type id -> its ElementId
        self._cache = {}
        self.allowed = None
        self.wanted = None      # circuits (KIND.groups) drawn; a device of another circuit is passed through
        self.reader = KIND.new_reader()     # passed to KIND.addresses for the whole run

    def remember(self, el):
        i = sr.eid_int(el.Id)
        if i not in self.elements:
            self.elements[i] = el
            if sr.is_device(el):
                self.addresses[i] = KIND.addresses(el, self.reader)
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
        """A device drawn on this riser: it has an address, and (with wanted) it is on one of those circuits.
        A device whose addresses can't be read as a circuit is still drawn."""
        addresses = self.addresses.get(i)
        if not addresses:
            return False
        if not self.wanted:
            return True
        circuits = KIND.groups(addresses)
        return not circuits or bool(circuits & self.wanted)

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


def trace_from(root, firsts, allowed=None, circuits=None):
    """(rows, returns, elements, addresses, unaddressed devices, unconnected, conduit type UniqueIds followed) for the
    conduit connected to root, or None if the user cancelled. unconnected: {"added": [ids], "left_off": [ids],
    "how": the user's choice} for devices on the circuits that no conduit reaches (add_unconnected).
    firsts: the first device of each circuit (empty =
    every run leaving root). allowed: None = ask which conduit types to follow; "auto" = the types at the first
    devices (the ones the question starts ticked); otherwise the conduit type ids to follow. circuits: the
    circuits (KIND.groups) to draw; by default those of the first devices (all circuits when there are none)."""
    net = Network()
    root_id = net.remember(root)
    starts = [net.remember(el) for el in firsts]
    if circuits is None:
        circuits = set()
        for i in starts:
            circuits |= KIND.groups(net.addresses.get(i))
    net.wanted = set(circuits) or None
    if allowed is None:
        allowed = choose_conduit_types(net, root_id, starts or [root_id])
        if allowed is None:
            return None
    elif allowed == "auto":
        in_network = net.all_conduit_types(root_id)
        allowed = (net.conduit_types_at(starts or [root_id]) & in_network) or in_network
    net.allowed = allowed
    type_uids = []
    for tid in allowed:
        try:
            type_uids.append(doc.GetElement(net.type_elem_ids[tid]).UniqueId)
        except Exception:
            try:
                type_uids.append(doc.GetElement(ElementId(tid)).UniqueId)
            except Exception:
                pass
    children, returns, passed = rl.trace(root_id, net.ports, net.is_node, starts or None)
    # One line per run (no T-tap rows): a tee'd branch is drawn at the split, out and back, then the main run.
    rows = rl.flat_rows(root_id, children, lambda n: KIND.sort_key(net.addresses.get(n)))
    unconnected = add_unconnected(rows, net)
    if unconnected is None:
        return None
    for row in rows:
        row["label"] = KIND.row_label([net.addresses[n] for n in row["nodes"]])
    unaddressed = [net.elements[i] for i in passed if i in net.addresses and not net.addresses[i]]
    return rows, returns, net.elements, net.addresses, unaddressed, unconnected, type_uids


def insert_by_address(nodes, i, addresses):
    """Put device i into the one-line after the device with the highest address below its own (first if none)."""
    key = KIND.sort_key(addresses.get(i))
    best, pos = None, 0
    for k, n in enumerate(nodes):
        nk = KIND.sort_key(addresses.get(n))
        if nk < key and (best is None or nk > best):
            best, pos = nk, k + 1
    nodes.insert(pos, i)


def add_unconnected(rows, net):
    """Devices on a run's circuit (e.g. same N#-#) that the conduit didn't reach: the user chooses to add them in
    address order (each after the device with the next lower address), at the end of the line, or to leave them
    off. Returns {"added": [ids], "left_off": [ids], "how": choice}, or None if the user cancelled."""
    loops_of = []
    for row in rows:
        loops = set()
        for n in row["nodes"]:
            loops |= KIND.groups(net.addresses.get(n))
        loops_of.append(loops)
    wanted = set()
    for loops in loops_of:
        wanted |= loops
    drawn = set(n for row in rows for n in row["nodes"])
    found = []      # (row, id), in address order
    for el, addresses in KIND.devices_on_groups(doc, wanted):
        i = net.remember(el)
        if i in drawn:
            continue
        loops = KIND.groups(addresses)
        for row, row_loops in zip(rows, loops_of):
            if loops & row_loops:
                found.append((row, i))
                drawn.add(i)
                break
    if not found:
        return {"added": [], "left_off": [], "how": None}
    labels = sorted(set(KIND.row_label([net.addresses.get(n) for n in row["nodes"]]) for row, _i in found) - set([""]))
    where = (" on %s %s" % (KIND.run_word, ", ".join(labels))) if labels else ""
    how = forms.CommandSwitchWindow.show(
        [UNCONNECTED_BY_ADDRESS, UNCONNECTED_AT_END, UNCONNECTED_LEAVE_OFF],
        message="%d device(s)%s have %s but no conduit path from the panel. Add them to the riser?"
                % (len(found), where, KIND.address_phrase))
    if not how:
        return None
    if how == UNCONNECTED_LEAVE_OFF:
        return {"added": [], "left_off": [i for _row, i in found], "how": how}
    for row, i in found:
        if how == UNCONNECTED_BY_ADDRESS:
            insert_by_address(row["nodes"], i, net.addresses)
        else:
            row["nodes"].append(i)
    return {"added": [i for _row, i in found], "left_off": [], "how": how}


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


def choose_target_view():
    """None = generate a new view, a ViewDrafting = add to it, False = cancelled."""
    views = drafting_views()
    options = [NEW_VIEW, EXISTING_VIEW] if views else [NEW_VIEW]
    choice = forms.CommandSwitchWindow.show(options, message="Where should this circuit be drawn?")
    if not choice:
        return False
    if choice == NEW_VIEW:
        return None
    # This kind's riser views first, then the rest, each alphabetical.
    names = sorted(views, key=lambda n: (0 if KIND.view_tag in n.upper() else 1, n.upper()))
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


def panel_model(root):
    """The panel's Model: Revit's built-in Model parameter of its type (or of the panel), else a parameter named
    Model; '' if there is none."""
    holders = []
    try:
        holders.append(doc.GetElement(root.GetTypeId()))
    except Exception:
        pass
    holders.append(root)
    for holder in holders:
        if holder is None:
            continue
        try:
            p = holder.get_Parameter(BuiltInParameter.ALL_MODEL_MODEL)
            text = (p.AsString() or "").strip() if p is not None else ""
        except Exception:
            text = ""
        if text:
            return text
    return named_value(root, "Model")


def refresh_panel(inst, root):
    """Fill the panel detail's Panel #, Location and Panel Model from the panel again (Update Selected One-Line)."""
    for name, value in ((PANEL_NUMBER_PARAM, named_value(root, PANEL_NUMBER_PARAM)), ("Location", room_text(root)),
                        (PANEL_MODEL_PARAM, panel_model(root))):
        if value:
            set_text_param(inst, name, value)


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


def stacked_height(spacing, loop):
    """Height of loop N's line above the bottom of the panel. Each Loop Spacing is measured from the line below
    it (Loop Spacing 1 from the bottom of the panel), so the height is Loop Spacing 1 + 2 + ... + N.
    None when one of them is missing."""
    try:
        return sum(spacing[n] for n in range(1, int(loop) + 1))
    except (KeyError, TypeError, ValueError):
        return None
LOOP_LABEL = re.compile(r"^(?:N\s*\d+\s*)?(?:LOOP|L)?\s*[-_.#]?\s*0*(\d+)$", re.IGNORECASE)


LOOP_LABEL_END = re.compile(r"(?:LOOP|CIRCUIT|CKT|REF[A-Z]*(?:\s*LINE)?)\s*[-_.#]?\s*0*(\d+)$", re.IGNORECASE)


def label_loop(text):
    """3 for '3', 'L3', 'Loop 3', 'LOOP-03', 'N1L3', 'Ref Line 3', 'SLC Loop 3', 'Circuit 3'; None otherwise."""
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
    # The bottom of the panel in the family: a loop's line height less its height above the bottom
    # (Loop Spacing 1 + ... + N).
    spacing = PANEL_FAMILY_INFO["spacing"]
    bottoms = sorted(c["y"] - stacked_height(spacing, c["loop"]) for c in found
                     if c["loop"] is not None and c["kind"] != "Line"
                     and stacked_height(spacing, c["loop"]) is not None)
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
    if not set_text_param(inst, PANEL_MODEL_PARAM, panel_model(root)):
        skipped.append(PANEL_MODEL_PARAM)
    doc.Regenerate()
    bb = inst.get_BoundingBox(view)
    if bb is None:
        raise Exception("Could not measure the %s detail item." % PANEL_FAMILY)
    ext = (bb.Max.X - bb.Min.X, 0.0, 0.0, bb.Max.Y - bb.Min.Y)
    return inst, ext, (-bb.Max.X, -bb.Max.Y), bb.Max.Y, skipped


def row_loop(addresses, nodes):
    """The number of the head end's reference line for a row (SLC loop, NAC circuit) when all its addresses
    agree on one, else None."""
    return KIND.row_number([addresses.get(n, []) for n in nodes])


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


def base_id(sid):
    """The device id of a drawn symbol id ('<id>#<n>' for a device's second, third ... symbol)."""
    text = "%s" % sid
    if "#" not in text:
        return sid
    head = text.split("#", 1)[0]
    try:
        return int(head)
    except ValueError:
        return head


def device_callouts(drawn, keys, addresses, available, not_loaded):
    """{device id: callout FamilySymbol} for the devices whose Address Group subgroup has a callout (Riser - Config),
    and [(Family : Type, Address Group, number of addresses)] of devices whose subgroup couldn't be worked out
    (drawn with the 45 degree text; listed in the output window). Callouts that aren't loaded are added to
    not_loaded and left out."""
    found, no_subgroup = {}, []
    if not ADDRESS_CALLOUTS:
        return found, no_subgroup
    try:
        cfg = cc.load()
    except Exception as ex:
        output.print_md("**%s:** Family Defaults Config could not be read (%s), so every device has the 45 degree "
                        "address text." % (TITLE, ex))
        return found, no_subgroup
    seen = set()
    for n in drawn:
        count = len(addresses.get(n, []))
        group, sub, symbol = sr.callout_for(ADDRESS_CALLOUTS, cfg, keys[n], count)
        if group and sub is None and (keys[n], count) not in seen:
            seen.add((keys[n], count))
            no_subgroup.append((keys[n], group, count))
        if not symbol:
            continue
        if symbol in available:
            found[n] = available[symbol]
        else:
            not_loaded.add(symbol)
    if no_subgroup:
        output.print_md("### %s - no Address Group subgroup for the number of addresses" % TITLE)
        output.print_md("These are drawn with the 45 degree address text (no subgroup of their Address Group in "
                        "Family Defaults Config has that many addresses):")
        for key, group, count in no_subgroup:
            output.print_md("- %s - %s, %d address(es)" % (key, group, count))
    return found, no_subgroup


def expand_devices(rows, returns, elements, addresses, keys, device_symbols, available):
    """Replace every device in the rows with the symbols drawn for it (see riser_layout.assign_symbols).
    The first symbol keeps the device's id; the others get '<id>#<n>'. elements, addresses and keys are
    filled in for the new ids. Returns (rows, returns, {id: FamilySymbol}, ids of each device's first symbol)."""
    parts_of, node_symbol = {}, {}
    for row in rows:
        for n in row["nodes"]:
            if n in parts_of:
                continue
            key = keys[n]
            if n in device_symbols:
                symbols = device_symbols[n]
                parts = rl.assign_symbols(addresses.get(n, []), len(symbols))
            else:
                symbols, parts = None, [(None, list(addresses.get(n, [])))]
            ids = []
            for k, (idx, addrs) in enumerate(parts):
                sid = n if k == 0 else "%s#%d" % (n, k)
                elements[sid] = elements[n]
                keys[sid] = key
                addresses[sid] = addrs
                if idx is not None:
                    node_symbol[sid] = available[symbols[idx]]
                ids.append(sid)
            parts_of[n] = ids
    new_rows = []
    for row in rows:
        nodes = []
        for n in row["nodes"]:
            nodes.extend(parts_of[n])
        new_row = dict(row)
        new_row["nodes"] = nodes
        new_rows.append(new_row)
    new_returns = set(parts_of[n][-1] for n in returns if n in parts_of)
    firsts = set(ids[0] for ids in parts_of.values())
    return new_rows, new_returns, node_symbol, firsts


def run_name(panel_name, row, index):
    """'NAC-01 - Circuit N1-2' (or '... - Run 2' when the circuit can't be read from the addresses)."""
    label = row.get("label")
    return "%s - %s" % (panel_name, ("%s %s" % (KIND.run_word, label)) if label else ("Run %d" % index))


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


def set_loop_spacing(panel, loop, value):
    """Set Loop Spacing <loop> on the panel (the instance parameter, else its type's). Returns "instance", "type",
    or None when there is no such parameter that can be changed."""
    holders = [("instance", panel)]
    try:
        holders.append(("type", panel.Symbol))
    except Exception:
        pass
    for where, holder in holders:
        try:
            params = list(holder.Parameters)
        except Exception:
            continue
        for prm in params:
            try:
                m = LOOP_SPACING.match(prm.Definition.Name)
                if m and int(m.group(1)) == loop and not prm.IsReadOnly:
                    if prm.Set(value):
                        return where
            except Exception:
                pass
    return None


def circuit_groups(view, panel, cands, exclude_id=None):
    """{loop number: [(group, bottom, top)]} for the circuit groups already in the view: a group belongs to loop N
    when one of its lines starts at loop N's place on the panel (the right end of its reference line)."""
    _, _, placed = panel_exit_points(view, panel, cands)
    starts = {}
    for c, y in placed:
        if c["loop"] is not None and c["loop"] not in starts and c.get("vx") is not None:
            starts[c["loop"]] = (c["vx"], y)
    found = {}
    if not starts:
        return found
    for g in FilteredElementCollector(doc, view.Id).OfClass(Group).ToElements():
        if exclude_id is not None and g.Id == exclude_id:
            continue
        loop = None
        for mid in g.GetMemberIds():
            el = doc.GetElement(mid)
            if not isinstance(el, CurveElement):
                continue
            try:
                p0, p1 = el.GeometryCurve.GetEndPoint(0), el.GeometryCurve.GetEndPoint(1)
            except Exception:
                continue
            if abs(p0.Y - p1.Y) > 1e-6:
                continue
            for k, (x, y) in starts.items():
                if abs(p0.Y - y) < 0.01 and abs(min(p0.X, p1.X) - x) < 0.01:
                    loop = k
                    break
            if loop is not None:
                break
        if loop is None:
            continue
        bb = g.get_BoundingBox(view)
        if bb is not None:
            found.setdefault(loop, []).append((g, bb.Min.Y, bb.Max.Y))
    return found


def fit_circuit(view, panel, cands, loop, group):
    """Make room for the circuit just drawn (group, on loop `loop`): if it would overlap a circuit below it, its
    Loop Spacing is raised; if it would overlap one above, the Loop Spacing of the line above it is raised. The
    circuits above the raised line - and this one, when its own spacing changed - move up with it. Loop Spacing 1
    is first raised to MIN_LOOP_SPACING_1_FT when it is smaller. Returns [(loop, old, new, "instance" / "type")] for
    the Loop Spacing values changed."""
    changes = []
    doc.Regenerate()
    bb = group.get_BoundingBox(view)
    if bb is None:
        return changes
    bottom, top = bb.Min.Y, bb.Max.Y
    others = circuit_groups(view, panel, cands, group.Id)
    clear = paper(LOOP_CLEARANCE)

    def low_point(g):
        try:
            box = g.get_BoundingBox(view)
            return box.Min.Y if box is not None else None
        except Exception:
            return None

    def raise_spacing(n, delta):
        spacing = loop_spacing_values(panel)
        if n not in spacing:
            return False
        moves = [g for k, items in others.items() if k >= n for g, _, _ in items]
        if loop >= n:
            moves.append(group)
        before = [low_point(g) for g in moves]
        where = set_loop_spacing(panel, n, spacing[n] + delta)
        if where is None:
            return False
        changes.append((n, spacing[n], spacing[n] + delta, where))
        # Circuits locked to the panel move with their reference lines here; the rest are moved below, each only
        # by what it hasn't moved already (moving a locked one again would break its lock).
        doc.Regenerate()
        for g, was in zip(moves, before):
            now = low_point(g)
            left = delta if was is None or now is None else delta - (now - was)
            if abs(left) > 1e-6:
                ElementTransformUtils.MoveElement(doc, g.Id, XYZ(0, left, 0))
        for k in list(others):
            if k >= n:
                others[k] = [(g, b + delta, t + delta) for g, b, t in others[k]]
        return True

    first = loop_spacing_values(panel).get(1)
    if first is not None and first < MIN_LOOP_SPACING_1_FT - 1e-6 and raise_spacing(1, MIN_LOOP_SPACING_1_FT - first):
        bottom += MIN_LOOP_SPACING_1_FT - first     # every loop sits on Loop Spacing 1, this one included
        top += MIN_LOOP_SPACING_1_FT - first
    below = [t for k, items in others.items() if k < loop for _, _, t in items]
    if below:
        need = max(below) + clear - bottom
        if need > 1e-6 and raise_spacing(loop, need):
            bottom += need
            top += need
    above = [b for k, items in others.items() if k > loop for _, b, _ in items]
    if above:
        need = top + clear - min(above)
        if need > 1e-6:
            raise_spacing(loop + 1, need)
    if changes:
        doc.Regenerate()
    return changes


def panel_exit_points(view, panel, cands):
    """(x of the panel's right side, top of the panel, [(candidate, y in the view)]), or (None, None, []).
    A loop's height comes from the placed panel's Loop Spacing values: each is measured from the line below it,
    so loop N is Loop Spacing 1 + ... + N above the bottom of the panel. Its reference line's height in the family
    is the fallback when one of those is missing. Each candidate also gets "vx" (x of its right
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
        if loop not in have and stacked_height(spacing, loop) is not None:
            cands.append({"kind": "Loop Spacing", "labels": ["Loop Spacing %d" % loop], "y": None,
                          "x": common_x, "loop": loop, "name": None, "is_ref": ""})
    out = []
    for c in cands:
        try:
            y_fam = c["y"]
            height = stacked_height(spacing, c["loop"]) if c["loop"] is not None else None
            if c["loop"] in spacing and height is None:
                missing = [n for n in range(1, c["loop"]) if n not in spacing]
                output.print_md("%s: Loop Spacing %s missing on the panel, so loop %d is placed at its reference "
                                "line as drawn in the family." % (TITLE, ", ".join(str(n) for n in missing),
                                                                  c["loop"]))
            if height is not None and bottom is not None:
                y_fam = bottom + height
            if y_fam is None:
                if height is None:
                    continue
                # No reference line to measure from: up from the bottom of the panel as drawn.
                c["y_eff"] = None
                c["vx"] = bb.Max.X
                out.append((c, bb.Min.Y + height))
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
    choice = forms.CommandSwitchWindow.show(
        [ORIGIN_PICK], message="Select where the one-line diagram for %s should start. %s" % (name, reason))
    if not choice:
        return None
    try:
        p = uidoc.Selection.PickPoint(ObjectSnapTypes.Endpoints | ObjectSnapTypes.Nearest |
                                      ObjectSnapTypes.Intersections,
                                      "Pick the start of the one-line for %s" % name)
    except OperationCanceledException:
        return None
    except Exception as ex:
        ec.alert("Could not pick a point in '%s':\n%s" % (view.Name, ex), title=TITLE)
        return None
    return (p.X, p.Y)


def shift_plan(plan, dx, dy):
    """The plan moved by (dx, dy)."""
    out = {"symbols": [(x + dx, y + dy, n) for x, y, n in plan["symbols"]],
           "boxes": [(x + dx, y + dy, l, r, u, d) for x, y, l, r, u, d in plan["boxes"]],
           "lines": [((p[0] + dx, p[1] + dy), (q[0] + dx, q[1] + dy)) for p, q in plan["lines"]],
           "texts": [(x + dx, y + dy, t, how) for x, y, t, how in plan["texts"]],
           "leader_texts": [(x + dx, y + dy, t, ex + dx, ey + dy)
                            for x, y, t, ex, ey in plan.get("leader_texts", [])],
           "callouts": [(x + dx, y + dy, n) for x, y, n in plan.get("callouts", [])]}
    return out


def measure_symbols(view, symbols, fill_from=None, capped=True):
    """{symbol id: (left, right, up, down)} - how far each symbol reaches from its insertion point,
    found by placing one, measuring it and deleting it again. fill_from: {symbol id: device} whose same-named
    parameters fill the placed one first (callouts). capped: a reach over MAX_SYMBOL / 2 counts as that."""
    cap = paper(MAX_SYMBOL) / 2.0 if capped else None
    default = paper(BOX_SIZE) / 2.0
    placed = {}
    for key, sym in symbols.items():
        try:
            placed[key] = doc.Create.NewFamilyInstance(XYZ(0, 0, 0), sym, view)
            if fill_from and key in fill_from:
                ec.copy_matching_params(fill_from[key], placed[key])
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
                    ext = tuple(max(v, 0.0) if cap is None else min(max(v, 0.0), cap)
                                for v in (-bb.Min.X, bb.Max.X, bb.Max.Y, -bb.Min.Y))
            except Exception:
                pass
            doc.Delete(inst.Id)
        sizes[key] = ext
    return sizes


def draw(view, plan, node_symbol, type_id, line_h, above_type_id=None, created=None, node_callout=None,
         elements=None):
    """Create everything in the layout. Returns the number of things that could not be created.
    created: a list that gets (start, end, detail curve) for every line drawn.
    node_callout / elements: {id: callout FamilySymbol} and {id: device}; each callout's parameters are filled from
    its device's same-named parameters."""
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
    for x, y, n in plan.get("callouts", []):
        try:
            inst = doc.Create.NewFamilyInstance(XYZ(x, y, 0), node_callout[n], view)
            ec.copy_matching_params(elements[n], inst)
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


# ---------- Update Selected One-Line (drafting views) ----------
def oneline_schema():
    """The extensible storage schema kept on each one-line group (one text field of JSON)."""
    guid = System.Guid(ONELINE_SCHEMA_GUID)
    schema = Schema.Lookup(guid)
    if schema is None:
        builder = SchemaBuilder(guid)
        builder.SetReadAccessLevel(AccessLevel.Public)
        builder.SetWriteAccessLevel(AccessLevel.Public)
        builder.SetSchemaName("EWRiserOneLine")
        builder.AddSimpleField("Data", clr.GetClrType(System.String))
        schema = builder.Finish()
    return schema


def save_oneline_data(group, data):
    """Remember how a one-line group was drawn (inside a transaction). A failure only means it can't be updated
    from this data later (it is then worked out from the group)."""
    try:
        schema = oneline_schema()
        entity = Entity(schema)
        entity.Set[System.String]("Data", json.dumps(data))
        group.SetEntity(entity)
    except Exception as ex:
        output.print_md("**%s:** could not store the circuit on group '%s' (%s); it can still be updated, worked "
                        "out from its name and addresses." % (TITLE, group.GroupType.Name, ex))


def read_oneline_data(group):
    """What save_oneline_data stored on the group, or None."""
    try:
        schema = Schema.Lookup(System.Guid(ONELINE_SCHEMA_GUID))
        if schema is None:
            return None
        entity = group.GetEntity(schema)
        if entity is None or not entity.IsValid():
            return None
        return json.loads(entity.Get[System.String]("Data"))
    except Exception:
        return None


class Update(object):
    """A one-line group to redraw: the group, its view and name, and the circuit to trace (panel, first devices,
    conduit types - "auto" when worked out), the loop it shows and where it starts (None = from its reference
    line)."""
    def __init__(self, group, view, root, firsts, allowed, loop, label, origin, circuits):
        self.group, self.view, self.name = group, view, group.GroupType.Name
        self.root, self.firsts, self.allowed = root, firsts, allowed
        self.loop, self.label, self.origin = loop, label, origin
        self.circuits = set(circuits or []) or None     # only these circuits' devices are drawn


class GroupFilter(ISelectionFilter):
    def AllowElement(self, el):
        return isinstance(el, Group)

    def AllowReference(self, ref, point):
        return False


def pick_oneline_group(view):
    try:
        ref = uidoc.Selection.PickObject(ObjectType.Element, GroupFilter(),
                                         "Select the one-line (its group) to update - Esc to cancel")
    except OperationCanceledException:
        return None
    return doc.GetElement(ref.ElementId)


def remove_group(group):
    """Delete a one-line group (and its members), and its group type when nothing else uses it."""
    gtype = group.GroupType
    doc.Delete(group.Id)
    try:
        if gtype is not None and gtype.IsValidObject and gtype.Groups.Size == 0:
            doc.Delete(gtype.Id)
    except Exception:
        pass


def group_origin(members):
    """Where a one-line starts: the left end of its topmost horizontal line, or None."""
    best = None
    for m in members:
        try:
            curve = m.GeometryCurve
            p, q = curve.GetEndPoint(0), curve.GetEndPoint(1)
        except Exception:
            continue
        if abs(p.Y - q.Y) > 1e-6:
            continue
        x = min(p.X, q.X)
        if best is None or p.Y > best[1] + 1e-6 or (abs(p.Y - best[1]) <= 1e-6 and x < best[0]):
            best = (x, p.Y)
    return best


def group_address_notes(members):
    """[(addresses written in the note, x, y of the note)] for each address text in a one-line group (first- /
    last on two lines included)."""
    notes = []
    for m in members:
        if not isinstance(m, TextNote):
            continue
        texts = []
        for line in (m.Text or "").splitlines():
            text = line.strip().rstrip("-").strip()
            if text and KIND.groups([text]):
                texts.append(text)
        if texts:
            try:
                point = (m.Coord.X, m.Coord.Y)
            except Exception:
                point = (0.0, 0.0)
            notes.append((texts, point[0], point[1]))
    return notes


def group_addresses(members):
    """The device addresses written in a one-line group's text."""
    found = []
    for texts, _x, _y in group_address_notes(members):
        for text in texts:
            if text not in found:
                found.append(text)
    return found


def first_drawn_addresses(members):
    """The addresses of the first device drawn on a one-line: its top line's leftmost address text."""
    notes = group_address_notes(members)
    if not notes:
        return []
    top = max(y for _t, _x, y in notes)
    on_top = [n for n in notes if abs(n[2] - top) < 0.01]
    return min(on_top, key=lambda n: n[1])[0]


def row_circuits(addresses, nodes):
    """The circuits (KIND.groups) of the devices in a row."""
    found = set()
    for n in nodes:
        found |= KIND.groups(addresses.get(n))
    return found


def panel_by_number(number):
    """The head end whose Panel # is number: the only one, the user's choice of several, or one from the head
    end list when none matches. None if cancelled."""
    wanted = (number or "").strip().upper()
    matches = []
    if wanted:
        try:
            candidates = head_end_panels()
        except Exception:
            candidates = []
        matches = [el for el in candidates if named_value(el, PANEL_NUMBER_PARAM).strip().upper() == wanted]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        by_label = dict(("%s  -  %s  [id %d]" % (number, ec.family_key(doc, el), sr.eid_int(el.Id)), el)
                        for el in matches)
        picked = forms.SelectFromList.show(sorted(by_label), title="Which panel is %s?" % number,
                                           button_name="Use Panel", multiselect=False)
        return by_label.get(picked) if picked else None
    picked = choose_head_end_from_list()
    return picked if picked not in (None, "model") else None


def work_out_update(group, view):
    """An Update for a one-line drawn before the circuit was stored on its group: the panel from the group name's
    Panel # (FACU-01 - Loop A), the loop from the addresses written in it, and its lowest-address device on that
    loop as the first device. None if it can't be worked out or the user cancelled."""
    members = [doc.GetElement(i) for i in group.GetMemberIds()]
    texts = group_addresses(members)
    loops = KIND.groups(texts)
    if not loops:
        ec.alert("No %s was found in the text of '%s', so its circuit can't be worked out. (Is it a %s "
                 "one-line?)" % (KIND.address_label, group.GroupType.Name, KIND.title), title=TITLE)
        return None
    name = group.GroupType.Name
    root = panel_by_number(name.rsplit(" - ", 1)[0] if " - " in name else "")
    if root is None:
        return None
    devices = KIND.devices_on_groups(doc, loops)
    # The first device drawn on it (where the one-line starts), else the lowest address shown on it.
    first_texts = set(first_drawn_addresses(members))
    starting = [el for el, addresses in devices if set(addresses) & first_texts]
    shown = [el for el, addresses in devices if set(addresses) & set(texts)]
    first = (starting or shown or [el for el, _a in devices] or [None])[0]
    return Update(group, view, root, [first] if first is not None else [], "auto",
                  KIND.row_number([texts]), KIND.row_label([texts]), group_origin(members), loops)


def prepare_update(view):
    """Pick a one-line group in the drafting view and work out how to redraw it. None if cancelled."""
    group = pick_oneline_group(view)
    if group is None:
        return None
    data = read_oneline_data(group)
    if data is None:
        return work_out_update(group, view)
    if data.get("kind") and data.get("kind") != KIND.title:
        ec.alert("'%s' was drawn by %s. Run %s to update it." % (group.GroupType.Name, data["kind"], data["kind"]),
                 title=TITLE)
        return None
    root = doc.GetElement(data.get("root") or "")
    if root is None:
        output.print_md("**%s:** the panel of '%s' is no longer in the model; working it out from the group name."
                        % (TITLE, group.GroupType.Name))
        return work_out_update(group, view)
    firsts = [el for el in (doc.GetElement(u) for u in data.get("firsts") or []) if el is not None]
    allowed = set()
    for u in data.get("conduit_types") or []:
        el = doc.GetElement(u)
        if el is not None:
            allowed.add(sr.eid_int(el.Id))
    # Where it is now (it may have been moved since it was drawn), else where it was drawn.
    origin = group_origin([doc.GetElement(i) for i in group.GetMemberIds()]) or data.get("origin")
    circuits = set(tuple(c) for c in data.get("circuits") or [])
    if not circuits:        # stored before v13: the circuits of its first devices, else its address text
        reader = KIND.new_reader()
        for el in firsts:
            circuits |= KIND.groups(KIND.addresses(el, reader))
        circuits = circuits or KIND.groups(group_addresses([doc.GetElement(i) for i in group.GetMemberIds()]))
    return Update(group, view, root, firsts, allowed or "auto", data.get("loop"), data.get("label") or "",
                  tuple(origin) if origin else None, circuits)


def update_rows(rows, addresses, update):
    """The traced row that is the one-line being updated: [row], or [] if none matches."""
    if len(rows) == 1:
        return rows
    for row in rows:
        if update.loop is not None and row_loop(addresses, row["nodes"]) == update.loop:
            return [row]
    for row in rows:
        if update.label and row.get("label") == update.label:
            return [row]
    first_ids = set(sr.eid_int(el.Id) for el in update.firsts)
    for row in rows:
        if row["nodes"] and row["nodes"][0] in first_ids:
            return [row]
    return []


# ---------- Main ----------
REVIEW_XAML = """
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Riser"
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
        <CheckBox x:Name="save_check" Content="Save these as my defaults" Margin="0,0,0,8"/>
        <TextBlock x:Name="error_text" Foreground="Firebrick" TextWrapping="Wrap" MaxWidth="400" Margin="0,0,0,8"/>
        <StackPanel Orientation="Horizontal" HorizontalAlignment="Right">
            <Button Content="Create Riser" Width="100" Margin="0,0,8,0" IsDefault="True" Click="ok_click"/>
            <Button Content="Cancel" Width="80" IsCancel="True" Click="cancel_click"/>
        </StackPanel>
    </StackPanel>
</Window>
"""


number_text = sr.number_text      # 4.5 -> '4.5', 6.0 -> '6' (from slc_riser, shared with Riser - Config)


class ReviewDialog(forms.WPFWindow):
    """Device count, with the spacing and wrapping settings to adjust before the riser is drawn.
    self.result = (spacing ft, devices per line, wrap rounding, save as default) or None if cancelled."""
    def __init__(self, rows, device_count=None):
        forms.WPFWindow.__init__(self, REVIEW_XAML, literal_string=True)
        self.Title = TITLE
        self.save_check.Content = "Save these as my defaults in %s" % KIND.config_name
        self.rows = rows
        self.result = None
        self._ready = False
        total = sum(len(r["nodes"]) for r in rows)
        if device_count is not None and device_count != total:
            self.count_text.Text = "%d device(s) (%d symbols) will be added to the riser." % (device_count, total)
        else:
            self.count_text.Text = "%d device(s) will be added to the riser." % total
        parts = []
        for r in rows:
            parts.append("%s%d" % (("%s %s: " % (KIND.run_word, r["label"])) if r.get("label") else "",
                                   len(r["nodes"])))
        detail = "%d run(s)" % len(rows)
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
            lo, hi = KIND.SETTING_LIMITS[key]
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


def review_layout(rows, device_count=None):
    """Show the device count and let the user adjust spacing and wrapping. False if cancelled."""
    global DEVICE_SPACING_FT, PER_LINE, WRAP_ROUNDING
    dlg = ReviewDialog(rows, device_count)
    dlg.ShowDialog()
    if dlg.result is None:
        return False
    DEVICE_SPACING_FT, PER_LINE, WRAP_ROUNDING, save = dlg.result
    if save:
        try:
            settings = KIND.load_settings()
        except Exception:
            settings = dict(KIND.DEFAULT_SETTINGS)
        settings.update({"device_spacing_ft": DEVICE_SPACING_FT, "devices_per_line": PER_LINE,
                         "wrap_rounding": WRAP_ROUNDING})
        try:
            KIND.save_settings(settings)
        except Exception as ex:
            ec.alert("These settings are used for this riser but could not be saved:\n%s\n\nPath: %s"
                        % (ex, KIND.settings_path()), title=TITLE)
    return True


def apply_settings():
    """Use the drawing settings saved in the kind's tab of Riser - Config. False if the file can't be read and the user
    chose to stop."""
    global VIEW_SCALE, PER_LINE, WRAP_ROUNDING, DEVICE_SPACING_FT, LABEL_OFFSET_IN, ADDRESS_CALLOUTS
    try:
        settings = KIND.load_settings()
    except Exception as ex:
        go_on = ec.alert("Could not read the riser settings, so the defaults will be used:\n%s\n\nPath: %s"
                            "\n\nContinue?" % (ex, KIND.settings_path()), title=TITLE, yes=True, no=True)
        if not go_on:
            return False
        settings = dict(KIND.DEFAULT_SETTINGS)
    VIEW_SCALE = settings["view_scale"]
    PER_LINE = settings["devices_per_line"]
    WRAP_ROUNDING = settings["wrap_rounding"]
    DEVICE_SPACING_FT = settings["device_spacing_ft"]
    LABEL_OFFSET_IN = settings["label_offset_in"]
    ADDRESS_CALLOUTS = settings.get(sr.CALLOUTS) or {}
    return True


def run(kind):
    """Draw a riser for this circuit kind (see the module notes)."""
    global KIND, TITLE, ABOVE_TEXT_TYPE_NAME
    KIND = kind
    TITLE = kind.title
    ABOVE_TEXT_TYPE_NAME = '%s 5/64"' % kind.title
    main()


def main():
    if not apply_settings():
        return
    view = uidoc.ActiveView
    if isinstance(view, ViewDrafting):
        # In a drafting view: work on the one-lines already drawn there.
        choice = forms.CommandSwitchWindow.show([UPDATE_ONELINE], message="%s - drafting view options" % TITLE)
        if choice != UPDATE_ONELINE:
            return
        update = prepare_update(view)
        if update is not None:
            draw_riser(update)
        return
    draw_riser()


def draw_riser(update=None):
    """Create a riser (update None), or redraw the one-line group in update (an Update from prepare_update)."""
    if update is None:
        root = starting_element()
        if root is None:
            return
        picked = first_devices(root)
        if picked is None:
            return
        firsts, circuits = picked
        allowed = None
    else:
        root, firsts, allowed, circuits = update.root, update.firsts, update.allowed, update.circuits
    entry = conduit_entry(root)     # the panel, or its gutter box when the conduit lands there
    traced = trace_from(entry, firsts, allowed, circuits)
    if traced is None:
        return
    rows, returns, elements, addresses, unaddressed, unconnected, type_uids = traced
    missing_circuits = []
    if update is None and circuits:
        # Trace Selected Circuits: one one-line per chosen circuit.
        rows, missing_circuits = split_rows_by_circuit(rows, addresses, circuits)
    first_uids = [el.UniqueId for el in firsts]
    if update is not None and rows:
        rows = update_rows(rows, addresses, update)
        if not rows:
            ec.alert("The circuit of '%s' could not be found from its panel any more (no traced %s matches it). "
                     "Check the conduit, or draw it again from a plan view." % (update.name, KIND.run_word.lower()),
                     title=TITLE)
            return
        on_row = set(rows[0]["nodes"])
        unconnected["added"] = [n for n in unconnected["added"] if n in on_row]
    root_id = sr.eid_int(root.Id)
    if not rows:
        msg = ("No devices with %s are connected to the selected element by conduit of the "
               "chosen type(s)." % KIND.address_phrase)
        if unaddressed:
            msg += ("\n\n%d Fire Alarm Device(s) on that conduit %s." % (len(unaddressed), KIND.no_address_hint))
        ec.alert(msg, title=TITLE)
        return

    try:
        table = KIND.load_table()
    except Exception as ex:
        ec.alert("Could not read the symbol table:\n%s\n\nPath: %s" % (ex, KIND.table_path()), title=TITLE)
        return
    available = sr.available_symbols(doc)

    # The panel is the NEX2-DETAIL-RISER detail item; the devices use the symbols from the table.
    panel_sym = panel_family_symbol()
    panel_refs = panel_reference_lines(panel_sym) if panel_sym is not None else []
    drawn = [n for row in rows for n in row["nodes"]]
    keys = dict((n, sr.family_key(doc, elements[n])) for n in drawn)
    # Symbols for each device: its type's symbols. Symbols that aren't loaded are left out.
    device_symbols, missing, not_loaded = {}, [], set()
    for n in drawn:
        key = keys[n]
        wanted = (table.get(key) or sr.new_entry())["symbols"]
        loaded = [sym for sym in wanted if sym in available]
        not_loaded.update(sym for sym in wanted if sym not in available)
        if loaded:
            device_symbols[n] = loaded
        elif key not in missing:
            missing.append(key)
    # Address callouts (SLC): by the device's Address Group subgroup; the others keep the 45 degree text.
    device_callout, no_subgroup = device_callouts(drawn, keys, addresses, available, not_loaded)
    if not_loaded:
        ec.alert("These riser symbols are set in %s but are not loaded in this project, so they "
                    "are left out:\n\n%s" % (KIND.config_name, "\n".join(sorted(not_loaded))), title=TITLE)
    if missing:
        names = sorted(available.keys())
        if not names:
            go_on = ec.alert("No Generic Annotation or Detail Item types are loaded in this project, so "
                                "there are no symbols to choose from.\n\nDraw every device as a box labeled "
                                "with its type name?", title=TITLE, yes=True, no=True)
            if not go_on:
                return
        else:
            picked_any = False
            for i, key in enumerate(missing, start=1):
                old = table.get(key) or sr.new_entry()
                if old["symbols"]:
                    forms.toast("Saved symbol(s) for %s are not loaded in this project." % key)
                picked = forms.SelectFromList.show(
                    names, title="Symbol for %s  (%d of %d without one)" % (key, i, len(missing)),
                    button_name="Use Symbol", multiselect=False)
                if picked:
                    for n in drawn:
                        if keys[n] == key and n not in device_symbols:
                            device_symbols[n] = [picked]
                    table[key] = sr.new_entry([picked])
                    picked_any = True
                    continue
                go_on = ec.alert("No symbol chosen for:\n%s\n\nDraw it as a box labeled with the type name? "
                                    "(Choose No to stop without creating the riser.)" % key,
                                    title=TITLE, yes=True, no=True)
                if not go_on:
                    break
            else:
                go_on = True
            if picked_any:      # remembered for next time, even if this run was stopped
                try:
                    KIND.save_table(table)
                except Exception as ex:
                    ec.alert("The symbols you chose are used for this riser but could not be saved:\n%s"
                                "\n\nPath: %s" % (ex, KIND.table_path()), title=TITLE)
            if not go_on:
                return

    # Each device becomes its symbols, in order, each with its own address(es).
    device_count = len(drawn)
    rows, returns, node_symbol, firsts = expand_devices(rows, returns, elements, addresses, keys,
                                                        device_symbols, available)
    # A callout is drawn once per device, under its first symbol; its other symbols get no address text.
    node_callout = dict((n, device_callout[n]) for n in firsts if n in device_callout)
    callout_parts = set(sid for sid in [n for row in rows for n in row["nodes"]]
                        if sid not in firsts and base_id(sid) in node_callout)
    drawn = [n for row in rows for n in row["nodes"]]

    if update is None and not review_layout(rows, device_count):
        return
    target = update.view if update is not None else choose_target_view()
    if target is False:
        return
    if target is None and panel_sym is None:
        go_on = ec.alert("The %s detail item is not loaded in this project, so no panel will be drawn and "
                            "you will pick where each %s's one-line starts.\n\nContinue?" % (PANEL_FAMILY, KIND.run_word.lower()),
                            title=TITLE, yes=True, no=True)
        if not go_on:
            return

    global VIEW_SCALE
    panel_name = (named_value(root, PANEL_NUMBER_PARAM) or element_name(root)).strip()

    # 1. The view, and the panel detail (a new one in a new view; the one already there otherwise).
    created_view = False
    panel_skipped = []
    t = Transaction(doc, "%s - view and panel" % TITLE)
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
        ec.alert("The riser could not be created:\n%s" % ex, title=TITLE)
        return

    def undo_view():
        if created_view:
            t2 = Transaction(doc, "%s - cancelled" % TITLE)
            t2.Start()
            try:
                doc.Delete(view.Id)
                t2.Commit()
            except Exception:
                t2.RollBack()

    if target is not None:
        panel_inst = find_view_panel(view, root)
    exit_x, panel_top, placed_refs = panel_exit_points(view, panel_inst, panel_refs)

    # 2. Where each circuit's one-line starts, and the reference line it is locked to.
    origins, lock_refs, reported = [], [], False
    for i, row in enumerate(rows, start=1):
        name = run_name(panel_name, row, i)
        loop = row_loop(addresses, row["nodes"])
        match = None
        if exit_x is not None and loop is not None:
            for c, y in placed_refs:
                if c["loop"] == loop:
                    match = (c, y)
                    break
        if match is None and update is not None and update.origin is not None:
            origins.append(update.origin)       # where the one-line being updated started
            lock_refs.append(None)
            continue
        if match is None and panel_inst is not None:
            if not reported:
                report_reference_lines(placed_refs, panel_top)
                reported = True
            reason = ("Its %s number could not be read from the device addresses." % KIND.run_word.lower()
                      if loop is None else
                      "No reference line named %d (or L%d / Loop %d) and no Loop Spacing %d was found in %s."
                      % (loop, loop, loop, loop, PANEL_FAMILY))
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

    # 3. Draw each circuit and group it.
    failed = 0
    groups, not_locked, spacing_changes = [], [], []
    t = Transaction(doc, ("Update one-line - %s" % TITLE) if update is not None else
                    ("Create %s" if target is None else "Add circuit to %s") % TITLE)
    t.Start()
    try:
        if update is not None:
            remove_group(update.group)          # its name is free again for the new one-line
            if panel_inst is not None:
                refresh_panel(panel_inst, root)
        type_id, line_h = text_type()
        above_type_id, above_h = None, line_h
        if any(named_value(elements[n], PANEL_NUMBER_PARAM) for n in drawn if n in firsts):
            above_type_id, above_h = small_text_type(type_id)
        used, callouts_used, fill_from = {}, {}, {}
        for sym in node_symbol.values():
            used[sr.eid_int(sym.Id)] = sym
        for n, sym in node_callout.items():
            callouts_used[sr.eid_int(sym.Id)] = sym
            fill_from.setdefault(sr.eid_int(sym.Id), elements[n])
        for sym in list(used.values()) + list(callouts_used.values()):
            if not sym.IsActive:
                sym.Activate()
        doc.Regenerate()
        sizes = measure_symbols(view, used)
        # Callouts: filled in from a device first (their labels change their size), and not capped in size.
        callout_sizes = measure_symbols(view, callouts_used, fill_from, capped=False)

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
            above = named_value(elements[n], PANEL_NUMBER_PARAM) if n in firsts else ""
            info[n] = {"mapped": n in node_symbol, "ext": ext, "lines": lines, "above": above}
            if n in node_callout:
                info[n]["callout"] = callout_sizes[sr.eid_int(node_callout[n].Id)]
                info[n]["lines"] = []
            elif n in callout_parts:
                info[n]["lines"] = []

        char_w = line_h / LINE_SPACING * 0.7    # a character is taken as about 0.7 of the text size wide
        cfg = {"spacing": DEVICE_SPACING_FT, "per_line": PER_LINE, "wrap_rounding": WRAP_ROUNDING, "char_w": char_w,
               "label_offset": LABEL_OFFSET_IN / 12.0, "above_h": above_h,
               "loop_label_raise": LOOP_LABEL_RAISE_IN / 12.0,
               "pad": paper(PAD), "text_gap": paper(TEXT_GAP), "line_h": line_h, "row_gap": paper(ROW_GAP),
               "end_text": getattr(KIND, "return_text", None)}

        for i, (row, origin, lock) in enumerate(zip(rows, origins, lock_refs), start=1):
            if lock is not None and spacing_changes:
                # An earlier circuit raised a Loop Spacing: read this one's place on the panel again.
                for c, y in panel_exit_points(view, panel_inst, panel_refs)[2]:
                    if c["loop"] == lock[0]["loop"] and c["kind"] == lock[0]["kind"]:
                        lock = (c, y)
                        origin = (c.get("vx", origin[0]), y)
                        break
            plan = rl.layout([row], root_id, info, returns, cfg)
            px, py = plan["panel"]
            plan = shift_plan(plan, origin[0] - px, origin[1] - py)
            before = view_element_ids(view)
            curves = []
            failed += draw(view, plan, node_symbol, type_id, line_h, above_type_id, curves, node_callout, elements)
            doc.Regenerate()
            new_ids = [eid for k, eid in view_element_ids(view).items() if k not in before]
            group = None
            if new_ids:
                group = doc.Create.NewGroup(List[ElementId](new_ids))
                gname = unique_group_name(update.name if update is not None else run_name(panel_name, row, i))
                try:
                    group.GroupType.Name = gname
                except Exception:
                    pass
                groups.append(group.GroupType.Name)
                save_oneline_data(group, {
                    "kind": KIND.title, "root": root.UniqueId, "firsts": first_uids, "conduit_types": type_uids,
                    "loop": row_loop(addresses, row["nodes"]), "label": row.get("label") or "",
                    "circuits": sorted(list(c) for c in row_circuits(addresses, row["nodes"])),
                    "origin": [origin[0], origin[1]]})
            if lock is not None:
                # The first line of the one-line: horizontal, starting at the origin.
                first = None
                for p, q, curve in curves:
                    if abs(p[1] - origin[1]) < 1e-6 and abs(q[1] - origin[1]) < 1e-6 and \
                            abs(min(p[0], q[0]) - origin[0]) < 1e-6:
                        first = curve
                        break
                # Room for it between the circuits below and above (its text and callouts included).
                if group is not None and lock[0]["loop"] is not None:
                    changed = fit_circuit(view, panel_inst, panel_refs, lock[0]["loop"], group)
                    if changed:
                        spacing_changes.extend(changed)
                        for c, y in panel_exit_points(view, panel_inst, panel_refs)[2]:
                            if c["loop"] == lock[0]["loop"] and c["kind"] == lock[0]["kind"]:
                                lock = (c, y)
                                break
                gname = run_name(panel_name, row, i)
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
        ec.alert("The riser could not be created:\n%s" % ex, title=TITLE)
        return

    try:
        uidoc.ActiveView = view
    except Exception:
        pass

    count = device_count
    if update is not None:
        msg = "Updated '%s' in '%s': %d device(s)." % (update.name, view.Name, count)
    else:
        msg = "%s '%s': %d device(s) on %d run(s)." % ("Created" if target is None else "Added to",
                                                        view.Name, count, len(rows))
    if groups:
        msg += "\n\nGroup(s): " + ", ".join(groups)
    if target is not None and panel_inst is None:
        msg += "\n\nNo %s panel detail was used in this view, so no panel was added." % PANEL_FAMILY
    if failed:
        msg += "\n\n%d item(s) could not be drawn." % failed
    if missing_circuits:
        msg += ("\n\nNo device of %s could be reached by conduit from the panel, so %s not drawn."
                % (", ".join(CIRCUIT_LABELS.get(c) or str(c) for c in missing_circuits),
                   "it was" if len(missing_circuits) == 1 else "they were"))
    if spacing_changes:
        msg += "\n\nMore room was made between circuits:\n" + "\n".join(
            "Loop Spacing %d: %s -> %s%s" % (n, feet_text(old), feet_text(new),
                                            " (type parameter - other panels of this type change too)"
                                            if where == "type" else "")
            for n, old, new, where in spacing_changes)
    if not_locked:
        msg += "\n\nNot locked to the reference line:\n" + "\n".join(not_locked)
    if panel_skipped:
        msg += ("\n\nThe %s detail item has no editable parameter named %s, so it was left as is."
                % (PANEL_FAMILY, " / ".join(panel_skipped)))
    if no_subgroup:
        msg += ("\n\n%d type(s) have an Address Group but no subgroup with their number of addresses, so they have "
                "the 45 degree address text; they are listed in the output window." % len(no_subgroup))
    no_path = unconnected["added"] or unconnected["left_off"]
    if no_path:
        done = {UNCONNECTED_BY_ADDRESS: "were added in address order",
                UNCONNECTED_AT_END: "were added at the end of the line",
                UNCONNECTED_LEAVE_OFF: "were left off"}.get(unconnected["how"], "")
        msg += ("\n\n%d device(s) on this %s have no conduit path from the panel and %s; they are listed in the "
                "output window." % (len(no_path), KIND.run_word.lower(), done))
        output.print_md("### %s - devices with no conduit path (%s)" % (TITLE, done))
        for i in no_path:
            output.print_md("- %s %s - %s" % (output.linkify(elements[i].Id), sr.family_key(doc, elements[i]),
                                              ", ".join(addresses.get(i) or [])))
    if unaddressed:
        msg += ("\n\n%d Fire Alarm Device(s) on the conduit have no %s and were left off. "
                "They are listed in the output window." % (len(unaddressed), KIND.address_label))
        output.print_md("### %s - devices on the conduit without %s" % (TITLE, KIND.address_phrase))
        for el in unaddressed:
            output.print_md("- %s %s" % (output.linkify(el.Id), sr.family_key(doc, el)))
    ec.alert(msg, title=TITLE)

