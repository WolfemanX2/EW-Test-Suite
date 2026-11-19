# EW Test Suite

pyRevit extension with conduit routing, link clash, device addressing, riser diagram, strobe coverage, project cleanup and family parameter tools for Revit.

Every tool's settings window lives in the **Tool Configs** drop-down (its own panel at the end of the tab) and is named `<Tool Name> - Config`.

## Tools

### <picture><source media="(prefers-color-scheme: dark)" srcset="EW%20Test%20Suite.tab/Conduit.panel/AutoConduit.pushbutton/icon.dark.png"><img src="EW%20Test%20Suite.tab/Conduit.panel/AutoConduit.pushbutton/icon.png" width="32" height="32" alt=""></picture> Auto Conduit
- Automatically draws conduit between devices in order of selection.

#### Related Tools
- **Auto-Circuit:** draws conduit the same way and also addresses the devices
- **Auto Conduit - Config:** sets each family's mounting (Wall/Ceiling) and conduit type

### <picture><source media="(prefers-color-scheme: dark)" srcset="EW%20Test%20Suite.tab/Circuit.panel/AutoCircuit.pushbutton/icon.dark.png"><img src="EW%20Test%20Suite.tab/Circuit.panel/AutoCircuit.pushbutton/icon.png" width="32" height="32" alt=""></picture> Auto-Circuit
- Draws conduit between devices and addresses them based on order of selection. It can also insert new devices into an existing circuit and renumber the devices after them.

#### Related Tools
- **Auto Conduit:** draws the conduit the same way, without addressing
- **Address SLC**, **Address NAC** and **Address Voice:** address devices with the same rules, without drawing conduit
- **Auto Conduit - Config**, **Address SLC - Config** and **Address NAC / Voice - Config:** Auto-Circuit uses their settings and has no config of its own

### <picture><source media="(prefers-color-scheme: dark)" srcset="EW%20Test%20Suite.tab/Clash.panel/LinkClash.pushbutton/icon.dark.png"><img src="EW%20Test%20Suite.tab/Clash.panel/LinkClash.pushbutton/icon.png" width="32" height="32" alt=""></picture> Link Clash
- Checks selected elements for clashes with MEP and structural elements in loaded Revit links and lists them in a results window with statuses. Auto Fix can shift or jog a clashing conduit to clear it.

#### Related Tools
- **Link Clash - Config:** sets the distances and allowed fixes that Auto Fix uses

### <picture><source media="(prefers-color-scheme: dark)" srcset="EW%20Test%20Suite.tab/Addressing.panel/AddressSlc.pushbutton/icon.dark.png"><img src="EW%20Test%20Suite.tab/Addressing.panel/AddressSlc.pushbutton/icon.png" width="32" height="32" alt=""></picture> Address SLC
- Fills in the SLC addresses of devices in the order you select them. It can also address them automatically by following the conduit downstream from a selected device.

#### Related Tools
- **Address NAC** and **Address Voice:** the same addressing steps, for NAC and Voice devices
- **Auto-Circuit:** draws the conduit and addresses SLC devices using the same rules
- **SLC Riser:** draws a riser diagram from these addresses
- **Address SLC - Config:** sets the address rules for each device type

### <picture><source media="(prefers-color-scheme: dark)" srcset="EW%20Test%20Suite.tab/Addressing.panel/AddressNac.pushbutton/icon.dark.png"><img src="EW%20Test%20Suite.tab/Addressing.panel/AddressNac.pushbutton/icon.png" width="32" height="32" alt=""></picture> Address NAC
- Fills in NAC addresses and circuits on devices in the order you select them, or automatically along the conduit from a selected device. It also marks the end-of-line device and estimates the circuit's current and EOL voltage.

#### Related Tools
- **Address Voice:** the same tool for Voice devices
- **Address SLC:** the same addressing steps, for SLC devices
- **Auto-Circuit:** draws the conduit and addresses NAC devices using the same rules
- **Address NAC / Voice - Config:** sets whether each device type is NAC, Voice or both

