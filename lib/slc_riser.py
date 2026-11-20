# -*- coding: utf-8 -*-
# slc_riser module - version v12
# Change log (last change first):
#   v12 - Code consolidation step 6 (SLC Riser v34): SLC addresses are read and parsed with
#         slc_addressing's reader and format, the same as the addressing tools (text parameters, any
#         SLC Address number); devices_on_loops reads with one reader.
#   v11 - Code consolidation step 3 (no change to SLC Riser): eid_int, is_device, type_name, type_key,
#         family_key and DEVICE_CATEGORIES come from ew_common.
#   v10 - Code consolidation step 2 (no change to SLC Riser): eid_int, conduit_connectors and
#         connected_elements now come from conduit_trace instead of a copy here.
#   v9 - SLC Riser v31: address_sort_key, address_loops and devices_on_loops (lowest address next at a
#        split, devices with no conduit path added and flagged).
#   v8 - SLC Riser v30 / Config v7: symbol rules by number of addresses.
"""Shared pieces of the riser tools: the SLC address parameter names, the conduit connections between
elements (from conduit_trace, shared with the addressing tools), and the lookup table that says which
symbol is drawn for each Family : Type.

The table is the user's own file, %APPDATA%\\pyRevit\\EWTestSuite\\riser_symbols.json. It is changed with the
SLC Riser - Config tool. Updates never overwrite it.

The drawing settings (view scale, device spacing, devices per line, label offset) are the user's own file,
%APPDATA%\\pyRevit\\EWTestSuite\\riser_settings.json, also changed with SLC Riser - Config."""
import os
import json

from Autodesk.Revit.DB import BuiltInCategory, FilteredElementCollector, FamilySymbol

import conduit_trace as ct      # the shared conduit tracing (lib/conduit_trace.py)
import ew_common as ec        # shared helpers (lib/ew_common.py)
import slc_addressing as slc   # the SLC address reader and format, shared with the addressing tools

# Set this to a shared path (e.g. r"\\server\share\riser_symbols.json") so everyone uses one table.
# Leave as None for a per-user file in %APPDATA%.
TABLE_PATH = None
SETTINGS_PATH = None    # same idea, for the drawing settings (e.g. r"\\server\share\riser_settings.json")

LOCAL_DIR = os.path.join(os.getenv("APPDATA") or os.path.expanduser("~"), "pyRevit", "EWTestSuite")

# A device is on the SLC riser when at least one of its SLC Address parameters (SLC Address, SLC Address 2,
# ...) has a value. They are read with slc_addressing's reader, the same one the addressing tools use.
SLC_ADDRESS_COUNT = 24     # only used in messages ('SLC Address 2 ... 24')
AddressParamReader = slc.AddressParamReader    # from slc_addressing

DEVICE_CATEGORIES = ec.DEVICE_CATEGORIES      # Fire Alarm Devices (lib/ew_common.py)
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
parse_address = slc.parse_address            # from slc_addressing: (node, loop, M/D, number) or None


def loop_letter(n):
    """Loop number as a letter: 1 = A, 2 = B ... 26 = Z, 27 = AA, 28 = AB ..."""
    text = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        text = chr(ord("A") + r) + text
    return text or str(n)


def address_sort_key(addresses):
    """Sort key for a device by its first readable SLC address: (node, loop, number, M/D). Devices without one
    sort last."""
    for text in addresses or []:
        parsed = parse_address(text)
        if parsed:
            node, loop, kind, number = parsed
            return (0, node, loop, number, kind)
    return (1, 0, 0, 0, "")


def address_loops(addresses):
    """{(node, loop)} named in these addresses."""
    found = set()
    for text in addresses or []:
        parsed = parse_address(text)
        if parsed:
            found.add((parsed[0], parsed[1]))
    return found


def devices_on_loops(doc, loops):
    """[(element, [SLC addresses])] of every Fire Alarm Device in the model with an address on one of these
    (node, loop) pairs, in address order."""
    found = []
    if not loops:
        return found
    reader = AddressParamReader()
    for cat in DEVICE_CATEGORIES:
        for el in FilteredElementCollector(doc).OfCategory(cat).WhereElementIsNotElementType().ToElements():
            try:
                addresses = slc_addresses(el, reader)
            except Exception:
                continue
            if addresses and address_loops(addresses) & loops:
                found.append((el, addresses))
    found.sort(key=lambda pair: address_sort_key(pair[1]))
    return found


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
eid_int = ec.eid_int            # from ew_common
is_device = ec.is_device        # from ew_common
type_name = ec.type_name        # from ew_common
type_key = ec.type_key          # from ew_common
family_key = ec.family_key      # from ew_common


def slc_addresses(el, reader=None):
    """The element's SLC addresses that have a value, in order: SLC Address, SLC Address 2, ...
    Pass one reader for a whole run (each type's parameters are then only looked up once)."""
    return slc.address_texts(reader or AddressParamReader(), el)


# ---------- Conduit connections ----------
# The conduit tracing is shared: these are conduit_trace's functions, the one copy every tool uses.
conduit_connectors = ct.conduit_connectors
connected_elements = ct.connected_elements


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
