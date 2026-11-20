# -*- coding: utf-8 -*-
# Change log (last change first):
#   v2 - Family Audit v3: FamilyLoadOptions moved to lib/family_qaqc.py (imported from there).
"""Shared code for the Device Shared Params and Tag Shared Params tools - version v2.

Adds a batch of shared parameters (from the shared parameter file) to:
  - the family open in the Family Editor, or
  - families picked from the project, which are opened, changed and reloaded
    (parameter values already in the project are kept).

Presets (a named set of parameters with their Instance/Type choice and group) are saved per user in
%APPDATA%\\pyRevit\\EWTestSuite\\family_param_presets.json.
"""
import os
import json
from collections import OrderedDict

from pyrevit import DB, forms, script

PRESET_FILE = os.path.join(os.getenv("APPDATA") or os.path.expanduser("~"),
                           "pyRevit", "EWTestSuite", "family_param_presets.json")
OTHER_GROUP = ("Other", "")

MODE_FAMILY = "family"   # FamilyManager parameter (Instance or Type)
MODE_LABEL = "label"     # tag families only: shared parameter in the family, available to labels


# --- presets ----------------------------------------------------------------
def load_presets(kind):
    try:
        with open(PRESET_FILE) as f:
            return json.load(f).get(kind, {})
    except Exception:
        return {}


def save_preset(kind, name, preset):
    data = {}
    try:
        with open(PRESET_FILE) as f:
            data = json.load(f)
    except Exception:
        pass
    data.setdefault(kind, {})[name] = preset
    _write(data)


def delete_preset(kind, name):
    try:
        with open(PRESET_FILE) as f:
            data = json.load(f)
    except Exception:
        return
    data.get(kind, {}).pop(name, None)
    _write(data)


def _write(data):
    folder = os.path.dirname(PRESET_FILE)
    if not os.path.isdir(folder):
        os.makedirs(folder)
    with open(PRESET_FILE, "w") as f:
        json.dump(data, f, indent=2, sort_keys=True)


# --- shared parameter file --------------------------------------------------
class SharedParamFile(object):
    """Opens the shared parameter file; if none is set, asks for one and restores the setting on close()."""

    def __init__(self, app):
        self.app = app
        self.original = app.SharedParametersFilename
        self.changed = False
        self.file = None
        try:
            self.file = app.OpenSharedParameterFile()
        except Exception:
            self.file = None
        if self.file is None:
            path = forms.pick_file(file_ext="txt", title="No shared parameter file is set - pick one")
            if path:
                app.SharedParametersFilename = path
                self.changed = True
                self.file = app.OpenSharedParameterFile()

    @property
    def path(self):
        return self.app.SharedParametersFilename

    def definitions(self):
        """[(group name, ExternalDefinition)] in file order."""
        out = []
        for g in self.file.Groups:
            for d in g.Definitions:
                out.append((g.Name, d))
        return out

    def close(self):
        if self.changed:
            try:
                self.app.SharedParametersFilename = self.original or ""
            except Exception:
                pass


def guid_str(d):
    return str(d.GUID).lower()


def spec_label(d):
    try:
        return DB.LabelUtils.GetLabelForSpec(d.GetDataType())
    except Exception:
        return ""


# --- parameter groups (Properties palette headings) ------------------------
def param_groups():
    """[(label, ForgeTypeId.TypeId)] sorted, 'Other' last. Revit 2022+."""
    seen, out = set(), []
    for attr in dir(DB.GroupTypeId):
        if attr.startswith("_"):
            continue
        try:
            v = getattr(DB.GroupTypeId, attr)
        except Exception:
            continue
        if not isinstance(v, DB.ForgeTypeId) or not v.TypeId:
            continue
        try:
            label = DB.LabelUtils.GetLabelForGroup(v)
        except Exception:
            continue
        if label and label not in seen:
            seen.add(label)
            out.append((label, v.TypeId))
    out.sort(key=lambda x: x[0].lower())
    out.append(OTHER_GROUP)
    return out


