# -*- coding: utf-8 -*-
# ew_common module - version v1
# Change log (last change first):
#   v1 - Code consolidation step 3 (Link Clash v12, NAC Coverage Checker v3, Line Nuke v4, Consolidate Text
#        Styles v5, Address NAC / Voice - Config v3): small helpers every tool shares, moved here from
#        conduit_routing, conduit_trace, nac_voice_types, slc_addressing, slc_riser and five tool scripts.
"""Small helpers shared by the EW Test Suite tools. Check here before writing a new one.

eid_int / eid        the number of an ElementId in any Revit version (.Value on 2024+, .IntegerValue before)
DEVICE_CATEGORIES    the categories that count as devices (Fire Alarm Devices)
is_device            True for an element in one of those categories
type_name / type_key the name of a type, and its 'Family : Type' key
family_key           the 'Family : Type' key of a placed element: the key used in the config tables"""
from Autodesk.Revit.DB import BuiltInCategory, BuiltInParameter

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
