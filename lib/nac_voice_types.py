# -*- coding: utf-8 -*-
# nac_voice_types module - version v8
# Change log (last change first):
#   v8 - Address NAC v4 / Address Voice v4 / Auto-Circuit v8 / Address NAC / Voice - Config v4: Head End
#        device type (never addressed) and type_options().
#   v7 - Code consolidation step 3 (no tool change): eid_int, is_device, family_key and DEVICE_CATEGORIES come
#        from ew_common.
#   v6 - Address NAC v1 / Address Voice v1: Address NAC / Voice split into two tools.
#   v5 - Address NAC / Voice v7: EOL current and voltage estimate in Comments.
#   v4 - Address NAC / Voice v5: Voice circuits in Notification Circuit too.
"""Shared pieces of the NAC / Voice addressing tools: the parameter names, the address format and the
lookup table that says which Family : Type is NAC Only, Voice Only, or NAC and Voice.

The table is the user's own file, %APPDATA%\\pyRevit\\EWTestSuite\\nac_voice_types.json. It is changed with the
Address NAC / Voice - Config tool (or Shift+Click on Address NAC / Voice). Updates never overwrite it."""
import os
import re
import json

from Autodesk.Revit.DB import StorageType
import ew_common as ec        # shared helpers (lib/ew_common.py)

# Set this to a shared path (e.g. r"\\server\share\nac_voice_types.json") so everyone uses one table.
# Leave as None for a per-user file in %APPDATA%.
TABLE_PATH = None

LOCAL_DIR = os.path.join(os.getenv("APPDATA") or os.path.expanduser("~"), "pyRevit", "EWTestSuite")

# Categories the tools pick from and scan.
DEVICE_CATEGORIES = ec.DEVICE_CATEGORIES      # Fire Alarm Devices (lib/ew_common.py)

# Kind codes: "N" = NAC, "V" = Voice. The code is also the letter the address starts with.
KINDS = ["N", "V"]
KIND_NAMES = {"N": "NAC", "V": "Voice"}
SOURCE_NAMES = {"N": "power supply", "V": "power supply / amplifier"}    # what #1 is called in the prompts
PARAM_NAMES = {
    "N": {"address": "NAC Address", "circuit": "NAC Circuit"},
    "V": {"address": "Voice Address", "circuit": "Voice Circuit"},
}
# Yes/No parameter on the device: Yes on the last device of its circuit, No on every other device of the circuit.
EOL_PARAM_NAMES = {"N": "NAC EOL", "V": "Voice EOL"}
# Text parameter on the conduit between the devices of a downstream run: N12 = power supply 1, circuit 2.
# A conduit carrying both holds both, NAC first, separated by a comma: N16,V16.
# Set a kind to None to leave its conduit alone.
CONDUIT_PARAM_NAMES = {"N": "Notification Circuit", "V": "Notification Circuit"}
# Circuit numbers offered when starting a new circuit.
CIRCUIT_RANGES = {"N": range(1, 7), "V": range(1, 9)}

# A written address: N2-3.14 = power supply 2, circuit 3, 14th device on the circuit.
VALUE_PATTERNS = {
    "N": re.compile(r"^N(\d+)-(\d+)\.(\d+)$", re.IGNORECASE),
    "V": re.compile(r"^V(\d+)-(\d+)\.(\d+)$", re.IGNORECASE),
}

# Device load, used by 'Max current' when addressing downstream. The first of these names found on the device
# (instance first, then its type) is read. A number or electrical current parameter is in amps; a text value
# such as "0.115 A" or "115 mA" is read too.
CURRENT_PARAM_NAMES = ["Current"]
DEFAULT_MAX_CURRENT = 1.2   # amps

