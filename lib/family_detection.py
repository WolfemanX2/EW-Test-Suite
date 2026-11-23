# -*- coding: utf-8 -*-
# family_detection module - version v3
# Change log (last change first):
#   v3 - Family Defaults Config v11 (cleanup): first_values - the first match of each setting, used by detect and by
#        the window (which had its own copy of it).
#   v2 - Family Defaults Config v10: device_choices - when a type matches Device Type rules of more than one group
#        (Head End / SLC / NAC), the first match of each group with why it matched, so the user can choose;
#        keywords_match / parameters_match say which keyword / parameter matched. A family with another group's
#        parameters but none of its keywords (Panel # + SLC Address) is asked about too (parameter_only_matches).
#   v1 - Family Defaults Config v8: Detect Types in Project - the detection rules (Mounting and Device Type from the
#        family / type name and the family's parameters) and the default conduit type for each Device Type.
"""Detect Types in Project (Family Defaults Config): work out a type's Mounting, Device Type and Conduit Type from
its family name, type name and parameters. Nothing here touches Revit; the window supplies the names.

Rules (the Detection Rules tab, saved in circuit_config.json) are checked top to bottom. For each setting (Mounting,
Device Type) the first rule that matches gives the value. A rule matches when:
    Keywords    one of them is in the family or type name (case ignored). 'speaker+strobe' needs both words.
                Blank = any name.
    Parameters  the family has one of these parameters (instance or type, case ignored). Blank = any family.
Device Types come in groups: Head End; SLC (Module, Detector); NAC (NAC Only, Voice Only, NAC and Voice). Within a
group the first matching rule wins (so 'speaker+strobe' beats 'speaker'); when a type matches rules of more than
one group (Panel # and SLC Address, say), device_choices gives each group's match and the window asks which is
right.
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


# Device Type -> its group; a type matching rules of two groups is asked about.
DEVICE_GROUPS = {"Head End": "Head End", "Module": "SLC", "Detector": "SLC",
                 "NAC Only": "NAC", "Voice Only": "NAC", "NAC and Voice": "NAC"}


def keywords_match(keywords, name):
    """The keyword found in name (case ignored; 'a+b' needs both), True for blank keywords (any name), or None."""
    words = _items(keywords)
    if not words:
        return True
    name = (name or u"").lower()
    for word in words:
        parts = [p.strip() for p in word.split("+") if p.strip()]
        if parts and all(p in name for p in parts):
            return word
    return None


def parameters_match(parameters, names):
    """The parameter the family has (names: lower-case parameter names), True for blank (any family), or None."""
    wanted = _items(parameters)
    if not wanted:
        return True
    for w in wanted:
        if w in names:
            return w
    return None


def matches(name, param_names, rules):
    """[(rule, why)] of every rule that matches, in order. why: 'has Panel #', "'module' in the name" ..."""
    names = set((n or u"").strip().lower() for n in param_names)
    out = []
    for r in rules:
        if SETTING_FIELDS.get(r["setting"]) is None:
            continue
        word = keywords_match(r["keywords"], name)
        if not word:
            continue
        param = parameters_match(r["parameters"], names)
        if not param:
            continue
        why = []
        if word is not True:
            why.append(u"'%s' in the name" % word)
        if param is not True:
            why.append(u"has %s" % _original(param, param_names))
        out.append((r, u", ".join(why)))
    return out


def _original(lower, param_names):
    """The parameter name as the family spells it."""
    for n in param_names:
        if (n or u"").strip().lower() == lower:
            return n.strip()
    return lower


def first_values(found):
    """{field: value} of the first match of each setting, from matches()."""
    out = {}
    for r, _why in found:
        out.setdefault(SETTING_FIELDS[r["setting"]], r["value"])
    return out


def detect(name, param_names, rules):
    """{field: value} for the first matching rule of each setting. name: 'Family Type' text to search;
    param_names: the family's parameter names (any case)."""
    return first_values(matches(name, param_names, rules))


def parameter_only_matches(name, param_names, rules):
    """[(rule, why)] of the Device Type rules whose parameters the family has but none of whose keywords are in the
    name (e.g. SLC Address on a panel without 'module' in its name)."""
    names = set((n or u"").strip().lower() for n in param_names)
    out = []
    for r in rules:
        if r["setting"] != DEVICE_TYPE or not _items(r["keywords"]) or not _items(r["parameters"]):
            continue
        param = parameters_match(r["parameters"], names)
        if param and not keywords_match(r["keywords"], name):
            out.append((r, u"has %s (no %s keyword in the name)" % (_original(param, param_names), r["value"])))
    return out


def device_choices(found, partial=()):
    """[(device type, why)] - the first Device Type match of each group, in rule order, from matches(). More than
    one group means the type looks like more than one kind of device and should be asked about.
    partial: parameter_only_matches(). When a type matched rules of some group, a group it only has the parameters of
    (Panel # matched Head End; SLC Address but no SLC keyword) is offered too, each of its Device Types (Module,
    Detector), so Head End vs SLC device is still asked."""
    out, groups = [], set()
    for r, why in found:
        if r["setting"] != DEVICE_TYPE:
            continue
        group = DEVICE_GROUPS.get(r["value"], r["value"])
        if group not in groups:
            groups.add(group)
            out.append((r["value"], why))
    if out:
        extra, seen = [], set(v for v, _w in out)
        for r, why in partial:
            group = DEVICE_GROUPS.get(r["value"], r["value"])
            if group not in groups and r["value"] not in seen:
                seen.add(r["value"])
                extra.append((r["value"], why))
        out += extra
    return out


def needs_asking(choices):
    """True when the choices span more than one Device Type group."""
    return len(set(DEVICE_GROUPS.get(v, v) for v, _w in choices)) > 1


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
