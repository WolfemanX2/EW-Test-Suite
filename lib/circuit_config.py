# -*- coding: utf-8 -*-
# circuit_config module - version v1
# Change log (last change first):
#   v1 - Auto Circuit - Config v1: one settings file for routing and addressing (mounting, Device Type, conduit
#        type, Address Group and rounding per family / type; Address Groups, rounding values and conduit
#        elevations), filled the first time from the Auto Conduit, Address SLC and Address NAC / Voice configs.
"""The Auto Circuit settings: one file, %APPDATA%\\pyRevit\\EWTestSuite\\circuit_config.json, edited with
Auto Circuit - Config.

Family Defaults (per family and per Family : Type; a type's own value wins, otherwise its family's):
    mounting       Wall / Ceiling
    device_type    NAC Only, Voice Only, NAC and Voice (Address NAC / Voice), Module, Detector (Address SLC),
                   Head End (connected, never addressed)
    conduit_type   the conduit type (its 'Family : Type' label) of runs leaving the device
    address_group  SLC: the name of an Address Group (that many addresses), CHOOSE_GROUP (choose one of the
                   groups when the device is addressed), or not set (asked how many)
    round_to       SLC: start the device on the next multiple of this number (one of the rounding values)
Address and Routing Defaults:
    address_groups [(name, number of addresses)]
    rounding       [numbers offered for round_to]
    elevations     {conduit type label: elevation text, e.g. 15'-0"}; a type without one is asked for

The first time (no file yet), it is filled from the configs it replaces: Auto Conduit - Config (mounting and
conduit type per family), Address SLC - Config (Module / Detector / Head End, counts, Address Options, rounding)
and Address NAC / Voice - Config (NAC / Voice / Head End). Those files are only read, never changed.
config/circuit_config.default.json, in the repository, is the office default: a user with none of these starts
from a copy of it."""
import os

import config_store as cs     # where settings files live, office defaults, safe write (lib/config_store.py)

CONFIG_PATH = None      # set to a shared path to make everyone use one file
DEFAULT_CONFIG = cs.default_file("circuit_config.default.json")

WALL, CEILING = "Wall", "Ceiling"
MOUNTINGS = [WALL, CEILING]
NAC_ONLY, VOICE_ONLY, NAC_AND_VOICE = "NAC Only", "Voice Only", "NAC and Voice"
MODULE, DETECTOR, HEAD_END = "Module", "Detector", "Head End"
DEVICE_TYPES = [NAC_ONLY, VOICE_ONLY, NAC_AND_VOICE, MODULE, DETECTOR, HEAD_END]
NAC_TYPES = [NAC_ONLY, VOICE_ONLY, NAC_AND_VOICE]
SLC_TYPES = [MODULE, DETECTOR]
CHOOSE_GROUP = "Choose a group"
MAX_ADDRESSES = 24
FIELDS = ["mounting", "device_type", "conduit_type", "address_group", "round_to"]

try:
    _TEXT = (str, unicode)      # IronPython 2
except NameError:
    _TEXT = (str,)


def config_path():
    return cs.user_file("circuit_config.json", CONFIG_PATH)


def empty():
    return {"families": {}, "types": {}, "address_groups": [], "rounding": [], "elevations": {}, "notes": []}


def family_of(key):
    """'Family : Type' -> 'Family'."""
    return key.split(" : ", 1)[0] if key else key


def setting(cfg, key, field, family=None):
    """A type's setting: its own value, else its family's, else None."""
    entry = cfg["types"].get(key) or {}
    value = entry.get(field)
    if value is not None:
        return value
    return (cfg["families"].get(family or family_of(key)) or {}).get(field)


def group_count(cfg, name):
    for group, count in cfg["address_groups"]:
        if group == name:
            return count
    return None


# ---------- Reading and writing ----------
def _positive_int(raw):
    try:
        number = int(float(u"%s" % raw)) if raw is not None and not isinstance(raw, bool) else None
    except ValueError:
        return None
    return number if number and number > 0 else None


def _text(raw):
    if raw is None:
        return None
    text = (u"%s" % raw).strip()
    return text or None


def _entry(raw):
    """One family or type entry, keeping only values that make sense."""
    out = {}
    if not isinstance(raw, dict):
        return out
    if raw.get("mounting") in MOUNTINGS:
        out["mounting"] = raw["mounting"]
    if raw.get("device_type") in DEVICE_TYPES:
        out["device_type"] = raw["device_type"]
    for field in ("conduit_type", "address_group"):
        value = _text(raw.get(field))
        if value:
            out[field] = value
    round_to = _positive_int(raw.get("round_to"))
    if round_to and round_to > 1:
        out["round_to"] = round_to
    return out


def normalize(data):
    """A config from whatever was in the file (missing parts are empty)."""
    cfg = empty()
    if not isinstance(data, dict):
        return cfg
    for part in ("families", "types"):
        for key, raw in (data.get(part) or {}).items():
            entry = _entry(raw)
            if entry:
                cfg[part][key] = entry
    seen = set()
    for raw in data.get("address_groups") or []:
        if isinstance(raw, dict):
            name, count = _text(raw.get("name")), _positive_int(raw.get("count"))
            if name and count and count <= MAX_ADDRESSES and name not in seen and name != CHOOSE_GROUP:
                seen.add(name)
                cfg["address_groups"].append((name, count))
    cfg["rounding"] = sorted(set(v for v in (_positive_int(r) for r in data.get("rounding") or []) if v and v > 1))
    for label, text in (data.get("elevations") or {}).items():
        text = _text(text)
        if text:
            cfg["elevations"][label] = text
    cfg["notes"] = [u"%s" % n for n in data.get("notes") or [] if isinstance(n, _TEXT)]
    return cfg


