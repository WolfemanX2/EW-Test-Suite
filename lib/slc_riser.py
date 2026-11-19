# -*- coding: utf-8 -*-
# slc_riser module - version v8
"""Shared pieces of the riser tools: the SLC address parameter names, the conduit connections between
elements, and the lookup table that says which symbol is drawn for each Family : Type.

The table is the user's own file, %APPDATA%\\pyRevit\\EWTestSuite\\riser_symbols.json. It is changed with the
SLC Riser - Config tool. Updates never overwrite it.

The drawing settings (view scale, device spacing, devices per line, label offset) are the user's own file,
%APPDATA%\\pyRevit\\EWTestSuite\\riser_settings.json, also changed with SLC Riser - Config."""
import os
import re
import json

from Autodesk.Revit.DB import (BuiltInCategory, BuiltInParameter, StorageType, Domain, ConnectorType,
                               FilteredElementCollector, FamilySymbol)

# Set this to a shared path (e.g. r"\\server\share\riser_symbols.json") so everyone uses one table.
# Leave as None for a per-user file in %APPDATA%.
TABLE_PATH = None
SETTINGS_PATH = None    # same idea, for the drawing settings (e.g. r"\\server\share\riser_settings.json")

LOCAL_DIR = os.path.join(os.getenv("APPDATA") or os.path.expanduser("~"), "pyRevit", "EWTestSuite")

# A device is on the SLC riser when at least one of these has a value: SLC Address, SLC Address 2 ... 24.
SLC_ADDRESS_COUNT = 24
SLC_ADDRESS_NAMES = ["SLC Address"] + ["SLC Address %d" % i for i in range(2, SLC_ADDRESS_COUNT + 1)]
_SLC_ORDER = dict((name.lower(), i) for i, name in enumerate(SLC_ADDRESS_NAMES))

# A written address: N1L2D015 = node 1, loop 2, detector 15 (M = module).
ADDRESS_PATTERN = re.compile(r"^N\s*(\d+)\s*L\s*(\d+)\s*([MD])\s*(\d+)$", re.IGNORECASE)

DEVICE_CATEGORIES = [BuiltInCategory.OST_FireAlarmDevices]
# Families that can be drawn in a drafting view.
SYMBOL_CATEGORIES = [BuiltInCategory.OST_GenericAnnotation, BuiltInCategory.OST_DetailComponents]


def table_path():
    return TABLE_PATH or os.path.join(LOCAL_DIR, "riser_symbols.json")


def settings_path():
    return SETTINGS_PATH or os.path.join(LOCAL_DIR, "riser_settings.json")


# ---------- Drawing settings ----------
# Drafting view scales offered in the config window: (label, scale number).
SCALES = [('1/16" = 1\'-0"', 192), ('3/32" = 1\'-0"', 128), ('1/8" = 1\'-0"', 96), ('3/16" = 1\'-0"', 64),
          ('1/4" = 1\'-0"', 48), ('3/8" = 1\'-0"', 32), ('1/2" = 1\'-0"', 24), ('3/4" = 1\'-0"', 16),
          ('1" = 1\'-0"', 12)]
DEFAULT_SETTINGS = {
    "view_scale": 96,           # 1/8" = 1'-0"
    "device_spacing_ft": 4.5,   # device centre to device centre, in feet in the view
    "devices_per_line": 5,      # devices on one line before the row wraps underneath
    "wrap_rounding": 0,         # a line only wraps when it would have more than devices_per_line + this
    "label_offset_in": 1.0,     # address text starts this many inches (in the view) below the riser line
}
SETTING_LIMITS = {              # (smallest, largest) allowed
    "view_scale": (1, 1000),
    "device_spacing_ft": (0.25, 100.0),
    "devices_per_line": (1, 200),
    "wrap_rounding": (0, 200),
    "label_offset_in": (0.0, 120.0),
}


def clean_settings(data):
    """DEFAULT_SETTINGS with every valid value from data in place of the default."""
    out = dict(DEFAULT_SETTINGS)
    for key, default in DEFAULT_SETTINGS.items():
        try:
            value = data.get(key)
            if value is None:
                continue
            value = int(value) if isinstance(default, int) else float(value)
            lo, hi = SETTING_LIMITS[key]
            if lo <= value <= hi:
                out[key] = value
        except Exception:
            pass
    return out


def load_settings():
    """The drawing settings, with the defaults for anything missing. Raises if the file can't be read."""
    path = settings_path()
    if not os.path.isfile(path):
        return dict(DEFAULT_SETTINGS)
    with open(path, "r") as f:
        return clean_settings(json.load(f))


def save_settings(settings):
    """Write the drawing settings, creating the folder if needed. Raises if they can't be written."""
    path = settings_path()
    folder = os.path.dirname(path)
    if folder and not os.path.isdir(folder):
        os.makedirs(folder)
    with open(path, "w") as f:
        json.dump(clean_settings(settings), f, indent=2, sort_keys=True)


# ---------- Address text ----------
def parse_address(text):
    """(node, loop, "M" or "D", number) for a written N#L#(M/D)# address, or None."""
    if not text:
        return None
    m = ADDRESS_PATTERN.match(text.strip())
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), m.group(3).upper(), int(m.group(4))


def loop_letter(n):
    """Loop number as a letter: 1 = A, 2 = B ... 26 = Z, 27 = AA, 28 = AB ..."""
    text = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        text = chr(ord("A") + r) + text
    return text or str(n)


def loop_label(address_lists):
    """'B' (L2), or 'A, B' for the loops found in those devices' addresses; '' if none can be read."""
    loops = set()
    for addresses in address_lists:
        for text in addresses:
            parsed = parse_address(text)
            if parsed:
                loops.add(parsed[1])
    return ", ".join(loop_letter(n) for n in sorted(loops))


