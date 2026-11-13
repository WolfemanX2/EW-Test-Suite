# EW Test Suite

pyRevit extension with conduit routing and link clash tools for Revit.

| Panel | Button | What it does |
|---|---|---|
| Conduit | Auto Conduit | Pick devices (or their tags) in order; plans and creates orthogonal conduit between them. |
| Conduit | Routing Preferences | Per Fire Alarm Device family: Wall/Ceiling mounting and the conduit type for runs leaving it. |
| Clash | Link Clash | Tests the selection against MEP and structural elements in loaded Revit links. Results window with statuses, grouping, Show in 3D and Auto Fix. |
| Clash | Auto Fix Rules | Distances, allowed fix types, jog angles and elevation rules used by Auto Fix. |

## Install

This repository is private, so pyRevit needs a GitHub personal access token to download it.

1. Create a token on GitHub: **Settings > Developer settings > Personal access tokens > Fine-grained tokens**.
   Give it access to this repository only, with **Contents: Read-only**.
2. Open a Command Prompt and run (one line):

   ```
   pyrevit extend ui EWTestSuite https://github.com/WolfemanX2/ew-test-suite.git --username=<your GitHub user> --password=<token>
   ```

3. Reload pyRevit (pyRevit tab > Reload). The **EW Test Suite** tab appears.

### Updating

pyRevit tab > **Update** pulls the latest version of this repository along with pyRevit itself.

### Alternative: install with git

```
git clone https://github.com/WolfemanX2/ew-test-suite.git "%APPDATA%\pyRevit\Extensions\EWTestSuite.extension"
```

If that folder isn't already a pyRevit extensions folder, add `%APPDATA%\pyRevit\Extensions` under
pyRevit Settings > Custom Extension Directories. Update later with `git pull` in that folder.

## Saved settings

These files are created by the tools and are not part of the repository, so updates never overwrite them:

- `lib/mounting_rules.json` (Routing Preferences)
- `lib/clash_rules.json` (Auto Fix Rules)
- Clash statuses: `%APPDATA%\pyRevit\LinkClash\` per model

To share settings across a team, set `RULES_PATH` in `lib/mounting_rules.py` / `lib/clash_rules.py`, or
`STATUS_DIR` in the Link Clash script, to a network location.

## Versions

Each script has its version on line 2.

| File | Version |
|---|---|
| Auto Conduit | v3 |
| Routing Preferences | v1 |
| Link Clash | v10 |
| Auto Fix Rules | v3 |
| lib/mounting_rules.py | v1 |
| lib/clash_rules.py | v3 |
