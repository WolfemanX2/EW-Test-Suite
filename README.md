# EW Test Suite

pyRevit extension with conduit routing, link clash, device addressing, riser diagram, strobe coverage, project cleanup and family parameter tools for Revit.

Every tool's settings window lives in the **Tool Configs** drop-down (its own panel at the end of the tab) and is named `<Tool Name> - Config`.

The **EW Production Suite** tab holds the **Family QAQC** panel (Family Placer, Family Audit) and the Obsolete panel.

Tools being replaced are kept in the **Obsolete** panel on the separate **EW Production Suite** tab, in three drop-downs:
**Old Tools** (Auto Conduit, Auto-Circuit, Address SLC, Address NAC, Address Voice, NAC Coverage Checker),
**Template Cleanup** (Line Nuke, Consolidate Text Styles) and **Parameter Tools** (the family parameter tools).

## Tools

### <picture><source media="(prefers-color-scheme: dark)" srcset="EW%20Production%20Suite.tab/Family%20QAQC.panel/FamilyPlacer.pushbutton/icon.dark.png"><img src="EW%20Production%20Suite.tab/Family%20QAQC.panel/FamilyPlacer.pushbutton/icon.png" width="32" height="32" alt=""></picture> Family Placer
- Places one of every loaded type of a chosen category in a grid in the active plan view: one row per family, one column per type, 6 ft apart unless you enter another spacing. Model families are placed 5.5 ft above the level, and each row is labeled with its family name. Families that need a host or a curve are skipped and listed.

### <picture><source media="(prefers-color-scheme: dark)" srcset="EW%20Production%20Suite.tab/Family%20QAQC.panel/FamilyAudit.pushbutton/icon.dark.png"><img src="EW%20Production%20Suite.tab/Family%20QAQC.panel/FamilyAudit.pushbutton/icon.png" width="32" height="32" alt=""></picture> Family Audit
- Lists the loaded families of one category (picked like Family Placer) with their number of types, the shared parameters inside each family and the shared parameter file each one is in (matched by GUID against the current file and any other files you add, which are remembered). Also lists the shared families nested in each family and shared parameters with the same name but different GUIDs, and can save the results as a CSV file (offered after the remap step, so it shows the remapped parameters). Shared parameters not found in any file but with a parameter of the same name in one can then be remapped to that file's parameter, as can plain family parameters with a matching name (each is an option). Similar names (fuzzy match) are offered too, but each one must be confirmed; the changed families are saved to a folder you pick and can be reloaded into the project.

### <picture><source media="(prefers-color-scheme: dark)" srcset="EW%20Test%20Suite.tab/Routing%20and%20Addressing.panel/AutoCircuitSlc.pushbutton/icon.dark.png"><img src="EW%20Test%20Suite.tab/Routing%20and%20Addressing.panel/AutoCircuitSlc.pushbutton/icon.png" width="32" height="32" alt=""></picture> Auto Circuit - SLC - Configurable
- Readdresses SLC devices manually or automatically along the conduit; Route Conduit and Reroute and Readdress are coming next.
- **Family Defaults Config:** Device Type, Address Group and rounding for each family and type

### <picture><source media="(prefers-color-scheme: dark)" srcset="EW%20Test%20Suite.tab/Routing%20and%20Addressing.panel/AutoCircuitNac.pushbutton/icon.dark.png"><img src="EW%20Test%20Suite.tab/Routing%20and%20Addressing.panel/AutoCircuitNac.pushbutton/icon.png" width="32" height="32" alt=""></picture> Auto Circuit - NAC - Configurable
- Readdresses NAC devices manually or automatically along the conduit, then marks the EOL device and fills the circuit totals; Route Conduit and Reroute and Readdress are coming next.
- **Family Defaults Config:** Device Type for each family and type

### <picture><source media="(prefers-color-scheme: dark)" srcset="EW%20Test%20Suite.tab/Routing%20and%20Addressing.panel/AutoCircuitVoice.pushbutton/icon.dark.png"><img src="EW%20Test%20Suite.tab/Routing%20and%20Addressing.panel/AutoCircuitVoice.pushbutton/icon.png" width="32" height="32" alt=""></picture> Auto Circuit - Voice - Configurable
- Readdresses Voice devices manually or automatically along the conduit, then marks the EOL device and fills Circuit Wattage; Route Conduit and Reroute and Readdress are coming next.
- **Family Defaults Config:** Device Type for each family and type

