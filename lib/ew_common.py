# -*- coding: utf-8 -*-
# ew_common module - version v2
# Change log (last change first):
#   v2 - Code consolidation step 4 (Auto Conduit v6, Auto-Circuit v7, Address SLC v7, SLC Riser v33, Link Clash
#        v13): picking a device or a tag hosted to it (tagged_hosts, resolve_pick, PickFilter, resolve_device,
#        DeviceOrTagFilter, ConduitFilter, shift_down) and pick highlighting (make_highlight, highlight).
#   v1 - Code consolidation step 3 (Link Clash v12, NAC Coverage Checker v3, Line Nuke v4, Consolidate Text
#        Styles v5, Address NAC / Voice - Config v3): small helpers every tool shares, moved here from
#        conduit_routing, conduit_trace, nac_voice_types, slc_addressing, slc_riser and five tool scripts.
"""Small helpers shared by the EW Test Suite tools. Check here before writing a new one.

eid_int / eid        the number of an ElementId in any Revit version (.Value on 2024+, .IntegerValue before)
DEVICE_CATEGORIES    the categories that count as devices (Fire Alarm Devices)
is_device            True for an element in one of those categories
type_name / type_key the name of a type, and its 'Family : Type' key
family_key           the 'Family : Type' key of a placed element: the key used in the config tables

Picking (every tool that asks for an element also accepts a tag hosted to it):
tagged_hosts         the elements a tag is hosted to
resolve_pick         what a pick stands for: the element itself, or the element its tag is hosted to
PickFilter           selection filter for elements that pass a rule, or tags hosted to one (optionally conduit)
resolve_device / DeviceOrTagFilter / ConduitFilter   the same for Fire Alarm Devices, and conduit only
shift_down           True while Shift is held (Shift+click to take a pick back)
make_highlight / highlight                           colour picked elements in the active view"""
from Autodesk.Revit.DB import (BuiltInCategory, BuiltInParameter, IndependentTag, Transaction,
                               OverrideGraphicSettings, Color, FillPatternElement, FilteredElementCollector)
from Autodesk.Revit.DB.Electrical import Conduit
from Autodesk.Revit.UI.Selection import ISelectionFilter
from System.Windows.Input import Keyboard, ModifierKeys

DEVICE_CATEGORIES = [BuiltInCategory.OST_FireAlarmDevices]


# ---------- ElementId numbers ----------
def eid_int(eid):
    """Integer value of an ElementId in any Revit version."""
    try:
        return eid.Value            # Revit 2024+
    except Exception:
        return eid.IntegerValue     # older Revit


def eid(x):
    """Integer value of an element's Id, or of an ElementId (works across Revit versions)."""
    i = x.Id if hasattr(x, "Id") else x
    try:
        return i.Value
    except Exception:
        return i.IntegerValue


# ---------- Devices ----------
def is_device(elem):
    """True for a Fire Alarm Device (an element in DEVICE_CATEGORIES)."""
    try:
        cat = elem.Category
        if cat is None:
            return False
        cid = eid_int(cat.Id)
        return any(cid == int(c) for c in DEVICE_CATEGORIES)
    except Exception:
        return False


# ---------- Family : Type keys ----------
def type_name(etype):
    """Name of a type. Falls back to the type name parameter where Revit won't give the name directly."""
    try:
        return etype.Name
    except Exception:
        p = etype.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM)
        return p.AsString() if p is not None else ""


def type_key(etype):
    """'Family : Type' of an element type."""
    return etype.FamilyName + " : " + type_name(etype)


def family_key(doc, el):
    """'Family : Type' of an element, the key used in the config tables (the type's id if it has no family)."""
    try:
        return type_key(doc.GetElement(el.GetTypeId()))
    except Exception:
        return str(eid_int(el.GetTypeId()))


