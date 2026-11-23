# -*- coding: utf-8 -*-
# Riser - Config script - version v8 (was SLC Riser - Config v7)
__title__ = "Riser - Config v8"
__doc__ = ("Settings for the riser tools, one tab per riser, laid out like Family Defaults Config: SLC Riser and "
           "NAC Riser. Each tab has its riser's own drawing settings (drafting view scale, spacing between devices, "
           "devices per line before wrapping, wrap rounding, address text offset) and its own table of the symbol "
           "drawn for each Family : Type. Save and Close are shared by both tabs.\n\n"
           "The symbols are any loaded Generic Annotation or Detail Item types. A type can have several, drawn in "
           "order with one address each (the last takes the rest), and rules that use other symbols depending on "
           "how many addresses a device has (e.g. <= 6 -> Default, <= 12 -> symbol A, >= 13 -> symbol B). "
           "'Add Types From Project' lists the loaded Fire Alarm Device types, or the Electrical Equipment types "
           "for panels.\n\n"
           "The SLC Riser tab uses the same files as SLC Riser - Config did, so nothing set there is lost.")

import riser_config_editor     # the window (lib/riser_config_editor.py)

riser_config_editor.show_editor()
