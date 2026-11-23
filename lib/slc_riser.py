# -*- coding: utf-8 -*-
# slc_riser module - version v16
# Change log (last change first):
#   v16 - SLC Riser v37: LoopKind.head_list_keywords / head_list_min_matches - the head end list shows panels
#         meeting 2 of 3: Head End in Family Defaults Config, a Panel # parameter, FACU / FACP / FAP / FAC in the
#         family name.
#   v15 - SLC Riser v35: LoopKind, the SLC loop kind SLC Riser now runs the riser engine (lib/riser_tool.py) with;
#         number_text (shared by the engine and Riser - Config); the unused LOCAL_DIR removed.
#   v14 - NAC Riser v1 / Riser - Config v8 (no change to SLC Riser): load_table, save_table, load_settings and
#         save_settings can be given another riser's file (NAC Riser's), so the risers share one copy of them.
#   v13 - Code consolidation step 7 (no tool change): paths, reading and the safe write come from config_store; a new
#         user starts from config/riser_symbols.default.json / riser_settings.default.json when added.
#   v12 - Code consolidation step 6 (SLC Riser v34): SLC addresses are read and parsed with
#         slc_addressing's reader and format, the same as the addressing tools (text parameters, any
#         SLC Address number); devices_on_loops reads with one reader.
"""Shared pieces of the riser tools: SLC Riser's loop kind for the riser engine (LoopKind), the SLC address parameter names, the conduit connections between
elements (from conduit_trace, shared with the addressing tools), and the lookup table that says which
symbol is drawn for each Family : Type.

The table is the user's own file, %APPDATA%\\pyRevit\\EWTestSuite\\riser_symbols.json. It is changed with the
SLC Riser tab of Riser - Config. Updates never overwrite it.

The drawing settings (view scale, device spacing, devices per line, label offset) are the user's own file,
%APPDATA%\\pyRevit\\EWTestSuite\\riser_settings.json, also changed on the SLC Riser tab of Riser - Config."""
from Autodesk.Revit.DB import BuiltInCategory, FilteredElementCollector, FamilySymbol

import conduit_trace as ct      # the shared conduit tracing (lib/conduit_trace.py)
import ew_common as ec        # shared helpers (lib/ew_common.py)
import slc_addressing as slc   # the SLC address reader and format, shared with the addressing tools
import config_store as cs     # where settings files live, office defaults, safe write (lib/config_store.py)

# Set this to a shared path (e.g. r"\\server\share\riser_symbols.json") so everyone uses one table.
# Leave as None for a per-user file in %APPDATA%.
TABLE_PATH = None
SETTINGS_PATH = None    # same idea, for the drawing settings (e.g. r"\\server\share\riser_settings.json")

# Office defaults: a user with no file yet starts from a copy of these, when they are in the repository.
DEFAULT_TABLE = cs.default_file("riser_symbols.default.json")
DEFAULT_SETTINGS_FILE = cs.default_file("riser_settings.default.json")

# A device is on the SLC riser when at least one of its SLC Address parameters (SLC Address, SLC Address 2,
# ...) has a value. They are read with slc_addressing's reader, the same one the addressing tools use.
SLC_ADDRESS_COUNT = 24     # only used in messages ('SLC Address 2 ... 24')
AddressParamReader = slc.AddressParamReader    # from slc_addressing

DEVICE_CATEGORIES = ec.DEVICE_CATEGORIES      # Fire Alarm Devices (lib/ew_common.py)
# Families that can be drawn in a drafting view.
SYMBOL_CATEGORIES = [BuiltInCategory.OST_GenericAnnotation, BuiltInCategory.OST_DetailComponents]


def table_path():
    return cs.user_file("riser_symbols.json", TABLE_PATH)


def settings_path():
    return cs.user_file("riser_settings.json", SETTINGS_PATH)


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


def load_settings(path=None, start_from=None):
    """The drawing settings, with the defaults for anything missing. Raises if the file can't be read.
    path / start_from: another riser's settings file and the office default it starts from (NAC Riser);
    SLC Riser's own by default."""
    if path is None:
        path = settings_path()
        start_from = None if SETTINGS_PATH else DEFAULT_SETTINGS_FILE
    if start_from:
        cs.start_from(path, [start_from])
    data = cs.read_json(path)
    return dict(DEFAULT_SETTINGS) if data is None else clean_settings(data)


