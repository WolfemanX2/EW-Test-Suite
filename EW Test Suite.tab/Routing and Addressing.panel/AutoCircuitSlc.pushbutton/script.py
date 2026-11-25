# -*- coding: utf-8 -*-
# Auto Circuit - SLC script - version v4
__title__ = "Auto Circuit\nSLC v4"
__doc__ = ("SLC addresses (N#L#M000 / N#L#D000), and the conduit between the devices.\n\n"
           "Choose what to do:\n"
           "- Readdress: Manually (in order of selection) or Automatically (in order of conduit connection).\n"
           "- Route Conduit: a New Conduit Route, or Add to Existing Circuit (next update).\n"
           "- Reroute and Readdress: a New Conduit Route, or Add to Existing Circuit (next update).\n\n"
           'Readdress: continue a loop already in the project, continue from a selected device, or start a new one; then Manually (pick each device or its tag in order) or Automatically (pick the first device, then the next device on the circuit: the devices along the conduit towards it are addressed in order of connection). Each Family : Type is addressed by its Device Type and Address Group in Family Defaults Config: a group with several subgroups asks which one; no group asks how many. NAC / Voice and Head End devices are skipped.' "\n\n"
           "Settings: Family Defaults Config (Shift+Click opens it).")

import auto_circuit     # the Auto Circuit tools (lib/auto_circuit.py)

try:
    SHIFT_CLICKED = bool(__shiftclick__)    # noqa: F821 (set by pyRevit)
except NameError:
    SHIFT_CLICKED = False

auto_circuit.main('SLC', SHIFT_CLICKED)