### <picture><source media="(prefers-color-scheme: dark)" srcset="EW%20Production%20Suite.tab/Obsolete.panel/Old%20Tools.pulldown/AutoConduit.pushbutton/icon.dark.png"><img src="EW%20Production%20Suite.tab/Obsolete.panel/Old%20Tools.pulldown/AutoConduit.pushbutton/icon.png" width="32" height="32" alt=""></picture> Auto Conduit - Configurable
- Automatically draws conduit between devices in order of selection.
- Reads the old settings files (its config window has been removed; Family Defaults Config replaces it)

### <picture><source media="(prefers-color-scheme: dark)" srcset="EW%20Production%20Suite.tab/Obsolete.panel/Old%20Tools.pulldown/AutoCircuit.pushbutton/icon.dark.png"><img src="EW%20Production%20Suite.tab/Obsolete.panel/Old%20Tools.pulldown/AutoCircuit.pushbutton/icon.png" width="32" height="32" alt=""></picture> Auto-Circuit - Configurable
- Draws conduit between devices and addresses them based on order of selection. It can also insert new devices into an existing circuit and renumber the devices after them.
- Reads the old settings files (its config window has been removed; Family Defaults Config replaces it)

### <picture><source media="(prefers-color-scheme: dark)" srcset="EW%20Test%20Suite.tab/Clash.panel/LinkClash.pushbutton/icon.dark.png"><img src="EW%20Test%20Suite.tab/Clash.panel/LinkClash.pushbutton/icon.png" width="32" height="32" alt=""></picture> Link Clash - Configurable
- Checks selected elements for clashes with MEP and structural elements in loaded Revit links and lists them in a results window with statuses. Auto Fix can shift or jog a clashing conduit to clear it.
- **Link Clash - Config:** sets the distances and allowed fixes that Auto Fix uses

### <picture><source media="(prefers-color-scheme: dark)" srcset="EW%20Production%20Suite.tab/Obsolete.panel/Old%20Tools.pulldown/AddressSlc.pushbutton/icon.dark.png"><img src="EW%20Production%20Suite.tab/Obsolete.panel/Old%20Tools.pulldown/AddressSlc.pushbutton/icon.png" width="32" height="32" alt=""></picture> Address SLC - Configurable
- Fills in the SLC addresses of devices in the order you select them. It can also address them automatically by following the conduit downstream from a selected device.
- Reads the old settings files (its config window has been removed; Family Defaults Config replaces it)

### <picture><source media="(prefers-color-scheme: dark)" srcset="EW%20Production%20Suite.tab/Obsolete.panel/Old%20Tools.pulldown/AddressNac.pushbutton/icon.dark.png"><img src="EW%20Production%20Suite.tab/Obsolete.panel/Old%20Tools.pulldown/AddressNac.pushbutton/icon.png" width="32" height="32" alt=""></picture> Address NAC - Configurable
- Fills in NAC addresses and circuits on devices in the order you select them, or automatically along the conduit from a selected device. It also marks the end-of-line device and fills each device's Circuit Current and estimated Circuit Voltage.
- Reads the old settings files (its config window has been removed; Family Defaults Config replaces it)

### <picture><source media="(prefers-color-scheme: dark)" srcset="EW%20Production%20Suite.tab/Obsolete.panel/Old%20Tools.pulldown/AddressVoice.pushbutton/icon.dark.png"><img src="EW%20Production%20Suite.tab/Obsolete.panel/Old%20Tools.pulldown/AddressVoice.pushbutton/icon.png" width="32" height="32" alt=""></picture> Address Voice - Configurable
- Fills in Voice addresses and circuits on devices in the order you select them, or automatically along the conduit from a selected device. It also marks the end-of-line device and fills each device's Circuit Wattage.
- Reads the old settings files (its config window has been removed; Family Defaults Config replaces it)