### <picture><source media="(prefers-color-scheme: dark)" srcset="EW%20Test%20Suite.tab/Addressing.panel/AddressVoice.pushbutton/icon.dark.png"><img src="EW%20Test%20Suite.tab/Addressing.panel/AddressVoice.pushbutton/icon.png" width="32" height="32" alt=""></picture> Address Voice
- Fills in Voice addresses and circuits on devices in the order you select them, or automatically along the conduit from a selected device. It also marks the end-of-line device.

#### Related Tools
- **Address NAC:** the same tool for NAC devices
- **Address SLC:** the same addressing steps, for SLC devices
- **Auto-Circuit:** draws the conduit and addresses Voice devices using the same rules
- **Address NAC / Voice - Config:** sets whether each device type is NAC, Voice or both

### <picture><source media="(prefers-color-scheme: dark)" srcset="EW%20Test%20Suite.tab/Riser.panel/SlcRiser.pushbutton/icon.dark.png"><img src="EW%20Test%20Suite.tab/Riser.panel/SlcRiser.pushbutton/icon.png" width="32" height="32" alt=""></picture> SLC Riser
- Draws a one-line SLC riser diagram in a drafting view, with each device shown in order of connection along the conduit and labeled with its SLC address.

#### Related Tools
- **Address SLC:** fills in the SLC addresses the riser shows
- **SLC Riser - Config:** sets the drawing settings and the symbols used for each device type

### <picture><source media="(prefers-color-scheme: dark)" srcset="EW%20Test%20Suite.tab/Coverage.panel/NACCoverageChecker.pushbutton/icon.dark.png"><img src="EW%20Test%20Suite.tab/Coverage.panel/NACCoverageChecker.pushbutton/icon.png" width="32" height="32" alt=""></picture> NAC Coverage Checker
- Shows strobe coverage on a floor plan, for the whole view or one room, based on each device's candela. Points that a strobe can't see because something in the model or a loaded link is in the way are shown as blocked.

#### Related Tools
- **Auto Conduit - Config:** its Wall/Ceiling setting decides how each device's coverage is laid out

### <picture><source media="(prefers-color-scheme: dark)" srcset="EW%20Test%20Suite.tab/Project%20Cleanup.panel/LineNuke.pushbutton/icon.dark.png"><img src="EW%20Test%20Suite.tab/Project%20Cleanup.panel/LineNuke.pushbutton/icon.png" width="32" height="32" alt=""></picture> Line Nuke
- Creates the 15 standard "Detail Line - Color - Size" line styles and merges any line styles with the same color, weight and pattern into them.

#### Related Tools
- **Consolidate Text Styles:** the same kind of cleanup for text styles

