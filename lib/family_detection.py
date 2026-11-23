# -*- coding: utf-8 -*-
# family_detection module - version v1
# Change log (last change first):
#   v1 - Family Defaults Config v8: Detect Types in Project - the detection rules (Mounting and Device Type from the
#        family / type name and the family's parameters) and the default conduit type for each Device Type.
"""Detect Types in Project (Family Defaults Config): work out a type's Mounting, Device Type and Conduit Type from
its family name, type name and parameters. Nothing here touches Revit; the window supplies the names.

Rules (the Detection Rules tab, saved in circuit_config.json) are checked top to bottom. For each setting (Mounting,
Device Type) the first rule that matches gives the value. A rule matches when:
    Keywords    one of them is in the family or type name (case ignored). 'speaker+strobe' needs both words.
                Blank = any name.
    Parameters  the family has one of these parameters (instance or type, case ignored). Blank = any family.
Conduit Type: the device type's 'conduit type name contains' text (several separated by commas, e.g.
'Voice, Speaker, SPK', earlier ones preferred) is looked for in the project's conduit types; a type whose Type name
has it is preferred, then the first alphabetically. Blank = not set."""

MOUNTING, DEVICE_TYPE = "Mounting", "Device Type"
SETTING_FIELDS = {MOUNTING: "mounting", DEVICE_TYPE: "device_type"}     # rule setting -> circuit_config field
SETTINGS = [DEVICE_TYPE, MOUNTING]

_SLC = "SLC Address"
_NAC = "NAC Address, Voice Address, Notification Circuit"

# The starting rules (also what 'Reset to Starting Rules' puts back). Order matters: the first match wins, so
# Head End comes first and 'speaker+strobe' comes before 'speaker' and 'strobe'.
DEFAULT_RULES = [
    {"setting": DEVICE_TYPE, "value": "Head End", "keywords": "", "parameters": "Panel #"},
    {"setting": DEVICE_TYPE, "value": "Module",
     "keywords": "module, monitor, relay, control, mms, isolator, pull", "parameters": _SLC},
    {"setting": DEVICE_TYPE, "value": "Detector",
     "keywords": "detector, smoke, heat, duct, sensor, photo, beam", "parameters": _SLC},
    {"setting": DEVICE_TYPE, "value": "NAC and Voice", "keywords": "speaker+strobe, spk+strobe", "parameters": _NAC},
    {"setting": DEVICE_TYPE, "value": "Voice Only", "keywords": "speaker, spk", "parameters": _NAC},
    {"setting": DEVICE_TYPE, "value": "NAC Only", "keywords": "strobe, horn, chime, bell", "parameters": _NAC},
    {"setting": MOUNTING, "value": "Ceiling", "keywords": "ceiling, clg", "parameters": ""},
    {"setting": MOUNTING, "value": "Wall", "keywords": "wall", "parameters": ""},
]

# Device Type -> text the default conduit type's name contains ('' = leave blank).
DEFAULT_CONDUITS = {
    "Module": "SLC",
    "Detector": "SLC",
    "NAC Only": "NAC",
    "NAC and Voice": "NAC",
    "Voice Only": "Voice, Speaker, SPK",
    "Head End": "",
}


def _text(raw):
    return (u"%s" % raw).strip() if raw is not None else u""


def _items(text):
    """'a, b ,c' -> ['a', 'b', 'c'] (lower case)."""
    return [x.strip().lower() for x in _text(text).split(",") if x.strip()]


def default_detection():
    return {"rules": [dict(r) for r in DEFAULT_RULES], "conduits": dict(DEFAULT_CONDUITS)}


def normalize(raw, values):
    """The detection settings from the file; the starting ones when there are none.
    values: {setting: [values it may have]} (Mounting: Wall / Ceiling; Device Type: the device types)."""
    if not isinstance(raw, dict):
        return default_detection()
    rules = []
    for r in raw.get("rules") or []:
        if not isinstance(r, dict):
            continue
        setting, value = _text(r.get("setting")), _text(r.get("value"))
        if setting in values and value in values[setting]:
            rules.append({"setting": setting, "value": value, "keywords": _text(r.get("keywords")),
                          "parameters": _text(r.get("parameters"))})
    conduits = dict(DEFAULT_CONDUITS)
    for key, text in (raw.get("conduits") or {}).items():
        if key in values.get(DEVICE_TYPE, []):
            conduits[key] = _text(text)
    return {"rules": rules if "rules" in raw else [dict(r) for r in DEFAULT_RULES], "conduits": conduits}


def keywords_match(keywords, name):
    """True when one of the keywords is in name (case ignored); 'a+b' needs both. Blank keywords match any name."""
    words = _items(keywords)
    if not words:
        return True
    name = (name or u"").lower()
    for word in words:
        parts = [p.strip() for p in word.split("+") if p.strip()]
        if parts and all(p in name for p in parts):
            return True
    return False


def parameters_match(parameters, names):
    """True when the family has one of the parameters (names: lower-case parameter names). Blank matches any."""
    wanted = _items(parameters)
    return not wanted or any(w in names for w in wanted)


def detect(name, param_names, rules):
    """{field: value} for the first matching rule of each setting. name: 'Family Type' text to search;
    param_names: the family's parameter names (any case)."""
    names = set((n or u"").strip().lower() for n in param_names)
    found = {}
    for r in rules:
        field = SETTING_FIELDS.get(r["setting"])
        if field is None or field in found:
            continue
        if keywords_match(r["keywords"], name) and parameters_match(r["parameters"], names):
            found[field] = r["value"]
    return found


def conduit_for(device_type, conduits, labels):
    """The conduit type label for a device type: the first label containing the device type's text, preferring one
    whose Type name has it. None when there is no text or no conduit type has it."""
    wanted = _items(conduits.get(device_type)) if device_type else []
    if not wanted:
        return None
    best = None
    for label in sorted(labels, key=lambda l: l.lower()):
        low = label.lower()
        type_part = low.split(" : ", 1)[-1]
        for i, w in enumerate(wanted):
            if w in low:
                rank = (i, 0 if w in type_part else 1)
                if best is None or rank < best[0]:
                    best = (rank, label)
                break
    return best[1] if best else None