def group_label(type_id):
    for label, tid in param_groups():
        if tid == type_id:
            return label
    return type_id or "Other"


# --- picking ----------------------------------------------------------------
def pick_definitions(spf):
    """Multiselect from the shared parameter file, with a drop-down of its groups."""
    defs = spf.definitions()
    if not defs:
        forms.alert("The shared parameter file has no parameters:\n{}".format(spf.path))
        return None
    by_label, context = {}, OrderedDict()
    context["<All groups>"] = []
    for gname, d in defs:
        dtype = spec_label(d)
        label = u"{}   [{}{}]".format(d.Name, gname, (u" - " + dtype) if dtype else u"")
        by_label[label] = d
        context["<All groups>"].append(label)
        context.setdefault(gname, []).append(label)
    picked = forms.SelectFromList.show(
        context, title="Shared parameters to add  ({})".format(os.path.basename(spf.path)),
        multiselect=True, group_selector_title="Shared parameter group:",
        button_name="Next", width=650, height=600)
    if not picked:
        return None
    return [by_label[p] for p in picked]


def pick_instance_type(defs):
    """{guid: is_instance} or None."""
    choice = forms.CommandSwitchWindow.show(
        ["All Instance", "All Type", "Choose which are Type..."],
        message="Add the {} parameter(s) as:".format(len(defs)))
    if not choice:
        return None
    if choice == "All Instance":
        return dict((guid_str(d), True) for d in defs)
    if choice == "All Type":
        return dict((guid_str(d), False) for d in defs)
    names = OrderedDict((d.Name + u"   {" + guid_str(d)[:8] + u"}", d) for d in defs)
    typed = forms.SelectFromList.show(
        list(names.keys()), title="Check the parameters to add as TYPE (the rest are Instance)",
        multiselect=True, button_name="Next", width=550, height=500)
    if typed is None:
        return None
    typed = set(guid_str(names[t]) for t in typed)
    return dict((guid_str(d), guid_str(d) not in typed) for d in defs)


def pick_group(default_label=None):
    groups = param_groups()
    labels = [g[0] for g in groups]
    picked = forms.SelectFromList.show(
        labels, title="Properties group for the new parameters",
        multiselect=False, button_name="Next", width=400, height=550)
    if not picked:
        return None
    return dict(groups)[picked]


# --- applying ---------------------------------------------------------------
def apply_to_family_doc(fdoc, defs, instance_map, group_type_id, mode):
    """Adds the parameters to an open family document. Call inside a transaction on fdoc.
    Returns [(parameter name, result text, added bool)]."""
    fm = fdoc.FamilyManager
    existing_by_guid, existing_by_name = {}, {}
    for p in fm.Parameters:
        existing_by_name[p.Definition.Name] = p
        try:
            if p.IsShared:
                existing_by_guid[str(p.GUID).lower()] = p
        except Exception:
            pass
    group = DB.ForgeTypeId(group_type_id or "")
    results = []
    for d in defs:
        g = guid_str(d)
        if mode == MODE_LABEL:
            if DB.SharedParameterElement.Lookup(fdoc, d.GUID) is not None or g in existing_by_guid:
                results.append((d.Name, "Already in family", False))
                continue
            try:
                DB.SharedParameterElement.Create(fdoc, d)
                results.append((d.Name, "Added (for labels)", True))
            except Exception as e:
                results.append((d.Name, "Failed: {}".format(e), False))
            continue

        if g in existing_by_guid:
            p = existing_by_guid[g]
            results.append((d.Name, "Already in family ({})".format("Instance" if p.IsInstance else "Type"), False))
            continue
        if d.Name in existing_by_name:
            results.append((d.Name, "Skipped: a different parameter already has this name", False))
            continue
        is_inst = instance_map.get(g, True)
        try:
            fm.AddParameter(d, group, is_inst)
            results.append((d.Name, "Added ({})".format("Instance" if is_inst else "Type"), True))
        except Exception as e:
            results.append((d.Name, "Failed: {}".format(e), False))
    return results


