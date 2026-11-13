# -*- coding: utf-8 -*-
# clash_rules module - version v3
"""Stores and reads the Auto Fix rules used by the Link Clash tool.
Rules are saved in a JSON file. All lengths are stored in feet."""
import os
import json

# Set this to a shared path (e.g. r"\\server\share\clash_rules.json") to share rules between users.
# Leave as None to store the file next to this module.
RULES_PATH = None

ELEV_NEVER = "Never (jogs only)"
ELEV_BEFORE = "Before trying jogs"
ELEV_AFTER = "After trying jogs"
ELEV_MODES = [ELEV_NEVER, ELEV_BEFORE, ELEV_AFTER]

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
}

LENGTH_KEYS = ["clearance", "max_shift", "shift_step", "jog_lead", "jog_min_leg", "max_elev_change",
               "max_saddle_length"]
ANGLE_KEYS = ["v_jog_min_angle", "v_jog_max_angle"]
ANGLES = list(range(5, 91, 5))   # allowed angle choices
BOOL_KEYS = ["ask_before", "allow_shift", "allow_h_jog", "allow_v_jog", "majority_elevation"]


def rules_path():
    if RULES_PATH:
        return RULES_PATH
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "clash_rules.json")


def _clean(raw):
    """Defaults overlaid with whatever valid values raw holds."""
    out = dict(DEFAULTS)
    if not isinstance(raw, dict):
        return out
    for k in LENGTH_KEYS:
        try:
            v = float(raw.get(k))
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
    if raw.get("elevation_mode") in ELEV_MODES:
        out["elevation_mode"] = raw["elevation_mode"]
    return out


def load_rules():
    p = rules_path()
    if not os.path.exists(p):
        return dict(DEFAULTS)
    try:
        with open(p, "r") as f:
            return _clean(json.load(f))
    except Exception:
        return dict(DEFAULTS)


def save_rules(rules):
    p = rules_path()
    folder = os.path.dirname(p)
    if folder and not os.path.exists(folder):
        os.makedirs(folder)
    with open(p, "w") as f:
        json.dump(_clean(rules), f, indent=2, sort_keys=True)
