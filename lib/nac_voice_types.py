# -*- coding: utf-8 -*-
# nac_voice_types module - version v3
"""Shared pieces of the NAC / Voice addressing tools: the parameter names, the address format and the
lookup table that says which Family : Type is NAC Only, Voice Only, or NAC and Voice.

The table is the user's own file, %APPDATA%\\pyRevit\\EWTestSuite\\nac_voice_types.json. It is changed with the
Address NAC / Voice - Config tool (or Shift+Click on Address NAC / Voice). Updates never overwrite it."""
import os
import re
import json

from Autodesk.Revit.DB import BuiltInCategory, StorageType

# Set this to a shared path (e.g. r"\\server\share\nac_voice_types.json") so everyone uses one table.
# Leave as None for a per-user file in %APPDATA%.
TABLE_PATH = None

LOCAL_DIR = os.path.join(os.getenv("APPDATA") or os.path.expanduser("~"), "pyRevit", "EWTestSuite")

# Categories the tools pick from and scan.
DEVICE_CATEGORIES = [BuiltInCategory.OST_FireAlarmDevices]

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
# Set a kind to None to leave its conduit alone.
CONDUIT_PARAM_NAMES = {"N": "Notification Circuit", "V": None}
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

NAC_ONLY = "NAC Only"
VOICE_ONLY = "Voice Only"
NAC_AND_VOICE = "NAC and Voice"
TYPE_LABELS = [NAC_ONLY, VOICE_ONLY, NAC_AND_VOICE]
TYPE_KINDS = {NAC_ONLY: ("N",), VOICE_ONLY: ("V",), NAC_AND_VOICE: ("N", "V")}
_ALIASES = {"N": NAC_ONLY, "NAC": NAC_ONLY, "V": VOICE_ONLY, "VOICE": VOICE_ONLY,
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


def label_for_kinds(kinds):
    """Device type that matches a set of kinds, or None if the set is empty."""
    if not kinds:
        return None
    if "N" in kinds and "V" in kinds:
        return NAC_AND_VOICE
    return NAC_ONLY if "N" in kinds else VOICE_ONLY


def family_key(doc, el):
    """'Family : Type' of an element, the key used in the table."""
    try:
        etype = doc.GetElement(el.GetTypeId())
        return etype.FamilyName + " : " + etype.Name
    except Exception:
        return str(eid_int(el.GetTypeId()))


# ---------- Lookup table ----------
def normalize_label(raw):
    """One of TYPE_LABELS for whatever is written in the file, or None if it isn't recognized."""
    if raw is None:
        return None
    return _ALIASES.get(str(raw).strip().upper())


def load_table():
    """{"Family : Type": "NAC Only" | "Voice Only" | "NAC and Voice"}. Raises if the file can't be read."""
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