# EOL estimate written to the Comments of the last NAC device: total circuit current and the voltage left at the
# end of the line, point to point. Each conduit segment carries the current of every device past it, through
# two conductors (out and back). Conduit length only: no allowance for fittings, boxes or slack.
SOURCE_VOLTS = 20.4             # 24 V battery at end of discharge
WIRE_OHMS_PER_1000FT = 3.07     # 14 AWG
EOL_COMMENT_KINDS = ("N",)      # Voice circuits get no estimate
MIN_DEVICE_VOLTS = 17.25         # warn when the estimate is below this
_COMMENT_PATTERN = re.compile(r"^\s*\d+(\.\d+)?\s*A(\s*,\s*EOL\s+-?\d+(\.\d+)?\s*V)?\s*$", re.IGNORECASE)


def fmt_eol_comment(amps, volts):
    """1.150 A, EOL 19.82 V  (or just the amps when the voltage couldn't be worked out)."""
    text = "%.3f A" % amps
    if volts is not None:
        text += ", EOL %.2f V" % volts
    return text


def is_eol_comment(text):
    """True for a comment this tool wrote (safe to clear when the device is no longer the EOL)."""
    return bool(text) and bool(_COMMENT_PATTERN.match(text))


def conduit_tokens(text):
    """'N12,V16' -> ['N12', 'V16']"""
    return [x.strip().upper() for x in (text or "").split(",") if x.strip()]


NAC_ONLY = "NAC Only"
VOICE_ONLY = "Voice Only"
NAC_AND_VOICE = "NAC and Voice"
HEAD_END = "Head End"     # the panel, power supplies and other head-end equipment: never addressed
TYPE_LABELS = [NAC_ONLY, VOICE_ONLY, NAC_AND_VOICE, HEAD_END]
TYPE_KINDS = {NAC_ONLY: ("N",), VOICE_ONLY: ("V",), NAC_AND_VOICE: ("N", "V"), HEAD_END: ()}
_ALIASES = {"N": NAC_ONLY, "NAC": NAC_ONLY, "V": VOICE_ONLY, "VOICE": VOICE_ONLY,
            "H": HEAD_END, "HEAD END": HEAD_END, "HEADEND": HEAD_END,
            "NV": NAC_AND_VOICE, "BOTH": NAC_AND_VOICE, "NAC AND VOICE": NAC_AND_VOICE,
            "NAC ONLY": NAC_ONLY, "VOICE ONLY": VOICE_ONLY}


def table_path():
    return TABLE_PATH or os.path.join(LOCAL_DIR, "nac_voice_types.json")


# ---------- Address text ----------
def fmt_circuit(kind, source, circuit):
    """N2-3"""
    return "%s%d-%d" % (kind, source, circuit)


def fmt_conduit(kind, source, circuit):
    """N12 - written on the conduit of a downstream run."""
    return "%s%d%d" % (kind, source, circuit)


def merge_conduit_value(current, kind, text):
    """The conduit's value with this kind's circuit replaced by text, keeping the other kind's:
    ("N16", "V", "V16") -> "N16,V16"; ("N15,V16", "N", "N12") -> "N12,V16"."""
    parts = [x.strip() for x in (current or "").split(",") if x.strip()]
    others = [x for x in parts if x[:1].upper() != kind]
    ordered = [x for k in KINDS for x in ([text] if k == kind else [o for o in others if o[:1].upper() == k])]
    return ",".join(ordered + [o for o in others if o[:1].upper() not in KINDS])


def fmt_address(kind, source, circuit, num):
    """N2-3.14"""
    return "%s.%d" % (fmt_circuit(kind, source, circuit), num)


def parse_address(kind, text):
    """(source, circuit, number) for a written address of that kind, or None."""
    if not text:
        return None
    m = VALUE_PATTERNS[kind].match(text.strip())
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


# ---------- Revit helpers ----------
eid_int = ec.eid_int            # from ew_common
is_device = ec.is_device        # from ew_common


def get_param(el, name):
    """The text parameter with that name (case ignored), or None. Prefers one that can be written."""
    wanted = name.strip().lower()
    found = None
    for p in el.Parameters:
        try:
            if p.Definition.Name.strip().lower() != wanted or p.StorageType != StorageType.String:
                continue
        except Exception:
            continue
        if not p.IsReadOnly:
            return p
        if found is None:
            found = p
    return found


