# -*- coding: utf-8 -*-
# mounting_rules module - version v1
"""Stores and reads routing preferences for Fire Alarm Device families:
 - mounting: 'Wall' or 'Ceiling'
 - conduit_type: the conduit type used for runs leaving that family
Preferences are keyed by family name and saved in a JSON file, so no family parameters are touched."""
import os
import json

# Set this to a shared path (e.g. r"\\server\share\mounting_rules.json") to share rules between users.
# Leave as None to store the file next to this module.
RULES_PATH = None

WALL = "Wall"
CEILING = "Ceiling"
KEY_MOUNT = "mounting"
KEY_TYPE = "conduit_type"


def rules_path():
    if RULES_PATH:
        return RULES_PATH
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "mounting_rules.json")


def _normalize(raw):
    """Accepts the old flat format {family: 'Wall'} and the new format {family: {mounting, conduit_type}}."""
    out = {}
    for fam, val in raw.items():
        entry = {}
        if isinstance(val, dict):
            m = val.get(KEY_MOUNT)
            if m in (WALL, CEILING):
                entry[KEY_MOUNT] = m
            t = val.get(KEY_TYPE)
            if t:
                entry[KEY_TYPE] = t
        elif val in (WALL, CEILING):
            entry[KEY_MOUNT] = val
        if entry:
            out[fam] = entry
    return out


def load_rules():
    p = rules_path()
    if not os.path.exists(p):
        return {}
    try:
        with open(p, "r") as f:
            data = json.load(f)
        return _normalize(data)
    except Exception:
        return {}


def save_rules(rules):
    p = rules_path()
    folder = os.path.dirname(p)
    if folder and not os.path.exists(folder):
        os.makedirs(folder)
    with open(p, "w") as f:
        json.dump(_normalize(rules), f, indent=2, sort_keys=True)


def get_mounting(family_name, rules=None):
    """Returns 'Wall', 'Ceiling', or None if the family has no mounting rule."""
    if rules is None:
        rules = load_rules()
    entry = rules.get(family_name)
    if isinstance(entry, dict):
        return entry.get(KEY_MOUNT)
    return entry if entry in (WALL, CEILING) else None


def get_conduit_type_name(family_name, rules=None):
    """Returns the saved 'Family : Type' label for conduit leaving this family, or None."""
    if rules is None:
        rules = load_rules()
    entry = rules.get(family_name)
    if isinstance(entry, dict):
        return entry.get(KEY_TYPE)
    return None


def _family_name(el):
    try:
        return el.Symbol.Family.Name
    except Exception:
        return None


def get_mounting_for_element(el, rules=None):
    name = _family_name(el)
    return get_mounting(name, rules) if name else None


def get_conduit_type_name_for_element(el, rules=None):
    name = _family_name(el)
    return get_conduit_type_name(name, rules) if name else None


# ---------------- conduit type helpers (need a Revit document) ----------------

def conduit_type_label(t):
    """'Family : Type' label for a ConduitType element."""
    try:
        fam = t.FamilyName
    except Exception:
        fam = u""
    try:
        nm = t.Name
    except Exception:
        nm = u""
    if fam:
        return u"{} : {}".format(fam, nm)
    return u"{}".format(nm)


def _conduit_types(doc):
    from Autodesk.Revit.DB import FilteredElementCollector
    from Autodesk.Revit.DB.Electrical import ConduitType
    return list(FilteredElementCollector(doc).OfClass(ConduitType))


def list_conduit_type_labels(doc):
    return sorted(set(conduit_type_label(t) for t in _conduit_types(doc)))


def find_conduit_type(doc, label):
    """Find the ConduitType in this project that matches a saved label, or None."""
    types = _conduit_types(doc)
    for t in types:
        if conduit_type_label(t) == label:
            return t
    for t in types:   # fall back to type name alone
        try:
            if t.Name == label:
                return t
        except Exception:
            pass
    return None
