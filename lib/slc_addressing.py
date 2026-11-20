# -*- coding: utf-8 -*-
# slc_addressing module - version v4
# Change log (last change first):
#   v4 - Code consolidation step 3 (no tool change): eid_int, is_device, family_key and DEVICE_CATEGORY come from
#        ew_common.
#   v3 - Code consolidation step 2 (Address SLC v6): eid_int, conduit_connectors, connected_elements,
#        element_type_name and trace_downstream now come from conduit_trace (one copy, with SLC Riser's
#        tee rule) instead of a copy here.
#   v2 - Address SLC v2: follow conduit downstream (the tracing functions); Tool Configs rename.
#   v1 - Address Devices v1 + Addressing Config v1: SLC addressing tools as pyRevit scripts.
"""Shared pieces of the SLC addressing tools (Address SLC, Address SLC - Config): the parameter names, the
address format, the rules table and the default config.

Addresses are written N#L#M000 for modules and N#L#D000 for detectors, into the text parameters
"SLC Address" (position 1), "SLC Address 2" ... "SLC Address 24".

The rules table is the user's own file, %APPDATA%\\MyTools\\AddressCounts.json - the same file, in the same
format, as the standalone Address Devices add-in, so the two can be used side by side. It is changed with the
Address SLC - Config tool (or Shift+Click on Address SLC). Updates never overwrite it.

config/address_config.default.json, in the repository, is the office default. If it holds rules, a user who has
no table yet starts from a copy of it, and 'Load Default Config' in Address SLC - Config opens at it. The tools
only ever read a default file."""
import os
import re
import json
import shutil

from Autodesk.Revit.DB import StorageType, FilteredElementCollector

import conduit_trace as ct      # the shared conduit tracing (lib/conduit_trace.py)
import ew_common as ec        # shared helpers (lib/ew_common.py)

# Set this to a shared path (e.g. r"\\server\share\AddressCounts.json") so everyone edits one table.
# Leave as None for a per-user file in %APPDATA% (recommended together with a default config).
TABLE_PATH = None

EXTENSION_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_CONFIG = os.path.join(EXTENSION_DIR, "config", "address_config.default.json")
LOCAL_DIR = os.path.join(os.getenv("APPDATA") or os.path.expanduser("~"), "MyTools")
REMEMBERED_DEFAULT = os.path.join(LOCAL_DIR, "DefaultConfigPath.txt")   # last default file the user loaded

DEVICE_CATEGORY = ec.DEVICE_CATEGORIES[0]     # Fire Alarm Devices (lib/ew_common.py)

PAD = 3                 # digits in the number part (000)
MAX_NUMBER = 999        # highest number that fits in PAD digits
MAX_ADDRESSES = 24      # "SLC Address" (1) through "SLC Address 24"

# Kind codes: the letter written in the address. Each kind is numbered separately within a loop.
MODULE = "M"
DETECTOR = "D"
KINDS = [MODULE, DETECTOR]
KIND_NAMES = {MODULE: "Module", DETECTOR: "Detector"}
KIND_LABELS = {MODULE: "Module (M)", DETECTOR: "Detector (D)"}

PARAM_NAME = re.compile(r"^SLC\s*Address\s*([0-9]*)$", re.IGNORECASE)
ADDRESS_VALUE = re.compile(r"^N([0-9]+)L([0-9]+)([MD])([0-9]+)$", re.IGNORECASE)

OPTIONS_EXAMPLE = '"Single Zone":6, "Dual Zone":12'
_QUOTES = (u'"', u"\u201c", u"\u201d")


def table_path():
    return TABLE_PATH or os.path.join(LOCAL_DIR, "AddressCounts.json")


# ---------- Address text ----------
def parse_kind(text):
    """"D", "d", "Detector" and the older "Device" -> DETECTOR; anything else -> MODULE."""
    text = (u"%s" % (text if text is not None else u"")).strip()
    return DETECTOR if text[:1].upper() == "D" else MODULE


def param_position(name):
    """Position of an SLC Address parameter name (1 = "SLC Address"), or None if it isn't one."""
    if not name:
        return None
    m = PARAM_NAME.match(name)
    if not m:
        return None
    return int(m.group(1)) if m.group(1) else 1


def parse_address(value):
    """(n, l, kind, number) for a written address such as N2L3M097, or None."""
    if not value:
        return None
    m = ADDRESS_VALUE.match(value.strip())
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), parse_kind(m.group(3)), int(m.group(4))


def fmt_number(number):
    """7 -> "007\""""
    return str(number).zfill(PAD)


def fmt_address(prefix, kind, number):
    """("N1L2", "M", 7) -> "N1L2M007\""""
    return "%s%s%s" % (prefix, kind, fmt_number(number))