### <picture><source media="(prefers-color-scheme: dark)" srcset="EW%20Test%20Suite.tab/Project%20Cleanup.panel/ConsolidateTextStyles.pushbutton/icon.dark.png"><img src="EW%20Test%20Suite.tab/Project%20Cleanup.panel/ConsolidateTextStyles.pushbutton/icon.png" width="32" height="32" alt=""></picture> Consolidate Text Styles
- Merges text styles that have the same text size into one style per size and renames it by size, font and modifiers (e.g. 1/8" Arial Bold).

#### Related Tools
- **Line Nuke:** the same kind of cleanup for line styles

### <picture><source media="(prefers-color-scheme: dark)" srcset="EW%20Test%20Suite.tab/Families.panel/DeviceSharedParams.pushbutton/icon.dark.png"><img src="EW%20Test%20Suite.tab/Families.panel/DeviceSharedParams.pushbutton/icon.png" width="32" height="32" alt=""></picture> Device Shared Params
- Adds a batch of shared parameters to device families, either the family open in the Family Editor or families picked from the project.

#### Related Tools
- **Tag Shared Params:** the same tool for tag families
- **Transfer Family Params:** copies parameters from one family to others

### <picture><source media="(prefers-color-scheme: dark)" srcset="EW%20Test%20Suite.tab/Families.panel/TagSharedParams.pushbutton/icon.dark.png"><img src="EW%20Test%20Suite.tab/Families.panel/TagSharedParams.pushbutton/icon.png" width="32" height="32" alt=""></picture> Tag Shared Params
- Adds a batch of shared parameters to tag families, either for use in labels or as parameters of the tag itself.

#### Related Tools
- **Device Shared Params:** the same tool for device families
- **Transfer Family Params:** copies parameters from one family to others

### <picture><source media="(prefers-color-scheme: dark)" srcset="EW%20Test%20Suite.tab/Families.panel/TransferFamilyParams.pushbutton/icon.dark.png"><img src="EW%20Test%20Suite.tab/Families.panel/TransferFamilyParams.pushbutton/icon.png" width="32" height="32" alt=""></picture> Transfer Family Params
- Copies the parameters you choose, with their formulas and values if you want, from one open family to one or more other open families.

#### Related Tools
- **Device Shared Params** and **Tag Shared Params:** add shared parameters from the shared parameter file to families

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
  (back up `lib\mounting_rules.json` first; it lives in the extension folder and is removed with it):

  ```
  pyrevit extensions delete EWTestSuite
  pyrevit extend ui EWTestSuite https://github.com/WolfemanX2/ew-test-suite.git --branch=dev --username=<your GitHub user> --password=<token>
  ```

  Put `mounting_rules.json` back in `lib`, then Reload. pyRevit **Update** then pulls `dev` on that machine.
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

### Address SLC - Config: default + each user's copy

- Each user's own table is `%APPDATA%\MyTools\AddressCounts.json`, the same file and format as the
  standalone Address Devices add-in, so both can be used side by side. Only the Address SLC - Config tool
  changes it; pyRevit updates never overwrite it.
- `config/address_config.default.json` (in this repository) is the office default. It is empty until rules are
  put in it: set them up in Address SLC - Config, click **Open Table File**, and paste that file's contents here
  on GitHub. A user with no table yet then starts from a copy of it.
- **Load Default Config...** in Address SLC - Config opens at that file (or at the last default file the user
  chose, which can be anywhere), and after a confirmation replaces the user's table with its rules. The default
  file is only read. The previous table is kept as `AddressCounts.backup.json`.
- To make everyone edit one table instead, set `TABLE_PATH` in `lib/slc_addressing.py` to a network location.

### Other settings

- `lib/mounting_rules.json` (Auto Conduit - Config). Not part of the repository, so updates never overwrite it.
  To share it, set `RULES_PATH` in `lib/mounting_rules.py` to a network location.
- NAC / Voice lookup table: `%APPDATA%\pyRevit\EWTestSuite\nac_voice_types.json` per user. pyRevit updates never
  overwrite it. To share it, set `TABLE_PATH` in `lib/nac_voice_types.py` to a network location.
- Riser symbol table: `%APPDATA%\pyRevit\EWTestSuite\riser_symbols.json` per user. pyRevit updates never
  overwrite it. To share it, set `TABLE_PATH` in `lib/slc_riser.py` to a network location.
- Riser drawing settings (view scale, spacing, devices per line, text offset): `%APPDATA%\pyRevit\EWTestSuite\riser_settings.json`
  per user, changed in SLC Riser - Config. To share them, set `SETTINGS_PATH` in `lib/slc_riser.py` to a network location.
- Clash statuses: `%APPDATA%\pyRevit\LinkClash\` per model. To share them, set `STATUS_DIR` in the Link
  Clash script to a network location.

## Versions

Each script has its version on line 2.

| File | Version |
|---|---|
| Auto Conduit | v4 |
| Auto Conduit - Config | v2 |
| Auto-Circuit | v4 |
| Link Clash | v11 |
| Link Clash - Config | v6 |
| lib/mounting_rules.py | v1 |
| lib/clash_rules.py | v5 |
| Address SLC | v5 |
| Address SLC - Config | v3 |
| lib/slc_addressing.py | v2 |
| lib/slc_config_editor.py | v2 |
| Address NAC | v2 |
| Address Voice | v2 |
| lib/nac_voice_addressing.py | v2 |
| Address NAC / Voice - Config | v2 |
| lib/nac_voice_types.py | v6 |
| lib/conduit_trace.py | v3 |
| SLC Riser | v30 |
| SLC Riser - Config | v7 |
| NAC Coverage Checker | v2 |
| lib/slc_riser.py | v8 |
| lib/riser_layout.py | v17 |
| Line Nuke | v3 |
| Consolidate Text Styles | v4 |
