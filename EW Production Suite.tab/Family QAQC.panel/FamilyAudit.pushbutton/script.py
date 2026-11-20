# -*- coding: utf-8 -*-
# Family Audit script - version v7
# v7 - fuzzy name matching in the remap step (each assumed match is confirmed by the user, unticked by default);
#      the CSV export comes after the remap step and shows the remapped parameters
# v6 - Nested Shared Families list: which audited families have shared families nested in them
# v5 - parameters Revit won't replace directly (e.g. Symbol Visibility) are rebuilt instead, keeping their values,
#      formulas, visibility / nested associations and dimension labels; a data type mismatch is reported as such
# v4 - fix: the remap step failed (too many values to unpack) - the same-name table reused the by_name list
# v3 - remap step options: also map plain family parameters to the shared parameter of the same name, and
#      reload the updated families into the project
# v2 - one category at a time (picked like Family Placer); remap step: parameters not found in the shared
#      parameter files but matching one there by name are swapped for it and the families saved to a folder
__title__ = "Family\nAudit v7"
__doc__ = ("Lists the loaded families of a chosen category with their number of types and the shared "
           "parameters inside each family, and which shared parameter file each parameter is in (matched by "
           "GUID against the current shared parameter file and any other files you add). Also lists shared "
           "parameters that have the same name but different GUIDs, and the shared families nested in each family. Results can be saved as a CSV file. Shared "
           "parameters not found in any file, but with a parameter of the same name in one, can then be remapped "
           "to that file's parameter (optionally plain family parameters with a matching name too), the changed "
           "families saved to a folder you pick and, optionally, reloaded into the project.")

import os
from collections import OrderedDict
from pyrevit import revit, forms, script
from Autodesk.Revit.DB import FilteredElementCollector, SharedParameterElement, Transaction, SaveAsOptions
from family_qaqc import (natural, loaded_by_category, read_shared_param_file,     # lib/family_qaqc.py
                         SharedFileSwitch, remap_to_shared, plain_family_params, FamilyLoadOptions,
                         nested_shared_families, fuzzy_match)
import config_store                                                              # lib/config_store.py

TITLE = "Family Audit"
FILES_SETTING = config_store.user_file("family_audit_files.json")   # the other files the user added
NOT_FAMILY_PARAM = "Not a family parameter"     # in the family (labels, nested families), not in Family Types

doc = revit.doc
app = doc.Application


# ---------- Shared parameter files ----------
def current_file():
    try:
        path = app.SharedParametersFilename
        return path if path and os.path.isfile(path) else None
    except Exception:
        return None


def pick_files():
    """The shared parameter files to check against, or None if cancelled. The current file is always included;
    other files the user adds are remembered for next time."""
    try:
        others = [p for p in (config_store.read_json(FILES_SETTING, empty=[]) or []) if os.path.isfile(p)]
    except Exception:
        others = []
    while True:
        files = ([current_file()] if current_file() else []) + [p for p in others if p != current_file()]
        listing = "\n".join("- " + os.path.basename(p) + ("  (current)" if p == current_file() else "")
                            for p in files) or "- none"
        choice = forms.alert("Shared parameter files to check against:\n" + listing, title=TITLE,
                             options=["Continue", "Add other files...", "Clear other files"])
        if choice is None:
            return None
        if choice == "Continue":
            return files
        if choice == "Add other files...":
            picked = forms.pick_file(file_ext="txt", multi_file=True, title="Pick shared parameter files")
            if picked:
                others += [p for p in picked if p not in others]
        else:
            others = []
        try:
            config_store.write_json(FILES_SETTING, others)
        except Exception:
            pass


def guid_index(files):
    """({guid: [(file name, parameter name in that file)]}, {parameter name: [(file path, guid)]}, and
    [(file name, error)] for files that couldn't be read."""
    index, by_name, errors = {}, {}, []
    for path in files:
        try:
            for g, (name, _grp) in read_shared_param_file(path).items():
                index.setdefault(g, []).append((os.path.basename(path), name))
                by_name.setdefault(name, []).append((path, g))
        except Exception as ex:
            errors.append((os.path.basename(path), str(ex)))
    return index, by_name, errors


