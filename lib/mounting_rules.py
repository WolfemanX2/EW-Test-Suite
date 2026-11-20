# -*- coding: utf-8 -*-
# mounting_rules module - version v2
# Change log (last change first):
#   v2 - Code consolidation step 7 (Auto Conduit - Config v3): the file moves from lib\ to the user's
#        %APPDATA%\pyRevit\EWTestSuite (the old one is copied over the first time); office default
#        config/mounting_rules.default.json; paths, reading and the safe write from config_store.
#   v1 - Auto Conduit v4 / Routing Preferences v1: mounting and conduit type per family.
"""Stores and reads routing preferences for Fire Alarm Device families:
 - mounting: 'Wall' or 'Ceiling'
 - conduit_type: the conduit type used for runs leaving that family
Preferences are keyed by family name and saved in a JSON file, so no family parameters are touched.

The file is each user's own %APPDATA%\\pyRevit\\EWTestSuite\\mounting_rules.json, so updates and reinstalls never remove
it. It used to be kept next to this module (lib\\mounting_rules.json); that file is copied over the first time."""
import os

import config_store as cs     # where settings files live, office defaults, safe write (lib/config_store.py)

# Set this to a shared path (e.g. r"\\server\share\mounting_rules.json") to share rules between users.
# Leave as None for a per-user file in %APPDATA%.
RULES_PATH = None

OLD_LOCAL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mounting_rules.json")   # before v2
DEFAULT_CONFIG = cs.default_file("mounting_rules.default.json")     # office default, when it is in the repository

WALL = "Wall"
CEILING = "Ceiling"
KEY_MOUNT = "mounting"
KEY_TYPE = "conduit_type"


def rules_path():
    return cs.user_file("mounting_rules.json", RULES_PATH)


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
    if not RULES_PATH:
        cs.start_from(p, [OLD_LOCAL, DEFAULT_CONFIG])   # the first time: the old file in lib, or the office default
    try:
        return _normalize(cs.read_json(p, {}))
    except Exception:
        return {}


def save_rules(rules):
    cs.write_json(rules_path(), _normalize(rules))


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
