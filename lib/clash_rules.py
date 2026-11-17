# -*- coding: utf-8 -*-
# clash_rules module - version v5
"""Stores and reads the Auto Fix rules used by the Link Clash tool.

Two files:
 - config/clash_rules.default.json, in the repository: the office starting point. Edit it in GitHub to change
   what new users start with. pyRevit's Update pulls changes to it.
 - the user's own copy, %APPDATA%\\pyRevit\\EWTestSuite\\clash_rules.json: created from the default the first time
   it is needed, then changed with the Link Clash - Config tool. Updates never overwrite it.

Lengths in the files are in inches when the file says "units": "inches" (both files do); older files without
that line are in feet. Inside the tools every length is in feet."""
import os
import json

# Set this to a shared path (e.g. r"\\server\share\clash_rules.json") so everyone uses one rules file.
# Leave as None for a per-user file in %APPDATA%.
RULES_PATH = None

EXTENSION_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_CONFIG = os.path.join(EXTENSION_DIR, "config", "clash_rules.default.json")
LOCAL_DIR = os.path.join(os.getenv("APPDATA") or os.path.expanduser("~"), "pyRevit", "EWTestSuite")
OLD_LOCAL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "clash_rules.json")   # before v5

ELEV_NEVER = "Never (jogs only)"
ELEV_BEFORE = "Before trying jogs"
ELEV_AFTER = "After trying jogs"
ELEV_MODES = [ELEV_NEVER, ELEV_BEFORE, ELEV_AFTER]

DEVICE_ASK = "Ask each time"
DEVICE_KEEP = "Device remains in place"
DEVICE_MOVE = "Adjust the device's elevation too"
DEVICE_MODES = [DEVICE_ASK, DEVICE_KEEP, DEVICE_MOVE]

DEFAULTS = {
    "ask_before": True,          # ask before applying each fix (starting state of the box in the results window)
    "clearance": 1.0 / 12,       # gap left between the conduit and anything in the links
    "allow_shift": True,         # try moving the conduit sideways first
    "max_shift": 1.0,            # furthest sideways move
    "shift_step": 1.0 / 12,      # moves are tried in steps of this size, smallest first
    "allow_h_jog": True,         # horizontal jogs (90 degree bends)
    "allow_v_jog": True,         # vertical jogs (angled bends)
    "v_jog_min_angle": 15,       # vertical jog (saddle) bend angles, degrees: multiples of 5 in this range,
    "v_jog_max_angle": 90,       # smallest tried first
    "max_saddle_length": 4.0,    # angles whose saddle would be longer than this are only used as a last resort
    "majority_elevation": True,  # several clashes on one conduit: first try an elevation change clearing most
    "jog_lead": 0.5,             # straight run kept between the obstacle and the jog
    "jog_min_leg": 0.75,         # shortest piece a jog may create
    "elevation_mode": ELEV_NEVER,   # whether the whole conduit may be raised or lowered
    "max_elev_change": 1.0,      # furthest the whole conduit may be raised or lowered
    "device_mode": DEVICE_ASK,   # conduit joined straight to a device, when its elevation would change
}
# DEFAULTS is only the fallback if config/clash_rules.default.json is missing or unreadable.

LENGTH_KEYS = ["clearance", "max_shift", "shift_step", "jog_lead", "jog_min_leg", "max_elev_change",
               "max_saddle_length"]
ANGLE_KEYS = ["v_jog_min_angle", "v_jog_max_angle"]
ANGLES = list(range(5, 91, 5))   # allowed angle choices
BOOL_KEYS = ["ask_before", "allow_shift", "allow_h_jog", "allow_v_jog", "majority_elevation"]


def rules_path():
    if RULES_PATH:
        return RULES_PATH
    return os.path.join(LOCAL_DIR, "clash_rules.json")


def _read(path):
    with open(path, "r") as f:
        return json.load(f)


def _write(path, rules):
    folder = os.path.dirname(path)
    if folder and not os.path.exists(folder):
        os.makedirs(folder)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(_to_file(_clean(rules)), f, indent=2, sort_keys=True)
    if os.path.exists(path):
        os.remove(path)
    os.rename(tmp, path)


def _to_file(rules):
    """Rules (feet) -> file contents (inches, rounded so the file stays readable)."""
    out = dict(rules)
    for k in LENGTH_KEYS:
        out[k] = round(rules[k] * 12.0, 4)
    out["units"] = "inches"
    return out


def default_rules():
    """The repository's default config (falls back to DEFAULTS if it is missing or unreadable)."""
    try:
        return _clean(_read(DEFAULT_CONFIG))
    except Exception:
        return dict(DEFAULTS)


def _clean(raw, base=None):
    """base (DEFAULTS if None) overlaid with whatever valid values raw holds. Result is in feet."""
    out = dict(base if base is not None else DEFAULTS)
    if not isinstance(raw, dict):
        return out
    scale = 1.0 / 12.0 if raw.get("units") == "inches" else 1.0
    for k in LENGTH_KEYS:
        try:
            v = float(raw.get(k)) * scale
            if v > 0:
                out[k] = v
        except Exception:
            pass
    for k in BOOL_KEYS:
        if isinstance(raw.get(k), bool):
            out[k] = raw[k]
    for k in ANGLE_KEYS:
        try:
            v = int(round(float(raw.get(k)) / 5.0)) * 5
            if 5 <= v <= 90:
                out[k] = v
        except Exception:
            pass
    if out["v_jog_min_angle"] > out["v_jog_max_angle"]:
        out["v_jog_min_angle"], out["v_jog_max_angle"] = out["v_jog_max_angle"], out["v_jog_min_angle"]
    if raw.get("device_mode") in DEVICE_MODES:
        out["device_mode"] = raw["device_mode"]
    if raw.get("elevation_mode") in ELEV_MODES:
        out["elevation_mode"] = raw["elevation_mode"]
    return out


def load_rules():
    """The user's rules. Settings missing from their file (e.g. added in a later version) come from the
    repository default. The first time, their file is created from the default (or from a pre-v5 file)."""
    base = default_rules()
    p = rules_path()
    if not os.path.exists(p):
        start = base
        if not RULES_PATH and os.path.exists(OLD_LOCAL):
            try:
                start = _clean(_read(OLD_LOCAL), base)   # keep settings saved before v5
            except Exception:
                pass
        try:
            _write(p, start)
        except Exception:
            pass
        return dict(start)
    try:
        return _clean(_read(p), base)
    except Exception:
        return dict(base)


def save_rules(rules):
    _write(rules_path(), rules)