def to_data(cfg):
    return {"families": cfg["families"], "types": cfg["types"],
            "address_groups": [{"name": n, "count": c} for n, c in cfg["address_groups"]],
            "rounding": list(cfg["rounding"]), "elevations": cfg["elevations"], "notes": list(cfg["notes"])}


def read(path):
    """The config in a file; a missing file is an empty config, an unreadable one raises."""
    return normalize(cs.read_json(path, {}))


def write(path, cfg):
    cs.write_json(path, to_data(cfg))


def load():
    """The user's config. The first time, it is filled from the old configs (or the office default) and saved.
    Raises if the file can't be read, so a broken file is never mistaken for 'no settings' and overwritten."""
    path = config_path()
    if not os.path.isfile(path):
        cfg = from_old_configs()
        if cfg is None and os.path.isfile(DEFAULT_CONFIG):
            try:
                cfg = read(DEFAULT_CONFIG)
            except Exception:
                cfg = None      # a bad default must not stop the tools
        cfg = cfg or empty()
        try:
            write(path, cfg)
        except Exception:
            pass
        return cfg
    return read(path)


def save(cfg):
    write(config_path(), cfg)


# ---------- The first time: from the configs this one replaces ----------
_OLD_SLC_KINDS = {"M": MODULE, "D": DETECTOR, "H": HEAD_END}


def _count_group(cfg, count):
    """The name of a group with that many addresses, made if there is none."""
    for name, c in cfg["address_groups"]:
        if c == count:
            return name
    name = "1 Address" if count == 1 else "%d Addresses" % count
    cfg["address_groups"].append((name, count))
    return name


def _named_group(cfg, label, count):
    for name, c in cfg["address_groups"]:
        if name == label:
            if c == count:
                return name
            label = "%s (%d)" % (label, count)
            return _named_group(cfg, label, count)
    cfg["address_groups"].append((label, count))
    return label


def from_old_configs():
    """A config filled from the Auto Conduit, Address SLC and Address NAC / Voice config files, or None if there
    are none. Their files are only read."""
    import mounting_rules
    import slc_addressing as slc
    import nac_voice_types as nv
    cfg, found = empty(), False
    notes = []

    # Auto Conduit - Config: mounting and conduit type, per family
    try:
        if os.path.isfile(mounting_rules.rules_path()) or os.path.isfile(mounting_rules.OLD_LOCAL):
            for family, rule in mounting_rules.load_rules().items():
                entry = _entry({"mounting": rule.get(mounting_rules.KEY_MOUNT),
                                "conduit_type": rule.get(mounting_rules.KEY_TYPE)})
                if entry:
                    cfg["families"][family] = entry
                    found = True
    except Exception as ex:
        notes.append(u"Auto Conduit - Config could not be read: %s" % ex)

    # Address SLC - Config: Device Type, addresses and rounding, per type
    try:
        if os.path.isfile(slc.table_path()):
            for key, rule in slc.read_table(slc.table_path()).items():
                entry = cfg["types"].setdefault(key, {})
                entry["device_type"] = _OLD_SLC_KINDS.get(rule["kind"], MODULE)
                if entry["device_type"] != HEAD_END:
                    if rule["count"]:
                        entry["address_group"] = _count_group(cfg, rule["count"])
                    elif rule["options"]:
                        names = [_named_group(cfg, label, count) for label, count in rule["options"]]
                        entry["address_group"] = names[0] if len(names) == 1 else CHOOSE_GROUP
                        if len(names) > 1:
                            notes.append(u"%s had the Address Options %s: it now chooses from all Address Groups."
                                         % (key, ", ".join(names)))
                    if rule["round_to"] and rule["round_to"] > 1:
                        entry["round_to"] = rule["round_to"]
                        if rule["round_to"] not in cfg["rounding"]:
                            cfg["rounding"].append(rule["round_to"])
                found = True
    except Exception as ex:
        notes.append(u"Address SLC - Config could not be read: %s" % ex)

    # Address NAC / Voice - Config: NAC / Voice / Head End, per type
    try:
        if os.path.isfile(nv.table_path()):
            for key, label in nv.load_table().items():
                entry = cfg["types"].setdefault(key, {})
                had = entry.get("device_type")
                if had in SLC_TYPES and label != nv.HEAD_END:
                    notes.append(u"%s was a %s in Address SLC - Config and %s in Address NAC / Voice - Config: "
                                 u"kept as %s." % (key, had, label, had))
                    continue
                if had == HEAD_END and label != nv.HEAD_END:
                    entry.pop("address_group", None)
                entry["device_type"] = label if label in DEVICE_TYPES else HEAD_END
                found = True
    except Exception as ex:
        notes.append(u"Address NAC / Voice - Config could not be read: %s" % ex)

    if not found and not notes:
        return None
    cfg["rounding"] = sorted(cfg["rounding"])
    cfg["notes"] = [u"Filled from your Auto Conduit, Address SLC and Address NAC / Voice configs."] + notes
    return cfg