### <picture><source media="(prefers-color-scheme: dark)" srcset="EW%20Test%20Suite.tab/Riser.panel/SlcRiser.pushbutton/icon.dark.png"><img src="EW%20Test%20Suite.tab/Riser.panel/SlcRiser.pushbutton/icon.png" width="32" height="32" alt=""></picture> SLC Riser - Configurable
- Draws a one-line SLC riser diagram in a drafting view, with each device shown in order of connection along the conduit and labeled with its SLC address.
- The head end panel is chosen from a list (panels with FACU / FACP / FAP / FAC in the family name that are also Head End in Family Defaults Config or have a Panel # parameter) or selected in the model. If no conduit is connected to the panel, the conduit is traced from the nearest element within 5' that has conduit connected, a GUTTER-BOX family 1-2' above the panel first.
- **Update Selected One-Line:** run SLC Riser or NAC Riser from a drafting view, pick a one-line group, and its
  circuit is traced again and redrawn in place with the current symbols, callouts and settings. Each one-line ends
  with SLC RETURN / NAC RETURN; the panel detail's Panel Model comes from the panel's Model.
- **Update Panel:** from the same drafting view options, every one-line of one panel in the view is traced again and
  redrawn (lowest loop / circuit first) as one undo step, with one summary; each question is asked once for all of them.
  NAC Riser (power supplies nested in the panel detail) also deletes circuits no longer in the model, draws new circuits
  on their power supply's output (N2-3 -> line 3 of power supply 2), and marks outputs with no circuit as SPARE.
- **Riser - Config (SLC Riser tab):** sets the drawing settings (including the panel detail family drawn for the head end, the circuit label's offset from the start of the one-line, and the line end: text or a Generic Annotation) and the symbols used for each device type, and an
  optional address callout symbol per Address Group subgroup (Family Defaults Config) used instead of the 45 degree
  address text, placed in a band below the line's address text with detail lines to the device (build callouts as
  Generic Annotations with their origin at the top); the callout's parameters are filled from the device's same-named
  parameters

### <picture><source media="(prefers-color-scheme: dark)" srcset="EW%20Test%20Suite.tab/Riser.panel/NacRiser.pushbutton/icon.dark.png"><img src="EW%20Test%20Suite.tab/Riser.panel/NacRiser.pushbutton/icon.png" width="32" height="32" alt=""></picture> NAC Riser - Configurable
- Draws a one-line NAC riser diagram the same way as SLC Riser: pick the power supply and the first device, and each NAC circuit leaving the power supply is drawn as one row in order of connection, labeled with its circuit (N1-2) and each device with its NAC Address and candela (N1-1.2 / 30CD) as level text centred under the symbol. Circuit N lines up with reference line N of the panel detail (the family set on the NAC Riser tab of Riser - Config), filled in with the power supply's Panel #, Panel Model, Location (room or space name) and Power Supply #1-3 (the number in each, e.g. NACP-01 -> 1).
- The power supply is chosen from a list (NAC / NCP / NACP in the family name, plus Head End in Family Defaults Config or a Panel # parameter) or selected in the model.
- **Riser - Config (NAC Riser tab):** its own drawing settings (including its own panel detail family) and symbols, kept apart from SLC Riser's

### <picture><source media="(prefers-color-scheme: dark)" srcset="EW%20Test%20Suite.tab/VESDA.panel/VesdaPipeSwap.pushbutton/icon.dark.png"><img src="EW%20Test%20Suite.tab/VESDA.panel/VesdaPipeSwap.pushbutton/icon.png" width="32" height="32" alt=""></picture> VESDA Pipe Swap - Configurable
- Changes the pipe type of a VESDA run without Revit's Change Type rebuilding it: pipes get the new type and keep their size, and elbows / tees (plus crosses, transitions, unions, caps) are swapped for the parts in the new type's Routing Preferences, in place and still connected.
- Sampling point families are never changed. Pick a pipe, fitting or tag and choose Whole connected run (stops at equipment such as the detector) or Selected only. If the run has several pipe types you choose which to change.
- Every connection is checked afterwards; any that came apart are rejoined, or listed and left selected with the choice to keep or undo the swap.
- ADDRESS follows the new type's number (the last number in the type name): swapped pipes are set to `<Panel #>: PORT 1` from the Panel # of the detector (Fire Alarm Device) the run connects to, or `ASD-##: PORT 1` if it has none, and sampling points on a swapped pipe `P4:S0:H3` → `P1:S0:H3` (S# and H# are not changed).
- **VESDA Pipe Swap - Config:** tick which Pipe Fitting / Pipe Accessory families are sampling points (saved per user by family name)

### <picture><source media="(prefers-color-scheme: dark)" srcset="EW%20Production%20Suite.tab/Obsolete.panel/Old%20Tools.pulldown/NACCoverageChecker.pushbutton/icon.dark.png"><img src="EW%20Production%20Suite.tab/Obsolete.panel/Old%20Tools.pulldown/NACCoverageChecker.pushbutton/icon.png" width="32" height="32" alt=""></picture> NAC Coverage Checker - Configurable
- Shows strobe coverage on a floor plan, for the whole view or one room, based on each device's candela. Points that a strobe can't see because something in the model or a loaded link is in the way are shown as blocked.
- Reads the old settings files (its config window has been removed; Family Defaults Config replaces it)

### <picture><source media="(prefers-color-scheme: dark)" srcset="EW%20Production%20Suite.tab/Obsolete.panel/Template%20Cleanup.pulldown/LineNuke.pushbutton/icon.dark.png"><img src="EW%20Production%20Suite.tab/Obsolete.panel/Template%20Cleanup.pulldown/LineNuke.pushbutton/icon.png" width="32" height="32" alt=""></picture> Line Nuke
- Creates the 15 standard "Detail Line - Color - Size" line styles and merges any line styles with the same color, weight and pattern into them.

### <picture><source media="(prefers-color-scheme: dark)" srcset="EW%20Production%20Suite.tab/Obsolete.panel/Template%20Cleanup.pulldown/ConsolidateTextStyles.pushbutton/icon.dark.png"><img src="EW%20Production%20Suite.tab/Obsolete.panel/Template%20Cleanup.pulldown/ConsolidateTextStyles.pushbutton/icon.png" width="32" height="32" alt=""></picture> Consolidate Text Styles
- Merges text styles that have the same text size into one style per size and renames it by size, font and modifiers (e.g. 1/8" Arial Bold).

### <picture><source media="(prefers-color-scheme: dark)" srcset="EW%20Production%20Suite.tab/Obsolete.panel/Parameter%20Tools.pulldown/DeviceSharedParams.pushbutton/icon.dark.png"><img src="EW%20Production%20Suite.tab/Obsolete.panel/Parameter%20Tools.pulldown/DeviceSharedParams.pushbutton/icon.png" width="32" height="32" alt=""></picture> Device Shared Params
- Adds a batch of shared parameters to device families, either the family open in the Family Editor or families picked from the project.

### <picture><source media="(prefers-color-scheme: dark)" srcset="EW%20Production%20Suite.tab/Obsolete.panel/Parameter%20Tools.pulldown/TagSharedParams.pushbutton/icon.dark.png"><img src="EW%20Production%20Suite.tab/Obsolete.panel/Parameter%20Tools.pulldown/TagSharedParams.pushbutton/icon.png" width="32" height="32" alt=""></picture> Tag Shared Params
- Adds a batch of shared parameters to tag families, either for use in labels or as parameters of the tag itself.

### <picture><source media="(prefers-color-scheme: dark)" srcset="EW%20Production%20Suite.tab/Obsolete.panel/Parameter%20Tools.pulldown/TransferFamilyParams.pushbutton/icon.dark.png"><img src="EW%20Production%20Suite.tab/Obsolete.panel/Parameter%20Tools.pulldown/TransferFamilyParams.pushbutton/icon.png" width="32" height="32" alt=""></picture> Transfer Family Params
- Copies the parameters you choose, with their formulas and values if you want, from one open family to one or more other open families.

## Install

This repository is private, so pyRevit needs a GitHub personal access token to download it.

1. Create a token on GitHub: **Settings > Developer settings > Personal access tokens > Fine-grained tokens**.
   Give it access to this repository only, with **Contents: Read-only**.
2. Open a Command Prompt and run (one line):

   ```
   pyrevit extend ui EWTestSuite https://github.com/WolfemanX2/ew-test-suite.git --username=<your GitHub user> --password=<token>
   ```

3. Reload pyRevit (pyRevit tab > Reload). The **EW Test Suite** tab appears.

### Branches

- `main` holds the released tools (Conduit, Clash, Addressing). Installs pull this branch by default.
- `dev` holds every tool, including ones still being tested. To test on your own machine, reinstall from it
  (your saved settings are in `%APPDATA%`, so they are kept):

  ```
  pyrevit extensions delete EWTestSuite
  pyrevit extend ui EWTestSuite https://github.com/WolfemanX2/ew-test-suite.git --branch=dev --username=<your GitHub user> --password=<token>
  ```

  Then Reload. pyRevit **Update** then pulls `dev` on that machine.
  When a tool is ready, merge `dev` into `main`.

### Updating

pyRevit tab > **Update** pulls the latest version of this repository along with pyRevit itself.

### Alternative: install with git

```
git clone https://github.com/WolfemanX2/ew-test-suite.git "%APPDATA%\pyRevit\Extensions\EWTestSuite.extension"
```

If that folder isn't already a pyRevit extensions folder, add `%APPDATA%\pyRevit\Extensions` under
pyRevit Settings > Custom Extension Directories. Update later with `git pull` in that folder.

## Saved settings

Every config tool saves each user's settings in `%APPDATA%\pyRevit\EWTestSuite\`, so pyRevit updates and
reinstalls never overwrite or remove them. All of them are read and written by `lib/config_store.py`.

**Office defaults:** put a default file in `config/` and a user with no settings file yet starts from a copy of
it. Users who already have their own file keep it.

| Config tool | User's file | Office default in `config/` |
|---|---|---|
| Family Defaults Config | `circuit_config.json` | `circuit_config.default.json` |
| Link Clash - Config | `clash_rules.json` | `clash_rules.default.json` |
| Riser - Config, SLC Riser tab (symbols) | `riser_symbols.json` | `riser_symbols.default.json` |
| Riser - Config, SLC Riser tab (drawing settings) | `riser_settings.json` | `riser_settings.default.json` |
| Riser - Config, NAC Riser tab (symbols) | `nac_riser_symbols.json` | `nac_riser_symbols.default.json` |
| Riser - Config, NAC Riser tab (drawing settings) | `nac_riser_settings.json` | `nac_riser_settings.default.json` |

Family Defaults Config replaced Auto Conduit - Config, Address SLC - Config and Address NAC / Voice - Config, and is
read by the Auto Circuit tools (the tools in Obsolete still read those three files). The first time it opens, it is
filled from them.

To make everyone share one file instead, set the `*_PATH` setting at the top of that config's `lib` file to a
network location (then no default is copied).

### Auto Fix rules: office default + each user's copy

- `config/clash_rules.default.json` (in this repository) is the starting point. Edit it here on GitHub to
  change what everyone starts with. Lengths are in inches; the settings are the ones in the Link Clash - Config
  window. Valid choices for the text settings:
  - `elevation_mode`: `Never (jogs only)`, `Before trying jogs`, `After trying jogs`
  - `device_mode`: `Ask each time`, `Device remains in place`, `Adjust the device's elevation too`
  - `v_jog_min_angle` / `v_jog_max_angle`: multiples of 5 from 5 to 90
- Each user's own copy is `%APPDATA%\pyRevit\EWTestSuite\clash_rules.json`. It is created from the default
  the first time Link Clash or Link Clash - Config needs it, and after that only the Link Clash - Config tool changes it.
  pyRevit updates never overwrite it.
- Changing the default later does not change existing users' copies, except for settings their copy doesn't
  have yet (new settings in a later version are filled in from the default). Users can pick up the new default
  with **Reset to office defaults** in Link Clash - Config, then Save.
- To make everyone share one rules file instead, set `RULES_PATH` in `lib/clash_rules.py` to a network location.

### Other settings

- Conduit routing settings for Auto Conduit and Auto-Circuit (obstacle avoidance, stub and leg lengths, default
  elevation, highlight color, prompt wording) are at the top of `lib/conduit_routing.py`. Both tools use the same
  routing code from that file, so a change there applies to both.
- Family Defaults Config: `%APPDATA%\pyRevit\EWTestSuite\circuit_config.json` per user. To share it, set
  `CONFIG_PATH` in `lib/circuit_config.py` to a network location. Its **Detect Types in Project** button fills Mounting,
  Device Type and Conduit Type from each type's family / type name and parameters (asks blanks only or replace, then
  shows the changes to tick before they go in the table). A type that matches more than one kind of device (Head End,
  SLC or NAC - e.g. Panel # and SLC Address) is asked about first, once per family. The rules (keywords, required parameters, and the conduit
  type name for each Device Type) are on its **Detection Rules** tab and saved in the same file; the starting rules
  are in `lib/family_detection.py`.
- Riser symbol table: `%APPDATA%\pyRevit\EWTestSuite\riser_symbols.json` per user. pyRevit updates never
  overwrite it. To share it, set `TABLE_PATH` in `lib/slc_riser.py` to a network location.
- Riser drawing settings (view scale, spacing, devices per line, text offset): `%APPDATA%\pyRevit\EWTestSuite\riser_settings.json`
  per user, changed on the SLC Riser tab of Riser - Config. To share them, set `SETTINGS_PATH` in `lib/slc_riser.py` to a network location.
- NAC Riser symbol table and drawing settings: `nac_riser_symbols.json` and `nac_riser_settings.json` in the same folder,
  changed on the NAC Riser tab of Riser - Config. To share them, set `TABLE_PATH` / `SETTINGS_PATH` in `lib/nac_riser.py`.
- Clash statuses: `%APPDATA%\pyRevit\LinkClash\` per model. To share them, set `STATUS_DIR` in the Link
  Clash script to a network location.

## Versions

Each script has its version on line 2, and each lib file lists its last five changes at the top. Small
helpers every tool uses (ElementId numbers, the Fire Alarm Device check, Family : Type keys, picking an
element or its tag, the pick highlight) are in `lib/ew_common.py`; the windows and menus the addressing tools
share are in `lib/addressing_ui.py`.

| File | Version |
|---|---|
| Auto Circuit - SLC | v5 |
| Auto Circuit - NAC | v6 |
| Auto Circuit - Voice | v6 |
| lib/auto_circuit.py | v5 |
| lib/circuit_rules.py | v1 |
| lib/ew_common.py | v8 |
| lib/addressing_ui.py | v4 |
| lib/config_store.py | v2 |
| Family Defaults Config | v12 |
| lib/circuit_config.py | v5 |
| lib/circuit_config_editor.py | v12 |
| lib/family_detection.py | v3 |
| Auto Conduit | v6 |
| Auto-Circuit | v12 |
| Link Clash | v14 |
| Link Clash - Config | v6 |
| lib/mounting_rules.py | v2 |
| lib/conduit_routing.py | v4 |
| lib/clash_rules.py | v6 |
| Address SLC | v12 |
| lib/slc_session.py | v6 |
| lib/slc_addressing.py | v8 |
| lib/slc_config_editor.py | v4 |
| Address NAC | v6 |
| Address Voice | v6 |
| lib/nac_voice_addressing.py | v12 |
| lib/nac_voice_eol.py | v1 |
| lib/nac_voice_config_editor.py | v1 |
| lib/nac_voice_types.py | v11 |
| lib/conduit_trace.py | v8 |
| SLC Riser | v59 |
| NAC Riser | v29 |
| Riser - Config (was SLC Riser - Config) | v17 |
| NAC Coverage Checker | v3 |
| lib/slc_riser.py | v23 |
| lib/riser_tool.py | v32 |
| lib/nac_riser.py | v12 |
| lib/riser_config_editor.py | v11 |
| lib/riser_layout.py | v28 |
| Line Nuke | v4 |
| Consolidate Text Styles | v5 |
| Device Shared Params | v1 |
| Tag Shared Params | v1 |
| Transfer Family Params | v1 |
| lib/family_shared_params.py | v1 |
| VESDA Pipe Swap | v4 |
| VESDA Pipe Swap - Config | v1 |
| lib/vesda_pipe_swap.py | v4 |

## Tests

`tests\` holds checks of the libraries' own logic that run outside Revit with Python 3 (pyRevit ignores the
folder): `python tests/run_tests.py`. `tests/revit_stand_ins.py` stands in for Revit, pyRevit and .NET, so the
tests cover the settings files, the conduit tracing order and the shared helpers, not what Revit does with the
result. Run them after changing a lib file.