def file_text(guid, name, index):
    """Which file(s) a parameter is in, noting a different name in the file."""
    hits = index.get(guid)
    if not hits:
        return "Not found"
    return ", ".join(f if n == name else "%s (named '%s' there)" % (f, n) for f, n in hits)


# ---------- Reading the families ----------
def shared_params(fam):
    """(OrderedDict {guid: (name, Instance / Type / NOT_FAMILY_PARAM)} of the shared parameters in a family,
    [names of its plain (not shared, not built-in) family parameters], [(name, category, instances)] of the
    shared families nested in it). Raises if the family can't be opened."""
    fdoc = doc.EditFamily(fam)
    try:
        plain = sorted(plain_family_params(fdoc), key=natural)
        found = OrderedDict()
        for p in sorted(fdoc.FamilyManager.Parameters, key=lambda p: natural(p.Definition.Name)):
            if p.IsShared:
                found[str(p.GUID).lower()] = (p.Definition.Name, "Instance" if p.IsInstance else "Type")
        for spe in FilteredElementCollector(fdoc).OfClass(SharedParameterElement).ToElements():
            g = str(spe.GuidValue).lower()
            if g not in found:
                found[g] = (spe.Name, NOT_FAMILY_PARAM)
        return found, plain, nested_shared_families(fdoc)
    finally:
        fdoc.Close(False)


# ---------- Picking ----------
class Item(forms.TemplateListItem):
    def __init__(self, value, label, checked=True):
        super(Item, self).__init__(value, checked=checked)
        self.label = label

    @property
    def name(self):
        return self.label


def pick_families(cats):
    """(category, [(family name, [FamilySymbol])]) chosen by the user, or None if cancelled. One category at a
    time, picked the same way as in Family Placer."""
    cat = forms.SelectFromList.show(sorted(cats, key=natural), title=TITLE + " - Category",
                                    button_name="Next", multiselect=False)
    if not cat:
        return None
    fams = cats[cat]
    names = sorted(fams, key=natural)
    if len(names) > 1:
        picked = forms.SelectFromList.show(
            [Item(n, "%s  (%d type%s)" % (n, len(fams[n]), "" if len(fams[n]) == 1 else "s")) for n in names],
            title=TITLE + " - Families in " + cat, button_name="Audit", multiselect=True)
        if not picked:
            return None
        names = [n for n in names if n in picked]
    return cat, [(n, fams[n]) for n in names]


# ---------- Results ----------
def csv_cell(v):
    v = u"%s" % v
    return u'"%s"' % v.replace(u'"', u'""') if any(c in v for c in u',"\n') else v


def save_csv(results):
    path = forms.save_file(file_ext="csv", default_name="Family Audit - " + doc.Title, title="Save Family Audit")
    if not path:
        return
    import codecs
    with codecs.open(path, "w", "utf-8-sig") as f:
        f.write(u"Category,Family,Number of Types,Shared Parameter,Instance / Type,GUID,Shared Parameter File,"
                u"Remap\r\n")
        for r in results:
            params = r["params"] or {"": ("", "")}
            for g, (name, kind) in params.items():
                cells = [r["category"], r["family"], r["types"], name or r["note"], kind, g,
                         r["files"].get(g, "") if g else "", r.get("changes", {}).get(g, "")]
                f.write(u",".join(csv_cell(c) for c in cells) + u"\r\n")
    forms.alert("Saved:\n" + path, title=TITLE)


# ---------- Remapping to the shared parameter file ----------
SHARED_NOT_FOUND = "shared, not found"
PLAIN = "family parameter"


def remap_candidates(results, index, by_name):
    """{kind: {"exact": [...], "fuzzy": [...]}} of possible remaps, each (result, key, name, file path, file guid,
    kind, name in the file, score): shared family parameters whose GUID is in none of the files, and plain family
    parameters, matched to a file parameter of the same name (one entry per file with it), or else to the closest
    name (fuzzy, to be confirmed by the user). key is the parameter's GUID, or 'plain:<name>'."""
    out = dict((k, {"exact": [], "fuzzy": []}) for k in (SHARED_NOT_FOUND, PLAIN))
    file_names = list(by_name)
    for r in results:
        in_family = set(n for n, _k in (r["params"] or {}).values()) | set(r["plain"])
        todo = [(g, name, SHARED_NOT_FOUND) for g, (name, kind) in (r["params"] or {}).items()
                if g not in index and kind != NOT_FAMILY_PARAM]
        todo += [("plain:" + name, name, PLAIN) for name in r["plain"]]
        for key, name, kind in todo:
            if name in by_name:
                for path, fg in by_name[name]:
                    out[kind]["exact"].append((r, key, name, path, fg, kind, name, 1.0))
                continue
            match, score = fuzzy_match(name, file_names)
            if match is None or match in in_family:     # the family already has a parameter of that name
                continue
            for path, fg in by_name[match]:
                out[kind]["fuzzy"].append((r, key, name, path, fg, kind, match, score))
    return out