def save_settings(settings, path=None):
    """Write the drawing settings (to path, or SLC Riser's file), creating the folder if needed. Raises if they
    can't be written."""
    cs.write_json(path or settings_path(), clean_settings(settings))


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


def load_table(path=None, start_from=None):
    """{"Family : Type" of a device: {"symbols": [default symbols, in order], "rules": [rule, ...]}}, each symbol
    a "Family : Type". Older tables with a single "symbol" are read as a one-symbol list. Raises if the file
    can't be read. path / start_from: another riser's table and its office default (NAC Riser); SLC Riser's
    own by default."""
    table = {}
    if path is None:
        path = table_path()
        start_from = None if TABLE_PATH else DEFAULT_TABLE
    if start_from:
        cs.start_from(path, [start_from])
    data = cs.read_json(path, {})
    for key, value in data.items():
        if isinstance(value, dict):
            symbols = value.get("symbols")
            if not isinstance(symbols, list):
                symbols = [value.get("symbol") or ""]
            table[key] = new_entry([(s or "").strip() for s in symbols], _read_rules(value.get("rules")))
        else:
            table[key] = new_entry([(value or "").strip()])
    return table


def save_table(table, path=None):
    """Write the table (to path, or SLC Riser's file), creating the folder if needed. Raises if it can't be
    written."""
    data = {}
    for key, entry in table.items():
        symbols = list(entry.get("symbols") or [])
        data[key] = {"symbols": symbols, "rules": list(entry.get("rules") or []),
                     "symbol": symbols[0] if symbols else ""}     # read by older versions
    cs.write_json(path or table_path(), data)


# ---------- Shared text ----------
def number_text(v):
    """4.5 -> '4.5', 6.0 -> '6' (the riser engine and Riser - Config)."""
    return ("%.4f" % v).rstrip("0").rstrip(".") if isinstance(v, float) else str(v)


# ---------- The SLC loop kind for the riser engine ----------
class LoopKind(object):
    """SLC loops for riser_tool.run(): the head end is the panel, each loop is one row labeled with its letter
    (L1 = A), and loop N lines up with the NEX2-DETAIL-RISER reference line / Loop Spacing N."""
    title = "SLC Riser"
    riser_name = "SLC Riser"            # LEVEL 1 - SLC RISER - FACU-01
    view_tag = "SLC RISER"
    config_name = "Riser - Config (SLC Riser tab)"
    run_word = "Loop"
    address_label = "SLC address"
    address_phrase = "an SLC address"
    head_prompt = "Select Head End Panel"
    head_example = "EX: FACU, NCP, APS, etc."
    # Select from List: a panel is listed when it meets this many of: Head End in Family Defaults Config, a Panel #
    # parameter, one of these words in its family name (case ignored).
    head_list_keywords = ["FACU", "FACP", "FAP", "FAC"]
    head_list_min_matches = 2
    no_address_hint = "have no value in SLC Address (or SLC Address 2 ... %d)" % SLC_ADDRESS_COUNT

    # Files: SLC Riser's own (riser_symbols.json / riser_settings.json).
    table_path = staticmethod(table_path)
    load_table = staticmethod(load_table)
    save_table = staticmethod(save_table)
    settings_path = staticmethod(settings_path)
    load_settings = staticmethod(load_settings)
    save_settings = staticmethod(save_settings)
    DEFAULT_SETTINGS = DEFAULT_SETTINGS
    SETTING_LIMITS = SETTING_LIMITS

    # Addresses.
    new_reader = staticmethod(AddressParamReader)       # reads each type's SLC Address parameters once
    addresses = staticmethod(slc_addresses)             # (el, reader)
    sort_key = staticmethod(address_sort_key)
    groups = staticmethod(address_loops)                # {(node, loop)}
    row_label = staticmethod(loop_label)                # 'B'

    @staticmethod
    def row_number(address_lists):
        """The loop number of a row when all its addresses agree on one, else None."""
        loops = set()
        for addresses in address_lists:
            for node, loop in address_loops(addresses):
                loops.add(loop)
        return loops.pop() if len(loops) == 1 else None

    @staticmethod
    def devices_on_groups(doc, groups):
        return devices_on_loops(doc, groups)