def round_up(number, step):
    """Next multiple of step (unchanged if already one)."""
    return ((number + step - 1) // step) * step


# ---------- Revit helpers ----------
eid_int = ec.eid_int            # from ew_common
is_device = ec.is_device        # from ew_common


def device_instances(doc):
    return FilteredElementCollector(doc).OfCategory(DEVICE_CATEGORY).WhereElementIsNotElementType()


def device_types(doc):
    return FilteredElementCollector(doc).OfCategory(DEVICE_CATEGORY).WhereElementIsElementType()


family_key = ec.family_key      # from ew_common


class AddressParamReader(object):
    """Reads the SLC Address parameters of devices.
    The first device of each type is scanned in full (every parameter name is tested); the matching parameter
    definitions are then remembered for that type, so every further device of the type is a handful of direct
    lookups. This keeps the whole-project scan fast."""

    def __init__(self):
        self._by_type = {}      # type id -> [(position, Definition)]

    def get(self, el):
        """[(position, Parameter)] sorted by position."""
        try:
            tid = eid_int(el.GetTypeId())
        except Exception:
            tid = -1
        known = self._by_type.get(tid) if tid > 0 else None
        if known is not None:
            found = []
            for pos, definition in known:
                try:
                    p = el.get_Parameter(definition)
                except Exception:
                    p = None
                if p is not None:
                    found.append((pos, p))
            return found

        found = []
        for p in el.Parameters:
            try:
                if p.StorageType != StorageType.String:
                    continue
                pos = param_position(p.Definition.Name)
                if pos is not None:
                    found.append((pos, p))
            except Exception:
                pass    # a parameter that cannot be inspected is not an address parameter
        found.sort(key=lambda item: item[0])
        if tid > 0:
            self._by_type[tid] = [(pos, p.Definition) for pos, p in found]
        return found


def scan_loops(doc, reader):
    """Loops already written in the model: [{"n", "l", "last": {"M": highest or None, "D": ...}}], sorted."""
    loops = {}
    for el in device_instances(doc):
        for _pos, p in reader.get(el):
            try:
                parsed = parse_address(p.AsString())
            except Exception:
                parsed = None
            if not parsed:
                continue
            n, l, kind, number = parsed
            loop = loops.setdefault((n, l), {"n": n, "l": l, "last": {MODULE: None, DETECTOR: None}})
            if loop["last"][kind] is None or number > loop["last"][kind]:
                loop["last"][kind] = number
    return [loops[key] for key in sorted(loops)]


def loop_label(loop):
    parts = ["last %s%s" % (k, fmt_number(loop["last"][k])) for k in KINDS if loop["last"][k] is not None]
    return "Continue Addressing N%dL%d (%s)" % (loop["n"], loop["l"], ", ".join(parts))


# ---------- Conduit connections ----------
# The conduit tracing is shared: these are conduit_trace's functions, the one copy every tool uses.
conduit_connectors = ct.conduit_connectors
connected_elements = ct.connected_elements
element_type_name = ct.element_type_name
trace_downstream = ct.trace_downstream


# ---------- Address Options: "Single Zone":6, "Dual Zone":12 ----------
def option_display(label, count):
    """Text shown when choosing, e.g. "Dual Zone (12)"."""
    return str(count) if label == str(count) else "%s (%d)" % (label, count)


def format_options(options):
    """[(label, count)] -> the text typed in Address SLC - Config."""
    return ", ".join('"%s":%d' % (label, count) for label, count in options or [])


def parse_options(text):
    """Reads the typed text. Returns ([(label, count)], None) or (None, error message).
    Blank text is valid and gives no options. Quotes around a label are optional when the label has no comma
    or colon; curly quotes are accepted. A bare number (6) is an option labelled with that number."""
    text = text or u""
    options, seen = [], set()
    i, n = 0, len(text)
    while True:
        while i < n and text[i].isspace():
            i += 1
        if i >= n:
            break

        quoted = text[i] in _QUOTES
        if quoted:
            i += 1
            start = i
            while i < n and text[i] not in _QUOTES:
                i += 1
            if i >= n:
                return None, "a label is missing its closing quote."
            label = text[start:i].strip()
            i += 1
        else:
            start = i
            while i < n and text[i] not in ":,;":
                i += 1
            label = text[start:i].strip()

        while i < n and text[i].isspace():
            i += 1
        if i < n and text[i] == ":":
            i += 1
            start = i
            while i < n and text[i] not in ",;":
                i += 1
            value = text[start:i].strip()
        elif not quoted:
            value = label   # a bare number
        else:
            return None, '"%s" needs a colon and a number after it, like %s.' % (label, OPTIONS_EXAMPLE)

        if not label:
            return None, "an option has no label. Write them like %s." % OPTIONS_EXAMPLE
        if not value.isdigit():
            return None, '"%s" needs a whole number after the colon, like %s.' % (label, OPTIONS_EXAMPLE)
        count = int(value)
        if count < 1 or count > MAX_ADDRESSES:
            return None, '"%s": the number of addresses must be from 1 to %d.' % (label, MAX_ADDRESSES)
        if label.lower() in seen:
            return None, 'the label "%s" is used more than once.' % label
        seen.add(label.lower())
        options.append((label, count))

        while i < n and text[i].isspace():
            i += 1
        if i >= n:
            break
        if text[i] in ",;":
            i += 1
            continue
        return None, "put a comma between options, like %s." % OPTIONS_EXAMPLE
    return options, None


# ---------- Rules table ----------
def new_rule(kind=MODULE, count=None, options=None, round_to=None):
    """One Family : Type rule.
    kind      MODULE or DETECTOR
    count     fixed number of addresses (never prompts); None = ask each time
    options   [(label, count)] named choices offered when the device is picked; [] = not used
    round_to  round the counter up to the next multiple of this before addressing (M004 -> M005)"""
    return {"kind": kind, "count": count, "options": list(options or []), "round_to": round_to}


try:
    _NUMBER_TYPES = (int, long, float)      # IronPython 2
except NameError:
    _NUMBER_TYPES = (int, float)


def _positive_int(raw):
    """Blank, None, 0 and negative values mean "not set"."""
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, _NUMBER_TYPES):
        number = raw
    else:
        text = (u"%s" % raw).strip()
        if not text:
            return None
        try:
            number = float(text)
        except ValueError:
            raise ValueError('"%s" is not a number.' % text)
    if number != number or number < 1:
        return None
    return int(number)