def pick_remaps(cands, title, button, checked=True):
    """The remaps the user ticks (only the first file ticked for a parameter is used). [] if none or cancelled."""
    if not cands:
        return []
    items = []
    for i, c in enumerate(cands):
        if c[6] == c[2]:
            label = "%s : %s  [%s]  ->  %s" % (c[0]["family"], c[2], c[5], os.path.basename(c[3]))
        else:
            label = "%s : %s  [%s]  ->  %s  (%s, %d%% match)" % (c[0]["family"], c[2], c[5], c[6],
                                                                os.path.basename(c[3]), int(round(c[7] * 100)))
        items.append(Item(i, label, checked))
    picked = forms.SelectFromList.show(items, title=TITLE + " - " + title, button_name=button, multiselect=True)
    return [cands[i] for i in sorted(picked or [])]


def first_per_param(chosen):
    """One remap per family parameter: the first one chosen."""
    out, seen = [], set()
    for c in chosen:
        key = (c[0]["family"], c[1])
        if key not in seen:
            seen.add(key)
            out.append(c)
    return out


def apply_to_results(done, index):
    """Updates the audit results with the remaps that worked, so the CSV shows the families as saved."""
    for c, kind in done:
        r, key, name, _path, fg, _k, new_name, _score = c
        if key.startswith("plain:"):
            if name in r["plain"]:
                r["plain"].remove(name)
            change = "Was family parameter '%s'" % name if new_name != name else "Was a family parameter"
        else:
            if r["params"] is not None:
                r["params"].pop(key, None)
            change = "Remapped from '%s' (GUID %s)" % (name, key) if new_name != name else \
                "Remapped from GUID %s" % key
        if r["params"] is None:
            r["params"] = OrderedDict()
        r["params"][fg] = (new_name, kind)
        r["files"][fg] = file_text(fg, new_name, index)
        r.setdefault("changes", {})[fg] = change
        if r["note"] == "None":
            r["note"] = ""