# ---------- Revit helpers ----------
def eid_int(eid):
    """Integer value of an ElementId in any Revit version."""
    try:
        return eid.Value            # Revit 2024+
    except Exception:
        return eid.IntegerValue     # older Revit


def is_device(elem):
    try:
        cat = elem.Category
        if cat is None:
            return False
        cid = eid_int(cat.Id)
        return any(cid == int(c) for c in DEVICE_CATEGORIES)
    except Exception:
        return False


def type_name(etype):
    try:
        return etype.Name
    except Exception:
        p = etype.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM)
        return p.AsString() if p is not None else ""


def type_key(etype):
    """'Family : Type' of an element type."""
    return etype.FamilyName + " : " + type_name(etype)


def family_key(doc, el):
    """'Family : Type' of an element, the key used in the table."""
    try:
        return type_key(doc.GetElement(el.GetTypeId()))
    except Exception:
        return str(eid_int(el.GetTypeId()))


def slc_addresses(el):
    """The element's SLC addresses that have a value, in order: SLC Address, SLC Address 2, ... 24."""
    found = {}
    for p in el.Parameters:
        try:
            idx = _SLC_ORDER.get(p.Definition.Name.strip().lower())
            if idx is None or not p.HasValue:
                continue
            text = p.AsString() if p.StorageType == StorageType.String else p.AsValueString()
        except Exception:
            continue
        text = (text or "").strip()
        if text and idx not in found:
            found[idx] = text
    return [found[i] for i in sorted(found)]


# ---------- Conduit connections ----------
def conduit_connectors(el):
    """Conduit / cable tray connectors of a conduit, fitting or family instance, in a steady order."""
    cm = None
    try:
        cm = el.ConnectorManager                # conduit, cable tray
    except Exception:
        pass
    if cm is None:
        try:
            cm = el.MEPModel.ConnectorManager   # devices, fittings, boxes, panels
        except Exception:
            cm = None
    if cm is None:
        return []
    out = []
    for c in cm.Connectors:
        try:
            if c.Domain == Domain.DomainCableTrayConduit:
                out.append(c)
        except Exception:
            pass
    try:
        out.sort(key=lambda c: c.Id)
    except Exception:
        pass
    return out


def connected_elements(el):
    """One list per conduit connector of el: the elements physically joined to that connector."""
    groups = []
    own = eid_int(el.Id)
    for c in conduit_connectors(el):
        group = []
        try:
            if c.IsConnected:
                for r in c.AllRefs:
                    try:
                        if r.ConnectorType == ConnectorType.Logical:
                            continue
                        owner = r.Owner
                        if owner is not None and eid_int(owner.Id) != own:
                            group.append(owner)
                    except Exception:
                        pass
        except Exception:
            pass
        groups.append(group)
    return groups


# ---------- Symbols ----------
def available_symbols(doc):
    """{"Family : Type": FamilySymbol} for every loaded generic annotation and detail item type."""
    found = {}
    for cat in SYMBOL_CATEGORIES:
        for s in FilteredElementCollector(doc).OfCategory(cat).OfClass(FamilySymbol).ToElements():
            try:
                found[type_key(s)] = s
            except Exception:
                pass
    return found


# ---------- Lookup table ----------
RULE_OPS = ["<=", "<", "=", ">=", ">"]     # how a rule compares a device's number of addresses


def new_rule(op, count, symbols=None):
    """A rule: when the number of addresses <op> count, draw these symbols ([] = the type's default ones)."""
    return {"op": op, "count": int(count), "symbols": [s for s in (symbols or []) if s]}


def new_entry(symbols=None, rules=None):
    """A table entry: the default riser symbols for one Family : Type, in order, and the rules that pick other
    symbols by the number of addresses (checked top to bottom, the first that matches is used)."""
    return {"symbols": [s for s in (symbols or []) if s], "rules": list(rules or [])}


def _read_rules(value):
    rules = []
    for r in (value or []):
        try:
            if r.get("op") in RULE_OPS:
                rules.append(new_rule(r["op"], int(r.get("count")), [(s or "").strip() for s in r.get("symbols") or []]))
        except Exception:
            pass
    return rules


def load_table():
    """{"Family : Type" of a device: {"symbols": [default symbols, in order], "rules": [rule, ...]}}, each symbol
    a "Family : Type". Older tables with a single "symbol" are read as a one-symbol list. Raises if the file
    can't be read."""
    table = {}
    path = table_path()
    if not os.path.isfile(path):
        return table
    with open(path, "r") as f:
        data = json.load(f)
    for key, value in data.items():
        if isinstance(value, dict):
            symbols = value.get("symbols")
            if not isinstance(symbols, list):
                symbols = [value.get("symbol") or ""]
            table[key] = new_entry([(s or "").strip() for s in symbols], _read_rules(value.get("rules")))
        else:
            table[key] = new_entry([(value or "").strip()])
    return table


def save_table(table):
    """Write the table, creating the folder if needed. Raises if it can't be written."""
    path = table_path()
    folder = os.path.dirname(path)
    if folder and not os.path.isdir(folder):
        os.makedirs(folder)
    data = {}
    for key, entry in table.items():
        symbols = list(entry.get("symbols") or [])
        data[key] = {"symbols": symbols, "rules": list(entry.get("rules") or []),
                     "symbol": symbols[0] if symbols else ""}     # read by older versions
    with open(path, "w") as f:
        json.dump(data, f, indent=2, sort_keys=True)
