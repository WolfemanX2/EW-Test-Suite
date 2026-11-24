# -*- coding: utf-8 -*-
# Auto Circuit - Voice script - version v4
__title__ = "Auto Circuit\nVoice v4"
__doc__ = ("Voice addresses and circuits (V#-#.# / V#-#), and the conduit between the devices.\n\n"
           "Choose what to do:\n"
           "- Readdress: Manually (in order of selection) or Automatically (in order of conduit connection).\n"
           "- Route Conduit: a New Conduit Route, or Add to Existing Circuit (next update).\n"
           "- Reroute and Readdress: a New Conduit Route, or Add to Existing Circuit (next update).\n\n"
           'Readdress: continue a circuit already in the project, continue from a selected device, or start a new one; then Manually (pick each device or its tag in order) or Automatically (pick the first device, then the next device on the circuit, and address to a device you pick, a max device count or a max current). When you finish, the last device gets Voice EOL = Yes and every device gets Circuit Wattage. Device Types come from Family Defaults Config; SLC and Head End devices are skipped.' "\n\n"
           "Settings: Family Defaults Config (Shift+Click opens it).")

import auto_circuit     # the Auto Circuit tools (lib/auto_circuit.py)

try:
    SHIFT_CLICKED = bool(__shiftclick__)    # noqa: F821 (set by pyRevit)
except NameError:
    SHIFT_CLICKED = False

auto_circuit.main('V', SHIFT_CLICKED)