def remap(results, index, by_name, out):
    """Follow-up step: offers to swap 'Not found' parameters for the same-named parameter in a shared parameter
    file, then saves the changed families to a folder the user picks."""
    found = remap_candidates(results, index, by_name)

    def count(kind):
        return len(set((c[0]["family"], c[1]) for m in ("exact", "fuzzy") for c in found[kind][m]))
    n_shared, n_plain = count(SHARED_NOT_FOUND), count(PLAIN)
    if not n_shared and not n_plain:
        return
    options = []
    if n_shared:
        options.append(Item(SHARED_NOT_FOUND, "Remap shared parameters not found in the files to the shared parameter "
                                              "of the same or a similar name (%d)" % n_shared))
    if n_plain:
        options.append(Item(PLAIN, "Map family parameters to the shared parameter of the same or a similar name (%d)"
                                   % n_plain))
    options.append(Item("reload", "Reload the updated families into this project"))
    picked = forms.SelectFromList.show(options, title=TITLE + " - Remap to shared parameter file",
                                       button_name="Next", multiselect=True)
    if not picked or not (SHARED_NOT_FOUND in picked or PLAIN in picked):
        return
    reload_fams = "reload" in picked
    kinds = [k for k in (SHARED_NOT_FOUND, PLAIN) if k in picked]
    chosen = pick_remaps([c for k in kinds for c in found[k]["exact"]], "Same name in the shared parameter file",
                         "Next")
    fuzzy = [c for k in kinds for c in found[k]["fuzzy"]]
    if fuzzy:
        forms.alert("%d parameter%s %s no exact match in the shared parameter files, but a similar name.\n\n"
                    "Next, tick each assumed match that is correct. Unticked ones are left as they are. A remapped "
                    "parameter takes the shared parameter's name, and formulas that use it are updated."
                    % (len(set((c[0]["family"], c[1]) for c in fuzzy)), "" if len(fuzzy) == 1 else "s",
                       "has" if len(fuzzy) == 1 else "have"), title=TITLE)
        chosen += pick_remaps(fuzzy, "Confirm assumed matches", "Remap", checked=False)
    chosen = first_per_param(chosen)
    if not chosen:
        return
    folder = forms.pick_folder(title="Folder to save the updated families in")
    if not folder:
        return

    by_family = OrderedDict()
    for c in chosen:
        by_family.setdefault(c[0]["family"], []).append(c)
    existing = [f for f in by_family if os.path.exists(os.path.join(folder, f + ".rfa"))]
    if existing and not forms.alert("%d famil%s already in that folder:\n%s\n\nOverwrite?" % (
            len(existing), "y is" if len(existing) == 1 else "ies are", "\n".join(existing[:15])),
            title=TITLE, yes=True, no=True):
        return

    report, done = [], []
    files = SharedFileSwitch(app)
    try:
        with forms.ProgressBar(title="Remapping families ({value} of {max_value})") as pb:
            for n, (fam_name, items) in enumerate(by_family.items()):
                pb.update_progress(n, len(by_family))
                rows, ok = remap_family(items[0][0]["fam"], fam_name, items, files, folder, reload_fams)
                report += rows
                done += ok
            pb.update_progress(len(by_family), len(by_family))
    finally:
        files.close()

    out.print_md("### Remapped to the shared parameter file")
    out.print_md("Saved to `%s`. %s" % (folder, "Reloaded into this project, keeping its parameter values."
                                         if reload_fams else
                                         "The families in this project are unchanged: load the saved files to "
                                         "update them."))
    out.print_table(report, columns=["Family", "Parameter", "Shared Parameter File", "Result"])
    apply_to_results(done, index)


def remap_family(fam, fam_name, items, files, folder, reload_fam):
    """Remaps one family's parameters and saves it to folder. Returns (report rows, [(remap, Instance / Type)]
    for the remaps that were saved)."""
    rows, ok = [], []
    try:
        fdoc = doc.EditFamily(fam)
    except Exception as ex:
        return [[fam_name, c[2], os.path.basename(c[3]), "Couldn't open: %s" % ex] for c in items], []
    try:
        params = dict((str(p.GUID).lower(), p) for p in fdoc.FamilyManager.Parameters if p.IsShared)
        params.update(("plain:" + n, p) for n, p in plain_family_params(fdoc).items())
        done = 0
        t = Transaction(fdoc, "Remap shared parameters")
        t.Start()
        for c in sorted(items, key=lambda c: c[3]):    # one file switch per file
            _r, g, name, path, fg, _k, new_name, _score = c
            fname = os.path.basename(path)
            try:
                d = files.definition(path, fg)
                if d is None:
                    raise Exception("not found in the file")
                if g not in params:
                    raise Exception("not in the family any more")
                kind = "Instance" if params[g].IsInstance else "Type"
                how = remap_to_shared(fdoc, params[g], d)
                done += 1
                ok.append((c, kind))
                rows.append([fam_name, name, fname, "Remapped" + (" as '%s'" % new_name if new_name != name else "")
                             + ("" if how == "replaced" else " (%s)" % how)])
            except Exception as ex:
                rows.append([fam_name, name, fname, "Not remapped: %s" % ex])
        if done:
            t.Commit()
            opts = SaveAsOptions()
            opts.OverwriteExistingFile = True
            path = os.path.join(folder, fam_name + ".rfa")
            fdoc.SaveAs(path, opts)
            rows.append([fam_name, "", "", "Saved %s" % os.path.basename(path)])
            if reload_fam:
                try:
                    fdoc.LoadFamily(doc, FamilyLoadOptions())
                    rows.append([fam_name, "", "", "Reloaded into the project"])
                except Exception as ex:
                    rows.append([fam_name, "", "", "Saved, but not reloaded: %s" % ex])
        else:
            t.RollBack()
            rows.append([fam_name, "", "", "Nothing changed, not saved"])
    except Exception as ex:
        rows.append([fam_name, "", "", "Failed: %s" % ex])
        ok = []                                     # not saved, so nothing changed
    finally:
        fdoc.Close(False)
    return rows, ok


