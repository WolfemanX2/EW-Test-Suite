# -*- coding: utf-8 -*-
# Auto Circuit - Config script - version v2
__title__ = "Auto Circuit - Config v2"
__doc__ = ("One settings window for routing and addressing.\n\n"
           "Family Defaults: every Fire Alarm Device and Electrical Equipment family in the project, with its "
           "types under it (double-click a family). Set Mounting (Wall / Ceiling), Device Type (NAC Only, Voice "
           "Only, NAC and Voice, Module, Detector, Head End), Conduit Type, Address Group and Round To (a number "
           "you type). A value "
           "set on a family is set on all its types; <varies> means its types differ.\n\n"
           "Address and Routing Defaults: the elevation runs of each conduit type are drawn at, and the Address "
           "Groups: each group has subgroups with their own number of addresses (MMS Cabinet: Single Zone 6, Dual "
           "Zone 12 ...); a device of a group with several subgroups chooses one when it is addressed.\n\n"
           "The first time, it is filled from Auto Conduit - Config, Address SLC - Config and Address NAC / Voice - "
           "Config (their files are only read).")

from pyrevit import revit

import circuit_config_editor     # the window (lib/circuit_config_editor.py)

circuit_config_editor.show_editor(revit.doc)