def get_yes_no(el, name):
    """The writable Yes/No parameter with that name (case ignored), or None."""
    wanted = name.strip().lower()
    for p in el.Parameters:
        try:
            if p.Definition.Name.strip().lower() == wanted and p.StorageType == StorageType.Integer \
                    and not p.IsReadOnly:
                return p
        except Exception:
            continue
    return None


_NUMBER = re.compile(r"([0-9]*\.?[0-9]+)\s*(m?A)?", re.IGNORECASE)


def _param_amps(p):
    """Amps held by a parameter, or None if it is empty or not a number."""
    try:
        if not p.HasValue:
            return None
    except Exception:
        pass
    st = p.StorageType
    if st == StorageType.Double:
        return p.AsDouble()     # electrical current is stored in amps
    if st == StorageType.Integer:
        return float(p.AsInteger())
    if st == StorageType.String:
        m = _NUMBER.search(p.AsString() or "")
        if not m:
            return None
        value = float(m.group(1))
        if m.group(2) and m.group(2).lower() == "ma":
            value /= 1000.0
        return value
    return None


def get_current(doc, el):
    """The device's Current in amps, or None if it has no Current parameter or no value."""
    owners = [el]
    try:
        etype = doc.GetElement(el.GetTypeId())
        if etype is not None:
            owners.append(etype)
    except Exception:
        pass
    for owner in owners:
        for name in CURRENT_PARAM_NAMES:
            wanted = name.strip().lower()
            for p in owner.Parameters:
                try:
                    if p.Definition.Name.strip().lower() != wanted:
                        continue
                    amps = _param_amps(p)
                except Exception:
                    continue
                if amps is not None:
                    return amps
    return None


def fmt_amps(amps):
    return "%.3f A" % amps


def kinds_on_element(el):
    """Set of kinds ("N", "V") whose Address parameter the element has and can be written."""
    kinds = set()
    for kind in KINDS:
        p = get_param(el, PARAM_NAMES[kind]["address"])
        if p is not None and not p.IsReadOnly:
            kinds.add(kind)
    return kinds


def type_options(available):
    """Device types to offer for a device not in the table, given the kinds it can take: the ones it has the
    parameters for, plus Head End. Empty if it takes neither kind."""
    if not available:
        return []
    return [t for t in TYPE_LABELS if all(k in available for k in TYPE_KINDS[t])]


def label_for_kinds(kinds):
    """Device type that matches a set of kinds, or None if the set is empty."""
    if not kinds:
        return None
    if "N" in kinds and "V" in kinds:
        return NAC_AND_VOICE
    return NAC_ONLY if "N" in kinds else VOICE_ONLY


family_key = ec.family_key      # from ew_common


# ---------- Lookup table ----------
def normalize_label(raw):
    """One of TYPE_LABELS for whatever is written in the file, or None if it isn't recognized."""
    if raw is None:
        return None
    return _ALIASES.get(str(raw).strip().upper())


def load_table():
    """{"Family : Type": "NAC Only" | "Voice Only" | "NAC and Voice" | "Head End"}. Raises if the file can't be read."""
    table = {}
    path = table_path()
    if not os.path.isfile(path):
        return table
    with open(path, "r") as f:
        data = json.load(f)
    for key, value in data.items():
        if isinstance(value, dict):
            value = value.get("type")
        label = normalize_label(value)
        if label:
            table[key] = label
    return table


def save_table(table):
    """Write the table, creating the folder if needed. Raises if it can't be written."""
    path = table_path()
    folder = os.path.dirname(path)
    if folder and not os.path.isdir(folder):
        os.makedirs(folder)
    data = dict((key, {"type": label}) for key, label in table.items())
    with open(path, "w") as f:
        json.dump(data, f, indent=2, sort_keys=True)
