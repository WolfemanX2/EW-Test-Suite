# -*- coding: utf-8 -*-
# nac_riser module - version v9
# Change log (last change first):
#   v9 - NAC Riser v19: CircuitKind.level_labels and candela_line - NAC address text is level and centred under
#        the symbol, with the candela on the line below (N1-1.2 / 30CD).
#   v8 - NAC Riser v18: CircuitKind.supply_of(circuit) - the power supply number (N#) of a circuit, for the list.
#   v7 - NAC Riser v17: CircuitKind.location_name_only (Location = room / space name) and panel_number_params
#        (Power Supply #1-3: the number in the panel's text, written to the panel detail as an integer).
#   v6 - NAC Riser v15: CircuitKind.select_runs - the first-device prompt offers 'Trace Selected Circuits'.
#   v5 - NAC Riser v10: CircuitKind.return_text - every NAC one-line ends with 'NAC RETURN'.
"""NAC Riser: what the riser engine (lib/riser_tool.py) needs to know about NAC circuits.

The head end is a power supply (FACU, NAC panel, booster ...). Each circuit leaving it is one row, labeled with the
circuit (N1-2), and lines up with the NEX2-DETAIL-RISER reference line / Loop Spacing numbered for the circuit
(N1-2 -> 2). A device is on the riser when its NAC Address has a value; addresses are N#-#.# (power supply -
circuit . device), read and parsed with nac_voice_types, the same as the addressing tools.

The symbol table and drawing settings are NAC Riser's own files, kept apart from SLC Riser's:
    %APPDATA%\\pyRevit\\EWTestSuite\\nac_riser_symbols.json   (office default: config\\nac_riser_symbols.default.json)
    %APPDATA%\\pyRevit\\EWTestSuite\\nac_riser_settings.json  (office default: config\\nac_riser_settings.default.json)
They are read and written with slc_riser's functions (the same format) and changed on the NAC tab of
Riser - Config.

CircuitKind is written for either kind letter of nac_voice_types ("N" or "V"), so a Voice Riser would only need
its own button and files."""
import nac_voice_types as nv    # NAC Address parameter name, address format, all_devices (lib/nac_voice_types.py)
import slc_riser as sr          # table / settings reading and writing, shared by the risers (lib/slc_riser.py)
import config_store as cs       # where settings files live, office defaults (lib/config_store.py)

# Set these to shared paths (e.g. r"\\server\share\nac_riser_symbols.json") so everyone uses one table / settings.
# Leave as None for a per-user file in %APPDATA%.
TABLE_PATH = None
SETTINGS_PATH = None

DEFAULT_TABLE = cs.default_file("nac_riser_symbols.default.json")
DEFAULT_SETTINGS_FILE = cs.default_file("nac_riser_settings.default.json")

# The drawing settings have the same keys, defaults and limits as SLC Riser's.
SCALES = sr.SCALES
DEFAULT_SETTINGS = sr.DEFAULT_SETTINGS
SETTING_LIMITS = sr.SETTING_LIMITS
ADDRESS_CALLOUTS = False    # Riser - Config: no Address Callouts table on the NAC tab


def table_path():
    return cs.user_file("nac_riser_symbols.json", TABLE_PATH)


def settings_path():
    return cs.user_file("nac_riser_settings.json", SETTINGS_PATH)


def load_table():
    """NAC Riser's symbol table (same format as SLC Riser's). Raises if the file can't be read."""
    return sr.load_table(table_path(), None if TABLE_PATH else DEFAULT_TABLE)


def save_table(table):
    sr.save_table(table, table_path())


def load_settings():
    """NAC Riser's drawing settings, with the defaults for anything missing. Raises if the file can't be read."""
    return sr.load_settings(settings_path(), None if SETTINGS_PATH else DEFAULT_SETTINGS_FILE)


def save_settings(settings):
    sr.save_settings(settings, settings_path())


