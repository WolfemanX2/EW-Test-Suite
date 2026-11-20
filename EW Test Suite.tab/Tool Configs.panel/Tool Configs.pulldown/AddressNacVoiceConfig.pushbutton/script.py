# -*- coding: utf-8 -*-
# Address NAC / Voice - Config script - version v5
__title__ = "Address NAC / Voice - Config v5"
__doc__ = ("Editable table of the Family : Type rules used by Address NAC / Voice. Each type is NAC Only, "
           "Voice Only, NAC and Voice, or Head End (never addressed by Address NAC, Address Voice or "
           "Auto-Circuit).\n\n"
           "'Add Types From Project' lists ALL loaded Fire Alarm Device types, including families that have "
           "not been placed, and suggests the device type from the NAC / Voice parameters each one has.\n\n"
           "Shift+Click on Address NAC or Address Voice opens this window too.")

from pyrevit import revit

import nac_voice_config_editor     # the window (lib/nac_voice_config_editor.py), shared with Shift+Click

nac_voice_config_editor.show_editor(revit.doc)
