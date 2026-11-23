# -*- coding: utf-8 -*-
# Riser - Config script - version v9 (was SLC Riser - Config v7)
__title__ = "Riser - Config v9"
__doc__ = ("Settings for the riser tools, one tab per riser, laid out like Family Defaults Config: SLC Riser and "
           "NAC Riser. Each tab has its riser's own drawing settings (drafting view scale, spacing between devices, "
           "devices per line before wrapping, wrap rounding, address text offset) and its own table of the symbol "
           "drawn for each Family : Type. Save and Close are shared by both tabs.\n\n"
           "The symbols are any loaded Generic Annotation or Detail Item types. A type can have several, drawn in "
           "order with one address each (the last takes the rest). 'Add Types From Project' lists the loaded Fire Alarm Device types, or the Electrical Equipment types "
           "for panels.\n\n"
           "SLC Riser tab: each type's Address Group from Family Defaults Config is shown, and the Address Callouts "
           "table lists every Address Group subgroup (e.g. MMS Cabinet: Single / Dual / Triple / Quad Zone). Give a "
           "subgroup a callout symbol and its devices (picked by their number of addresses) are labeled with it "
           "instead of the 45 degree address text; the callout's parameters are filled from the device's "
           "same-named parameters. Blank = the 45 degree text.\n\n"
           "The SLC Riser tab uses the same files as SLC Riser - Config did, so nothing set there is lost.")

import riser_config_editor     # the window (lib/riser_config_editor.py)

riser_config_editor.show_editor()