from family_qaqc import FamilyLoadOptions     # lib/family_qaqc.py


def pick_project_families(doc, is_match, title):
    """Multiselect of editable families matching is_match(family), with a category drop-down."""
    fams = [f for f in DB.FilteredElementCollector(doc).OfClass(DB.Family)
            if f.IsEditable and not f.IsInPlace and f.FamilyCategory is not None and is_match(f)]
    if not fams:
        forms.alert("No matching editable families are loaded in this project.")
        return None
    by_label, cats = {}, {}
    for f in fams:
        cat = f.FamilyCategory.Name
        label = u"{} : {}".format(cat, f.Name)
        by_label[label] = f
        cats.setdefault(cat, []).append(label)
    context = OrderedDict()
    if "Fire Alarm Devices" in cats:
        context["Fire Alarm Devices"] = sorted(cats["Fire Alarm Devices"])
    context["<All categories>"] = sorted(by_label.keys())
    for cat in sorted(cats):
        if cat not in context:
            context[cat] = sorted(cats[cat])
    picked = forms.SelectFromList.show(
        context, title=title, multiselect=True, group_selector_title="Category:",
        button_name="Next", width=650, height=600)
    if not picked:
        return None
    return [by_label[p] for p in picked]


# --- main flow ---------------------------------------------------------------
def run(doc, kind, title, is_match, kind_label):
    """kind: 'device' or 'tag'. is_match(family) -> bool. kind_label: 'device' / 'tag' (for messages)."""
    output = script.get_output()
    app = doc.Application

    # 1. Target families
    if doc.IsFamilyDocument:
        owner = doc.OwnerFamily
        if owner.FamilyCategory is not None and not is_match(owner):
            if not forms.alert("This family ({}) doesn't look like a {} family. Continue anyway?"
                               .format(owner.FamilyCategory.Name, kind_label), yes=True, no=True):
                return
        targets = None   # current family document
    else:
        targets = pick_project_families(doc, is_match, "{} families to add parameters to".format(title))
        if not targets:
            return

    spf = SharedParamFile(app)
    if spf.file is None:
        forms.alert("No shared parameter file - nothing to add.")
        return
    try:
        _run_with_file(doc, kind, title, targets, spf, output)
    finally:
        spf.close()


