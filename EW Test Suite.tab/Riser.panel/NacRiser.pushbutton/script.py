# -*- coding: utf-8 -*-
# NAC Riser script - version v1
__title__ = "NAC\nRiser v1"
__doc__ = ("Draws a one-line NAC riser diagram in a new drafting view named "
           "<LEVEL> - NAC RISER - <PANEL #> (the power supply's level and its Panel # parameter, in capitals). "
           "It works the same way as SLC Riser, following NAC circuits instead of SLC loops.\n\n"
           "Steps: select the NAC power supply (FACU, NAC panel, booster ...), then the first device in the circuit "
           "(either can be picked by its tag), choose the conduit types to trace, check the device count and "
           "adjust spacing / wrapping, then generate a new drafting view (with the panel detail) or add the "
           "circuit to an existing one (joined to the panel detail already there). Press Esc instead of picking "
           "a first device to follow every conduit run leaving the power supply.\n\n"
           "Every Fire Alarm Device with a NAC Address (N#-#.#) is drawn in order of connection, one row per "
           "circuit, with its address under it (45 degrees, right justified, hanging below the riser line). "
           "Each row is labeled with its circuit (N1-2) and made into a detail group named "
           "<PANEL #> - Circuit N1-2. The power supply is drawn with the NEX2-DETAIL-RISER detail item; circuit N "
           "leaves it in line with the reference line numbered N (1, L1, Loop 1, Circuit 1 ...) at the height of "
           "its Loop Spacing N, and the first line is locked to that reference line.\n\n"
           "A conduit teeing off the main run is drawn at the tee, out and back, then the main run carries on. "
           "Devices on the circuit (same N#-#) that no conduit reaches are added at the end in address order and "
           "marked NOT CONNECTED. Devices on the conduit without a NAC Address are passed through and listed "
           "afterwards.\n\n"
           "Symbols for each Family : Type, and the view scale, spacing, devices per line, wrap rounding and label "
           "offset, are set on the NAC tab of Riser - Config (kept apart from SLC Riser's). A type without a "
           "symbol is asked about when the tool runs, and the choice is saved.")

import riser_tool        # the riser engine, shared by the risers (lib/riser_tool.py)
import nac_riser         # the NAC circuit kind (lib/nac_riser.py)

riser_tool.run(nac_riser.CircuitKind("N"))
