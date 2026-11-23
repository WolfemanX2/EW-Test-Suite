# -*- coding: utf-8 -*-
# Family Defaults Config script - version v11
__title__ = "Family Defaults Config v11"
__doc__ = ("One settings window for routing and addressing, used by Auto Circuit - SLC, NAC and Voice.\n\n"
           "Family Defaults: every Fire Alarm Device and Electrical Equipment family in the project, with its "
           "types under it (double-click a family). Set Mounting (Wall / Ceiling), Device Type (NAC Only, Voice "
           "Only, NAC and Voice, Module, Detector, Head End), Conduit Type, Address Group and Round To (a number "
           "you type). A value "
           "set on a family is set on all its types; <varies> means its types differ. Select several rows "
           "(Ctrl+click / Shift+click): changing a cell in one of them changes that column on all of them; filter by Category, Circuit Type (SLC: "
           "SLC Address parameters, NAC: a Notification Circuit parameter), Mounting, Device Type, Conduit Type or "
           "Address Group, and sort by any of them.\n\n"
           "Address and Routing Defaults: the elevation runs of each conduit type are drawn at, and the Address "
           "Groups: each group has subgroups with their own number of addresses (MMS Cabinet: Single Zone 6, Dual "
           "Zone 12 ...); a device of a group with several subgroups chooses one when it is addressed.\n\n"
           "Detect Types in Project (bottom bar, next to Load Default Config): fills Mounting, Device Type and Conduit Type for every type in "
           "the project from its family / type name and parameters - e.g. SLC Address + 'Module' in the name = Module "
           "with the SLC conduit type, Panel # = Head End, 'Ceiling' / 'Wall' in the name = the mounting. It asks "
           "whether to fill blank cells only or replace existing values, then lists the changes to untick any you "
           "don't want; nothing is saved until Save. The rules are on the Detection Rules tab: each sets Mounting or "
           "Device Type when one of its keywords is in the name ('speaker+strobe' needs both words) and the family "
           "has one of its parameters; the first match wins. The conduit type is the one whose name contains the "
           "text set for the Device Type (SLC, NAC, Voice ...). A type that looks like more than one kind of device - "
           "Head End, SLC (Module / Detector) or NAC - e.g. Panel # and SLC Address, is asked about (once per family) "
           "before the list.\n\n"
           "The first time, it is filled from Auto Conduit - Config, Address SLC - Config and Address NAC / Voice - "
           "Config (their files are only read).")

from pyrevit import revit

import circuit_config_editor     # the window (lib/circuit_config_editor.py)

circuit_config_editor.show_editor(revit.doc)