# ---------- Picking: an element, or a tag hosted to it ----------
def tagged_hosts(tag):
    """Elements in this model that a tag is hosted to (any Revit version)."""
    ids = []
    try:
        ids = list(tag.GetTaggedLocalElementIds())      # Revit 2022+
    except Exception:
        try:
            ids = [tag.TaggedLocalElementId]            # older Revit
        except Exception:
            ids = []
    hosts = []
    for i in ids:
        try:
            el = tag.Document.GetElement(i)
        except Exception:
            el = None
        if el is not None:
            hosts.append(el)
    return hosts


def resolve_pick(elem, ok, prefer=None):
    """What a pick stands for: elem itself if ok(elem); for a tag, an element it is hosted to that is ok (the
    first one, or the first that also passes prefer); otherwise None."""
    if elem is None:
        return None
    try:
        if ok(elem):
            return elem
    except Exception:
        pass
    if isinstance(elem, IndependentTag):
        hosts = []
        for host in tagged_hosts(elem):
            try:
                if ok(host):
                    hosts.append(host)
            except Exception:
                pass
        if prefer is not None:
            for host in hosts:
                try:
                    if prefer(host):
                        return host
                except Exception:
                    pass
        return hosts[0] if hosts else None
    return None


class PickFilter(ISelectionFilter):
    """Allows elements that pass ok, or tags hosted to one. With conduit=True also conduit (for tools that
    follow a picked conduit)."""
    def __init__(self, ok, conduit=False):
        self.ok = ok
        self.conduit = conduit

    def AllowElement(self, elem):
        try:
            if self.conduit and isinstance(elem, Conduit):
                return True
            return resolve_pick(elem, self.ok) is not None
        except Exception:
            return False

    def AllowReference(self, ref, pt):
        return False


def resolve_device(elem):
    """The Fire Alarm Device a pick stands for (the device, or a tag hosted to one), or None."""
    return resolve_pick(elem, is_device)


class DeviceOrTagFilter(PickFilter):
    """Allows Fire Alarm Devices, or tags hosted to one; with conduit=True also conduit."""
    def __init__(self, conduit=False):
        PickFilter.__init__(self, is_device, conduit)


class ConduitFilter(ISelectionFilter):
    """Allows conduit only."""
    def AllowElement(self, elem):
        return isinstance(elem, Conduit)

    def AllowReference(self, ref, pt):
        return False


def shift_down():
    """True while a Shift key is held."""
    try:
        return (Keyboard.Modifiers & ModifierKeys.Shift) == ModifierKeys.Shift
    except Exception:
        return False


# ---------- Highlighting picked elements ----------
def make_highlight(doc, color=(255, 0, 160), weight=6):
    """Graphic override used to mark picked elements, or None if it can't be built.
    color: (R, G, B); weight: line weight 1-16."""
    try:
        col = Color(*color)
        ogs = OverrideGraphicSettings()
        ogs.SetProjectionLineColor(col)
        ogs.SetProjectionLineWeight(weight)
    except Exception:
        return None
    try:   # solid colour fill as well, where the Revit version supports it
        for fp in FilteredElementCollector(doc).OfClass(FillPatternElement):
            if fp.GetFillPattern().IsSolidFill:
                ogs.SetSurfaceForegroundPatternId(fp.Id)
                ogs.SetSurfaceForegroundPatternColor(col)
                break
    except Exception:
        pass
    return ogs


def highlight(doc, uidoc, ogs, ids, tool_name):
    """Apply an override (a highlight, or a blank one to clear it) to elements in the active view.
    The transaction is named '<tool_name> highlight'. Returns False if Revit refused."""
    t = Transaction(doc, "{} highlight".format(tool_name))
    try:
        t.Start()
        view = doc.ActiveView
        for i in ids:
            view.SetElementOverrides(i, ogs)
        t.Commit()
        uidoc.RefreshActiveView()
        return True
    except Exception:
        try:
            if t.HasStarted() and not t.HasEnded():
                t.RollBack()
        except Exception:
            pass
        return False