def main():
    cats = loaded_by_category(doc, include_tags=True)
    if not cats:
        forms.alert("No loaded families in this model.", title=TITLE)
        return
    picked = pick_families(cats)
    if not picked:
        return
    cat, rows = picked
    files = pick_files()
    if files is None:
        return
    index, by_name, file_errors = guid_index(files)

    results, cancelled = [], False
    with forms.ProgressBar(title="Reading families ({value} of {max_value})", cancellable=True) as pb:
        for i, (fam_name, symbols) in enumerate(rows):
            if pb.cancelled:
                cancelled = True
                break
            fam = symbols[0].Family
            r = {"category": cat, "family": fam_name, "types": len(symbols), "params": None, "note": "",
                 "files": {}, "fam": fam, "plain": [], "nested": []}
            if not fam.IsEditable:
                r["note"] = "Can't be opened for editing"
            else:
                try:
                    r["params"], r["plain"], r["nested"] = shared_params(fam)
                    r["files"] = dict((g, file_text(g, n, index)) for g, (n, _k) in r["params"].items())
                    if not r["params"]:
                        r["note"] = "None"
                except Exception as ex:
                    r["note"] = "Couldn't open: %s" % ex
            results.append(r)
            pb.update_progress(i + 1, len(rows))

    out = script.get_output()
    out.set_title(TITLE)
    out.print_md("## Family Audit - %s - %s" % (doc.Title, cat))
    out.print_md("Checked against: %s" % (", ".join("`%s`" % os.path.basename(p) for p in files) or
                                          "**no shared parameter file** (every parameter shows as Not found)"))
    for f, err in file_errors:
        out.print_md("**Couldn't read %s:** %s" % (f, err))
    if cancelled:
        out.print_md("**Cancelled** after %d of %d families." % (len(results), len(rows)))

    table = []
    for r in results:
        if r["params"]:
            names = "<br>".join(n + ("" if k != NOT_FAMILY_PARAM else " *") for n, k in r["params"].values())
            where = "<br>".join(r["files"][g] for g in r["params"])
        else:
            names, where = r["note"], ""
        table.append([r["family"], str(r["types"]), names, where])
    out.print_table(table, columns=["Family", "Types", "Shared Parameters", "Shared Parameter File"])
    out.print_md("\\* in the family but not one of its Family Types parameters (used by a label or a nested "
                 "family).")

    # Shared families nested in the audited families
    nested = [r for r in results if r["nested"]]
    out.print_md("### Nested Shared Families")
    if nested:
        out.print_table([[r["family"], str(len(r["nested"])),
                          "<br>".join("%s (%s)" % (n, c) for n, c, _i in r["nested"]),
                          "<br>".join(str(i) for _n, _c, i in r["nested"])] for r in nested],
                        columns=["Family", "Nested Shared Families", "Name (Category)", "Instances"])
    else:
        out.print_md("None of these families have shared families nested in them.")

    # Same name, different GUID: the usual cause of schedules and tags showing blanks
    guids_by_name = {}
    for r in results:
        for g, (n, _k) in (r["params"] or {}).items():
            guids_by_name.setdefault(n, {}).setdefault(g, []).append(r["family"])
    clashes = [(n, gs) for n, gs in guids_by_name.items() if len(gs) > 1]
    if clashes:
        out.print_md("### Same name, different GUID")
        ctable = []
        for n, gs in sorted(clashes, key=lambda x: natural(x[0])):
            for g, fams in gs.items():
                ctable.append([n, g, file_text(g, n, index), ", ".join(sorted(set(fams), key=natural))])
        out.print_table(ctable, columns=["Shared Parameter", "GUID", "Shared Parameter File", "Families"])

    if not cancelled:
        remap(results, index, by_name, out)

    # after the remap step, so the CSV shows the families as they were saved
    if results and forms.alert("Save the results as a CSV file?", title=TITLE, yes=True, no=True):
        save_csv(results)


if __name__ == "__main__":
    main()
