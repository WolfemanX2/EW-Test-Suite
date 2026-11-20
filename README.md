# EW Test Suite

pyRevit extension with conduit routing, link clash, device addressing, riser diagram, strobe coverage, project cleanup and family parameter tools for Revit.

Every tool's settings window lives in the **Tool Configs** drop-down (its own panel at the end of the tab) and is named `<Tool Name> - Config`.

The **EW Production Suite** tab holds the **Family QAQC** panel (Family Placer) and the Obsolete panel.

Tools being replaced are kept in the **Obsolete** panel on the separate **EW Production Suite** tab, in three drop-downs:
**Old Tools** (Auto Conduit, Auto-Circuit, Address SLC, Address NAC, Address Voice, NAC Coverage Checker),
**Template Cleanup** (Line Nuke, Consolidate Text Styles) and **Parameter Tools** (the family parameter tools).

## Tools

### <picture><source media="(prefers-color-scheme: dark)" srcset="EW%20Production%20Suite.tab/Family%20QAQC.panel/FamilyPlacer.pushbutton/icon.dark.png"><img src="EW%20Production%20Suite.tab/Family%20QAQC.panel/FamilyPlacer.pushbutton/icon.png" width="32" height="32" alt=""></picture> Family Placer
- Places one of every loaded type of a chosen category in a grid in the active plan view: one row per family, one column per type, 6 ft apart unless you enter another spacing. Model families are placed 5.5 ft above the level, and each row is labeled with its family name. Families that need a host or a curve are skipped and listed.

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
- **SLC Riser - Config:** sets the drawing settings and the symbols used for each device type

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
| SLC Riser - Config (symbols) | `riser_symbols.json` | `riser_symbols.default.json` |
| SLC Riser - Config (drawing settings) | `riser_settings.json` | `riser_settings.default.json` |

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
  `CONFIG_PATH` in `lib/circuit_config.py` to a network location.
- Riser symbol table: `%APPDATA%\pyRevit\EWTestSuite\riser_symbols.json` per user. pyRevit updates never
  overwrite it. To share it, set `TABLE_PATH` in `lib/slc_riser.py` to a network location.
- Riser drawing settings (view scale, spacing, devices per line, text offset): `%APPDATA%\pyRevit\EWTestSuite\riser_settings.json`
  per user, changed in SLC Riser - Config. To share them, set `SETTINGS_PATH` in `lib/slc_riser.py` to a network location.
- Clash statuses: `%APPDATA%\pyRevit\LinkClash\` per model. To share them, set `STATUS_DIR` in the Link
  Clash script to a network location.

## Versions

Each script has its version on line 2, and each lib file lists its last five changes at the top. Small
helpers every tool uses (ElementId numbers, the Fire Alarm Device check, Family : Type keys, picking an
element or its tag, the pick highlight) are in `lib/ew_common.py`; the windows and menus the addressing tools
share are in `lib/addressing_ui.py`.

| File | Version |
|---|---|
| Auto Circuit - SLC | v1 |
| Auto Circuit - NAC | v1 |
| Auto Circuit - Voice | v1 |
| lib/auto_circuit.py | v1 |
| lib/circuit_rules.py | v1 |
| lib/ew_common.py | v3 |
| lib/addressing_ui.py | v3 |
| lib/config_store.py | v1 |
| Family Defaults Config | v7 |
| lib/circuit_config.py | v3 |
| lib/circuit_config_editor.py | v7 |
| Auto Conduit | v6 |
| Auto-Circuit | v12 |
| Link Clash | v13 |
| Link Clash - Config | v6 |
| lib/mounting_rules.py | v2 |
| lib/conduit_routing.py | v3 |
| lib/clash_rules.py | v6 |
| Address SLC | v12 |
| lib/slc_session.py | v4 |
| lib/slc_addressing.py | v8 |
| lib/slc_config_editor.py | v4 |
| Address NAC | v6 |
| Address Voice | v6 |
| lib/nac_voice_addressing.py | v9 |
| lib/nac_voice_eol.py | v1 |
| lib/nac_voice_config_editor.py | v1 |
| lib/nac_voice_types.py | v11 |
| lib/conduit_trace.py | v5 |
| SLC Riser | v34 |
| SLC Riser - Config | v7 |
| NAC Coverage Checker | v3 |
| lib/slc_riser.py | v13 |
| lib/riser_layout.py | v20 |
| Line Nuke | v4 |
| Consolidate Text Styles | v5 |
| Device Shared Params | v1 |
| Tag Shared Params | v1 |
| Transfer Family Params | v1 |
| lib/family_shared_params.py | v1 |