def _run_with_file(doc, kind, title, targets, spf, output):
    by_guid = dict((guid_str(d), d) for _, d in spf.definitions())

    # 2. Parameters: new pick or a saved preset
    presets = load_presets(kind)
    from_preset = False
    while True:
        opts = ["Pick parameters..."]
        if presets:
            opts += ["Use a preset..."] + ["Delete a preset..."]
        choice = opts[0] if len(opts) == 1 else forms.CommandSwitchWindow.show(opts, message=title)
        if not choice:
            return
        if choice == "Delete a preset...":
            name = forms.SelectFromList.show(sorted(presets), title="Delete preset", button_name="Delete")
            if name and forms.alert("Delete preset '{}'?".format(name), yes=True, no=True):
                delete_preset(kind, name)
                presets = load_presets(kind)
            continue
        break

    if choice == "Use a preset...":
        name = forms.SelectFromList.show(sorted(presets), title="Preset", button_name="Use")
        if not name:
            return
        p = presets[name]
        defs, missing = [], []
        for item in p.get("params", []):
            d = by_guid.get(item["guid"])
            (defs.append(d) if d else missing.append(item.get("name", item["guid"])))
        if missing:
            if not defs:
                forms.alert("None of the preset's parameters are in this shared parameter file:\n{}"
                            .format(spf.path))
                return
            if not forms.alert("Not in this shared parameter file (will be skipped):\n  {}\n\nContinue?"
                               .format("\n  ".join(missing)), yes=True, no=True):
                return
        mode = p.get("mode", MODE_FAMILY)
        instance_map = dict((i["guid"], i.get("instance", True)) for i in p.get("params", []))
        group_type_id = p.get("group", "")
        from_preset = True
    else:
        defs = pick_definitions(spf)
        if not defs:
            return
        mode = MODE_FAMILY
        if kind == "tag":
            m = forms.CommandSwitchWindow.show(
                ["For labels (shared parameter only)", "As family parameters (Instance / Type)"],
                message="How should the parameters be added to the tag family?")
            if not m:
                return
            mode = MODE_LABEL if m.startswith("For labels") else MODE_FAMILY
        instance_map, group_type_id = {}, ""
        if mode == MODE_FAMILY:
            instance_map = pick_instance_type(defs)
            if instance_map is None:
                return
            group_type_id = pick_group()
            if group_type_id is None:
                return

    # 3. Confirm
    lines = []
    for d in defs:
        if mode == MODE_LABEL:
            lines.append(u"  {}".format(d.Name))
        else:
            lines.append(u"  {}  ({})".format(d.Name, "Instance" if instance_map.get(guid_str(d), True) else "Type"))
    where = ("the open family" if targets is None
             else "{} famil{} (opened, changed and reloaded)".format(len(targets), "y" if len(targets) == 1 else "ies"))
    how = ("for use in labels" if mode == MODE_LABEL
           else "under '{}'".format(group_label(group_type_id)))
    msg = u"Add {} parameter(s) {} to {}:\n\n{}".format(len(defs), how, where, u"\n".join(lines))
    if not forms.alert(msg, yes=True, no=True, title=title):
        return

    # 4. Apply
    rows, failed_fams = [], []
    if targets is None:
        t = DB.Transaction(doc, "Add Shared Parameters")
        t.Start()
        try:
            res = apply_to_family_doc(doc, defs, instance_map, group_type_id, mode)
            t.Commit()
        except Exception:
            t.RollBack()
            raise
        fam_name = doc.Title
        rows += [[fam_name, n, r] for n, r, _ in res]
    else:
        opts = FamilyLoadOptions()
        with forms.ProgressBar(title="Adding parameters ({value} of {max_value})", cancellable=True) as pb:
            for i, fam in enumerate(targets):
                if pb.cancelled:
                    break
                name = fam.Name
                fdoc = None
                try:
                    fdoc = doc.EditFamily(fam)
                    t = DB.Transaction(fdoc, "Add Shared Parameters")
                    t.Start()
                    res = apply_to_family_doc(fdoc, defs, instance_map, group_type_id, mode)
                    t.Commit()
                    if any(a for _, _, a in res):
                        fdoc.LoadFamily(doc, opts)
                    rows += [[name, n, r] for n, r, _ in res]
                except Exception as e:
                    failed_fams.append(name)
                    rows.append([name, "-", "Family failed: {}".format(e)])
                finally:
                    if fdoc is not None:
                        try:
                            fdoc.Close(False)
                        except Exception:
                            pass
                pb.update_progress(i + 1, len(targets))

    output.print_md("## {}".format(title))
    output.print_md("Shared parameter file: `{}`".format(spf.path))
    output.print_table(rows, columns=["Family", "Parameter", "Result"])
    added = sum(1 for r in rows if r[2].startswith("Added"))
    output.print_md("**{} parameter(s) added.**".format(added))
    if targets is not None:
        output.print_md("Families were reloaded into the project; their .rfa files on disk were not changed.")

    # 5. Offer to save as a preset
    if not from_preset:
        name = forms.ask_for_string(
            prompt="Save this set of parameters as a preset? Enter a name (Cancel to skip).",
            title=title)
        if name and name.strip():
            name = name.strip()
            if name in presets and not forms.alert("Replace preset '{}'?".format(name), yes=True, no=True):
                return
            save_preset(kind, name, {
                "mode": mode,
                "group": group_type_id,
                "params": [{"guid": guid_str(d), "name": d.Name,
                            "instance": instance_map.get(guid_str(d), True)} for d in defs],
            })
