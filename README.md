# EW Test Suite

pyRevit extension with conduit routing, link clash, device addressing, riser diagram, project cleanup and family parameter tools for Revit.

Every tool's settings window lives in the **Tool Configs** drop-down (its own panel at the end of the tab) and is named `<Tool Name> - Config`.

| Panel | Button | What it does |
|---|---|---|
| Conduit | Auto Conduit | Pick devices (or their tags) in order; plans and creates orthogonal conduit between them. |
| Circuit | Auto-Circuit | Conduit and addressing in one pass. Choose the circuit type: **NAC**, **Voice** or **SLC**. NAC / Voice: continue a circuit already in the project, continue from a selected device, or start a new one (the same choices and `N#-#.#` / `V#-#.#` addresses as Address NAC / Voice), then set the circuit limits (max current, default 1.2 A, and max device count; blank = no limit). SLC: continue a loop, continue from a selected device, or start a new one (`N#L#M000` / `N#L#D000`, as Address SLC). Then pick the new devices or their tags in order: the prompt shows the next address and the running totals, and a NAC / Voice pick that would go over a limit is asked about. When continuing, choose to continue from the circuit's last device or select a device on it. **Insert:** if devices follow the selected one along the conduit, the conduit to the next device is removed (it must be a straight run of conduit and fittings, no tee or junction box in between), new conduit runs from the selected device through the new devices back to that next device, and every device after them on the conduit is renumbered (SLC: re-numbered with the Address SLC - Config rules; devices already addressed keep their address count unless their rule fixes one). Devices on the circuit that come later by number but aren't on that conduit run are listed as possible duplicates. Elements that don't take an address of that kind (e.g. the power supply or panel) are connected but not addressed. Conduit is planned and created as in Auto Conduit; after a confirmation listing the addresses, the connected devices are addressed in order. NAC / Voice: Address and Circuit parameters, Notification Circuit on the new conduit (`N12` / `V12`, merged as `N16,V16`), and EOL on the last device of each circuit touched. SLC: each Family : Type by its rule in Address SLC - Config (fixed count, Address Options or asked, rounding), modules and detectors counted separately, unused address parameters cleared. Uses the existing Auto Conduit - Config, Address NAC / Voice - Config and Address SLC - Config files (no config of its own). One Undo; cancelling after picking undoes everything, including the removed conduit. |
| Clash | Link Clash | Tests the selection against MEP and structural elements in loaded Revit links. Results window with statuses, grouping, Show in 3D and Auto Fix. |
| Addressing | Address SLC | Pick devices (or their tags) in order; fills their `SLC Address` parameters (`SLC Address`, `SLC Address 2` ... `24`) with `N#L#M000` (modules) or `N#L#D000` (detectors), counted separately. Continues a loop already in the project, continues from a selected device (after the addresses written on it), or starts a new one. Each Family : Type follows its rule in Address SLC - Config; unused address parameters on the device are cleared. **Follow the conduit:** after a device is addressed (or after Continue From Selected), pick a conduit leaving it; every device connected downstream by conduit of that conduit type is listed for confirmation, then addressed in order of connection (at a split, the branch with fewer devices first). Conduit of any other type is not followed. Shift+Click opens Address SLC - Config. |
| Addressing | Address NAC | Pick devices (or their tags) in order; fills NAC Address / NAC Circuit (`N#-#.#` / `N#-#`). Continues a circuit already in the project, continues from a selected device, or starts a new one. After the first device, choose Manual (pick each device) or Automatic: you are told to select the conduit leaving the device in the direction to check, then address to a picked device, up to a max device count for the circuit, or up to a max current (each device's `Current` parameter, default 1.2 A); the conduit of the run gets Notification Circuit `N12` (shared with Voice as `N16,V16`). After an automatic run, choose Finish or Continue adding to the circuit. When finished, the last device gets NAC EOL = Yes, the rest No, and its Comments get the total current and estimated EOL voltage (20.4 V source, 14 AWG at 3.07 ohms/1000 ft, point to point, home run included when connected; warns below 17.25 V). Shift+Click to edit the lookup table. |
| Addressing | Address Voice | The same as Address NAC for Voice Address / Voice Circuit (`V#-#.#` / `V#-#`), Notification Circuit `V12` and Voice EOL; no current / voltage estimate. |
| Riser | SLC Riser | Select the panel, then pick the first device of each loop (either can be picked by its tag) (Esc when finished; Esc with none picked follows every run from the panel). Follows the conduit from each first device away from the panel and draws a one-line riser in a new drafting view named `<LEVEL> - SLC RISER - <PANEL #>` (the panel's level and `Panel #` parameter, in capitals): every Fire Alarm Device with an SLC address (`SLC Address`, `SLC Address 2` ... `24`) in order of connection, one row per conduit run, labeled with its loop as a letter (`L1` = A, `L2` = B ..., read from the `N#L#M#` / `N#L#D#` addresses), full address underneath (several addresses on one device show the first and last on two lines, `first-` / `last`; the text is at 45 degrees, right justified, hanging below the riser line, its top corner 1" under its device; devices 6' apart; view scale 1/8" = 1'-0"). Conduit splits become T-tap rows. Only conduit of the chosen types is followed (the types at the first devices are ticked to start with), so tees onto other conduit types are ignored. A device with a value in `Panel #` shows it above its symbol in 5/64" centered text. A type with no symbol in the table is asked about and the choice is saved. |
| Project Cleanup | Line Nuke | Creates 15 standard Solid line styles named `Detail Line - <Color> - <Size>` (Black, Blue, Red, Green, Magenta; Thin = weight 1, Medium = 3, Thick = 6), then moves the lines of every other line style with the same color, weight and pattern onto the standard style and deletes the duplicate. A second mode also merges the remaining duplicate line styles and renames them `Color - Weight - Pattern`. Built-in styles are never changed; you pick styles to exclude and confirm a preview first (No undoes everything). |
| Project Cleanup | Consolidate Text Styles | Groups text styles by text size (within a tolerance entered as a fraction or decimal of an inch) and merges each group into its most-used style: text notes and schedule text using the other styles are switched to it and the other styles are deleted. The kept style is rounded to the nearest 1/64" and renamed `<size> <font> <modifiers>` (e.g. `1/8" Arial Bold`). Only the size is compared, so merged text takes on the kept style's font and formatting. You pick styles to exclude and confirm a preview first. |
| Families | Device Shared Params | Adds a batch of shared parameters from the shared parameter file to device families: the family open in the Family Editor, or model families picked from the project (Fire Alarm Devices first), which are opened, changed and reloaded keeping project values. Choose Instance or Type (all, or pick which are Type) and the Properties group. Parameters already in a family are skipped. A set can be saved as a preset (`%APPDATA%\pyRevit\EWTestSuite\family_param_presets.json`). |
| Families | Tag Shared Params | Same for tag families. **For labels** adds the shared parameter to the tag family so a label can use it (edit the label to show it); **As family parameters** adds Instance/Type parameters of the tag itself (e.g. Yes/No visibility switches). Presets are kept separately from the device tool's. |
| Tool Configs | Auto Conduit - Config | Per Fire Alarm Device family: Wall/Ceiling mounting and the conduit type for runs leaving it. |
| Tool Configs | Link Clash - Config | Distances, allowed fix types, jog angles and elevation rules used by Auto Fix. |
| Tool Configs | Address SLC - Config | Rules table: for each Family : Type, Device Type (Module or Detector), Number of Addresses (blank = ask), Address Options (named choices typed as `"Single Zone":6, "Dual Zone":12`) and Round Up To Multiple Of (any whole number). **Load Default Config...** copies a default config file into your own table without changing the default. |
| Tool Configs | Address NAC / Voice - Config | Lookup table for Address NAC and Address Voice: each Family : Type is NAC Only, Voice Only, or NAC and Voice. |
| Tool Configs | SLC Riser - Config | Drawing settings (drafting view scale, spacing between devices, devices before wrapping, wrap rounding, address text offset) and the lookup table of the Generic Annotation or Detail Item type drawn for each Family : Type. |

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
| Auto-Circuit | v3 |
| Link Clash | v11 |
| Link Clash - Config | v6 |
| lib/mounting_rules.py | v1 |
| lib/clash_rules.py | v5 |
| Address SLC | v2 |
| Address SLC - Config | v3 |
| lib/slc_addressing.py | v2 |
| lib/slc_config_editor.py | v2 |
| Address NAC | v1 |
| Address Voice | v1 |
| lib/nac_voice_addressing.py | v1 |
| Address NAC / Voice - Config | v2 |
| lib/nac_voice_types.py | v6 |
| lib/conduit_trace.py | v3 |
| SLC Riser | v13 |
| SLC Riser - Config | v4 |
| lib/slc_riser.py | v5 |
| lib/riser_layout.py | v9 |
| Line Nuke | v3 |
| Consolidate Text Styles | v4 |
