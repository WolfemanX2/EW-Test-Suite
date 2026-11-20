# -*- coding: utf-8 -*-
# Address NAC script - version v4
__title__ = "Address\nNAC v4"
__doc__ = """Fills NAC Address / NAC Circuit (N#-#.# / N#-#) on each picked Fire Alarm Device (or a tag hosted to one), in order of selection.

Continue a circuit already in the project (resumes after its highest device number), continue from a selected
device, or start a new one. After the first device, choose Manual (pick each device) or Automatic: select the
conduit leaving the device in the direction to check, then address to a device you pick, up to a max device count
for the circuit, or up to a max current (each device's Current, default 1.2 A). The conduit of the run gets
Notification Circuit = N12. After an automatic run, choose Finish or keep adding to the circuit.

When you finish, the last device of the circuit gets NAC EOL = Yes and every other device on it No. Its Comments get the total circuit current and the estimated EOL voltage
(20.4 V source, 14 AWG at 3.07 ohms per 1000 ft, point to point, home run included when connected).

Device types come from Address NAC / Voice - Config. Shift+Click to define / remove table entries.
Press Esc to finish picking."""

import nac_voice_addressing

try:
    SHIFT_CLICKED = bool(__shiftclick__)
except NameError:
    SHIFT_CLICKED = False

nac_voice_addressing.main("N", SHIFT_CLICKED)