class CircuitKind(object):
    """A notification circuit kind ("N" = NAC) for riser_tool.run()."""

    # Files and config: this module's functions.
    table_path = staticmethod(table_path)
    load_table = staticmethod(load_table)
    save_table = staticmethod(save_table)
    settings_path = staticmethod(settings_path)
    load_settings = staticmethod(load_settings)
    save_settings = staticmethod(save_settings)
    DEFAULT_SETTINGS = DEFAULT_SETTINGS
    SETTING_LIMITS = SETTING_LIMITS

    def __init__(self, kind="N"):
        self.kind = kind
        name = nv.KIND_NAMES[kind]                      # "NAC"
        self.param = nv.PARAM_NAMES[kind]["address"]    # "NAC Address"
        self.title = "%s Riser" % name
        self.riser_name = "%s Riser" % name             # LEVEL 1 - NAC RISER - NAC-01
        self.view_tag = ("%s Riser" % name).upper()
        self.config_name = "Riser - Config (%s Riser tab)" % name
        self.run_word = "Circuit"
        self.return_text = "%s RETURN" % name.upper()     # written after the last device of every one-line
        self.address_label = self.param
        self.address_phrase = "a %s" % self.param
        self.head_prompt = "Select %s Power Supply" % name
        self.head_example = "EX: FACU, NAC Panel, Booster Power Supply, etc."
        self.no_address_hint = "have no value in %s" % self.param
        # Select from List (riser_tool.head_end_panels): a power supply is listed when its family name contains one
        # of these words (case ignored) and it is also Head End in Family Defaults Config or has a Panel # parameter.
        self.head_list_keywords = ["NAC", "NCP", "NACP"] if kind == "N" else None
        self.head_list_keywords_required = True
        self.head_list_min_matches = 2
        # The first-device prompt offers "Trace Selected Circuits" (a list of every circuit in the project) instead of
        # "Trace Every Run From Panel" (riser_tool.first_devices).
        self.select_runs = True
        # The panel detail (riser_tool.fill_panel): Location is the name of the room / space the panel is in, and
        # these text parameters of the panel go to the detail's integer parameters of the same name as the number
        # in them (NACP-01 -> 1).
        self.location_name_only = True
        self.panel_number_params = ["Power Supply #1", "Power Supply #2", "Power Supply #3"]
        # Address text: level and centred under the symbol (not at 45 degrees), with the device's candela below it.
        self.level_labels = True
        self.candela_line = True

    # ---- Addresses ----
    def new_reader(self):
        return None     # nothing to cache: one text parameter

    def addresses(self, el, reader=None):
        """[the device's NAC Address] when it has a value, else []."""
        p = nv.get_param(el, self.param)
        if p is None:
            return []
        try:
            text = (p.AsString() or "").strip()
        except Exception:
            return []
        return [text] if text else []

    def _parsed(self, addresses):
        for text in addresses or []:
            parsed = nv.parse_address(self.kind, text)
            if parsed:
                yield parsed

    def sort_key(self, addresses):
        """(0, power supply, circuit, device) of the first readable address; devices without one sort last."""
        for source, circuit, number in self._parsed(addresses):
            return (0, source, circuit, number)
        return (1, 0, 0, 0)

    def supply_of(self, group):
        """The power supply number (N#) of a circuit (KIND.groups), e.g. 1 for N1-3."""
        return group[0]

    def groups(self, addresses):
        """{(power supply, circuit)} named in these addresses."""
        return set((source, circuit) for source, circuit, _ in self._parsed(addresses))

    def row_label(self, address_lists):
        """'N1-2', or 'N1-2, N1-3' for the circuits found in a row; '' if none can be read."""
        found = set()
        for addresses in address_lists:
            found |= self.groups(addresses)
        return ", ".join(nv.fmt_circuit(self.kind, s, c) for s, c in sorted(found))

    def row_number(self, address_lists):
        """The circuit number of a row (N1-2 -> 2) when all its addresses agree on one, else None. It picks the
        head end's reference line / Loop Spacing with that number."""
        circuits = set()
        for addresses in address_lists:
            circuits |= set(c for _, c in self.groups(addresses))
        return circuits.pop() if len(circuits) == 1 else None

    def devices_on_groups(self, doc, groups):
        """[(element, [NAC Address])] of every Fire Alarm Device on these (power supply, circuit) pairs, in
        address order."""
        found = []
        if not groups:
            return found
        for el in nv.all_devices(doc):
            try:
                addresses = self.addresses(el)
            except Exception:
                continue
            if addresses and self.groups(addresses) & groups:
                found.append((el, addresses))
        found.sort(key=lambda pair: self.sort_key(pair[1]))
        return found
