# -*- coding: utf-8 -*-
# Address SLC script - version v10
__title__ = "Address\nSLC v10"
__doc__ = ("Fills the SLC Address parameters of each picked Fire Alarm Device (or a tag hosted to one), in order "
           "of selection. Addresses are N#L#M000 for modules and N#L#D000 for detectors; modules and detectors "
           "are counted separately. Address parameters on the device beyond the number filled are cleared.\n\n"
           "At the start, continue a loop already in the project (resumes after its highest M and D numbers), "
           "continue from a selected device (resumes after the addresses written on it), or start a new one.\n\n"
           "Each Family : Type is addressed by its rule in Address SLC - Config: a fixed number of addresses, "
           "named Address Options to choose from, or a prompt for the count. A type without a rule is asked "
           "for its kind and count. A type set to Head End is never addressed: it is skipped when picked and "
           "passed over when following conduit.\n\n"
           "After the first device (or after 'Continue From Selected'), choose Manual (pick each device) or "
           "Automatic: select the conduit leaving the device in the direction to check. Every device connected "
           "downstream by that conduit type is found, listed for confirmation and addressed in order of "
           "connection, either to the end of the run or to an end device you select. Conduit of any other type is "
           "not followed. After an automatic run, choose Finish or keep "
           "adding to the loop. In Manual you can still pick a conduit at any time to address downstream. Each automatic run is one Undo.\n\n"
           "Shift+Click opens Address SLC - Config. Press Esc to finish picking.")

import slc_session      # the addressing session (lib/slc_session.py)

try:
    SHIFT_CLICKED = bool(__shiftclick__)
except NameError:
    SHIFT_CLICKED = False

slc_session.main(SHIFT_CLICKED)
