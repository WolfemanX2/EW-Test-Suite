# -*- coding: utf-8 -*-
# Addressing Config script - version v2
__title__ = "Addressing\nConfig v2"
__doc__ = ("Editable table of the Family : Type rules used by Address SLC: Device Type (Module or Detector), "
           "Number of Addresses, Address Options and Round Up To Multiple Of.\n\n"
           "Address Options are named choices offered when the device is picked, typed as "
           "\"Single Zone\":6, \"Dual Zone\":12.\n\n"
           "'Add Types From Project' lists ALL loaded Fire Alarm Device types, including families that have "
           "not been placed. 'Load Default Config' copies the rules of a default config file into your local "
           "one without changing the default.")

from pyrevit import revit

import slc_config_editor

slc_config_editor.show_editor(revit.doc)