def _read_options(raw):
    """"options" is a list of {"label": ..., "count": ...}; a plain {"label": count} object is accepted too."""
    pairs = []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                pairs.append((item.get("label"), item.get("count")))
    elif isinstance(raw, dict):
        pairs = list(raw.items())
    options = []
    for label, count in pairs:
        count = _positive_int(count)
        if count is None or count > MAX_ADDRESSES:
            continue
        label = (u"%s" % (label if label is not None else u"")).strip() or str(count)
        options.append((label, count))
    return options


def read_table(path):
    """{"Family : Type": rule} from a file. A missing or empty file is an empty table; an unreadable one raises,
    so a broken file is never mistaken for "no rules" and overwritten.
    Older files are accepted: "multiple_of" / "zone_size" N becomes the options N, 2N, 3N ..., and the oldest
    format, a plain integer, is a Module with that count."""
    table = {}
    if not os.path.isfile(path):
        return table
    with open(path, "r") as f:
        text = f.read()
    if not text.strip():
        return table
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError('The file does not contain a table of "Family : Type" entries.')
    for key, value in data.items():
        try:
            if isinstance(value, dict):
                rule = new_rule(parse_kind(value.get("type")), _positive_int(value.get("count")),
                                _read_options(value.get("options")), _positive_int(value.get("round_to")))
                if not rule["options"]:
                    step = _positive_int(value.get("multiple_of")) or _positive_int(value.get("zone_size"))
                    if step:
                        rule["options"] = [(str(v), v) for v in range(step, MAX_ADDRESSES + 1, step)]
            else:
                rule = new_rule(MODULE, _positive_int(value))
        except ValueError as ex:
            raise ValueError('Entry "%s": %s' % (key, ex))
        table[key] = rule
    return table


def write_table(path, table):
    """Write a table, creating the folder if needed. Raises if it can't be written."""
    folder = os.path.dirname(path)
    if folder and not os.path.isdir(folder):
        os.makedirs(folder)
    data = {}
    for key, rule in table.items():
        data[key] = {"count": rule["count"],
                     "options": [{"label": label, "count": count} for label, count in rule["options"]],
                     "round_to": rule["round_to"],
                     "type": rule["kind"]}
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2, sort_keys=True)
    if os.path.exists(path):
        os.remove(path)
    os.rename(tmp, path)


def load_table():
    """The user's table. The first time, when there is no table yet and the repository default holds rules,
    the table is created as a copy of the default. Raises if the file can't be read."""
    path = table_path()
    if not os.path.isfile(path) and not TABLE_PATH and os.path.isfile(DEFAULT_CONFIG):
        try:
            default = read_table(DEFAULT_CONFIG)
            if default:
                write_table(path, default)
        except Exception:
            pass    # a bad default must not stop the tools; the table just starts empty
    return read_table(path)


def save_table(table):
    write_table(table_path(), table)


# ---------- Default config ----------
def same_path(a, b):
    try:
        return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))
    except Exception:
        return a == b


def last_default_path():
    """Where 'Load Default Config' looks first: the last default this user loaded, else the repository's."""
    try:
        if os.path.isfile(REMEMBERED_DEFAULT):
            with open(REMEMBERED_DEFAULT, "r") as f:
                for line in f:
                    line = line.strip().strip('"')
                    if line and not line.startswith("#"):
                        return os.path.expandvars(line)
    except Exception:
        pass
    return DEFAULT_CONFIG if os.path.isfile(DEFAULT_CONFIG) else None


def remember_default_path(path):
    try:
        if not os.path.isdir(LOCAL_DIR):
            os.makedirs(LOCAL_DIR)
        with open(REMEMBERED_DEFAULT, "w") as f:
            f.write(path + "\n")
    except Exception:
        pass    # remembering the folder is only a convenience


def backup_table():
    """Copies the user's table to "AddressCounts.backup.json" before it is replaced."""
    path = table_path()
    if os.path.isfile(path):
        base, ext = os.path.splitext(path)
        shutil.copyfile(path, base + ".backup" + ext)
