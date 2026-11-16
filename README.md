# EW Test Suite

pyRevit extension with conduit routing, link clash, device addressing and riser diagram tools for Revit.

| Panel | Button | What it does |
|---|---|---|
| Conduit | Auto Conduit | Pick devices (or their tags) in order; plans and creates orthogonal conduit between them. |
| Conduit | Routing Preferences | Per Fire Alarm Device family: Wall/Ceiling mounting and the conduit type for runs leaving it. |
| Clash | Link Clash | Tests the selection against MEP and structural elements in loaded Revit links. Results window with statuses, grouping, Show in 3D and Auto Fix. |
| Clash | Auto Fix Rules | Distances, allowed fix types, jog angles and elevation rules used by Auto Fix. |
| Addressing | Address NAC / Voice | Pick devices (or their tags) in order; fills NAC Address / NAC Circuit (`N#-#.#` / `N#-#`) and Voice Address / Voice Circuit (`V#-#.#` / `V#-#`). Continues a circuit already in the project, continues from a selected device, or starts a new one; NAC and Voice count separately. Shift+Click to edit the lookup table. |
| Addressing | NAC / Voice Types | Lookup table: each Family : Type is NAC Only, Voice Only, or NAC and Voice. |
| Riser | SLC Riser | Select the panel, then pick the first device of each loop (Esc when finished; Esc with none picked follows every run from the panel). Follows the conduit from each first device away from the panel and draws a one-line riser in a new drafting view named `<LEVEL> - SLC RISER - <PANEL #>` (the panel's level and `Panel #` parameter, in capitals): every Fire Alarm Device with an SLC address (`SLC Address`, `SLC Address 2` ... `24`) in order of connection, one row per conduit run, labeled with its loop (`L#`, read from the `N#L#M#` / `N#L#D#` addresses), full address underneath (several addresses on one device show the first and last on two lines, `first-` / `last`; the text is at 45 degrees, right justified, hanging below the riser line, its top corner 1" under its device; devices 6' apart; view scale 1/8" = 1'-0"). Conduit splits become T-tap rows. A type with no symbol in the table is asked about and the choice is saved. |
| Riser | Riser Symbols | Lookup table: the Generic Annotation or Detail Item type drawn for each Family : Type. |

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
  change what everyone starts with. Lengths are in inches; the settings are the ones in the Auto Fix Rules
  window. Valid choices for the text settings:
  - `elevation_mode`: `Never (jogs only)`, `Before trying jogs`, `After trying jogs`
  - `device_mode`: `Ask each time`, `Device remains in place`, `Adjust the device's elevation too`
  - `v_jog_min_angle` / `v_jog_max_angle`: multiples of 5 from 5 to 90
- Each user's own copy is `%APPDATA%\pyRevit\EWTestSuite\clash_rules.json`. It is created from the default
  the first time Link Clash or Auto Fix Rules needs it, and after that only the Auto Fix Rules tool changes it.
  pyRevit updates never overwrite it.
- Changing the default later does not change existing users' copies, except for settings their copy doesn't
  have yet (new settings in a later version are filled in from the default). Users can pick up the new default
  with **Reset to office defaults** in Auto Fix Rules, then Save.
- To make everyone share one rules file instead, set `RULES_PATH` in `lib/clash_rules.py` to a network location.

### Other settings

- `lib/mounting_rules.json` (Routing Preferences). Not part of the repository, so updates never overwrite it.
  To share it, set `RULES_PATH` in `lib/mounting_rules.py` to a network location.
- NAC / Voice lookup table: `%APPDATA%\pyRevit\EWTestSuite\nac_voice_types.json` per user. pyRevit updates never
  overwrite it. To share it, set `TABLE_PATH` in `lib/nac_voice_types.py` to a network location.
- Riser symbol table: `%APPDATA%\pyRevit\EWTestSuite\riser_symbols.json` per user. pyRevit updates never
  overwrite it. To share it, set `TABLE_PATH` in `lib/slc_riser.py` to a network location.
- Riser drawing sizes (view scale, devices per line, spacing) are the settings at the top of the SLC Riser script.
- Clash statuses: `%APPDATA%\pyRevit\LinkClash\` per model. To share them, set `STATUS_DIR` in the Link
  Clash script to a network location.

## Versions

Each script has its version on line 2.

| File | Version |
|---|---|
| Auto Conduit | v4 |
| Routing Preferences | v1 |
| Link Clash | v11 |
| Auto Fix Rules | v5 |
| lib/mounting_rules.py | v1 |
| lib/clash_rules.py | v5 |
| Address NAC / Voice | v2 |
| NAC / Voice Types | v1 |
| lib/nac_voice_types.py | v1 |
| SLC Riser | v8 |
| Riser Symbols | v1 |
| lib/slc_riser.py | v2 |
| lib/riser_layout.py | v7 |
