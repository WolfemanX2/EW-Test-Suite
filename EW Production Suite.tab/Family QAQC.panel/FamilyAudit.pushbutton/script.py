# -*- coding: utf-8 -*-
# Family Audit script - version v1
__title__ = "Family\nAudit v1"
__doc__ = ("Lists the loaded families of the chosen categories with their number of types and the shared "
           "parameters inside each family, and which shared parameter file each parameter is in (matched by "
           "GUID against the current shared parameter file and any other files you add). Also lists shared "
           "parameters that have the same name but different GUIDs. Results can be saved as a CSV file.")

import os
from collections import OrderedDict
from pyrevit import revit, forms, script
from Autodesk.Revit.DB import FilteredElementCollector, SharedParameterElement
from family_qaqc import natural, loaded_by_category, read_shared_param_file     # lib/family_qaqc.py
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
    """{guid: [(file name, parameter name in that file)]} and [(file name, error)] for files that couldn't be read."""
    index, errors = {}, []
    for path in files:
        try:
            for g, (name, _grp) in read_shared_param_file(path).items():
                index.setdefault(g, []).append((os.path.basename(path), name))
        except Exception as ex:
            errors.append((os.path.basename(path), str(ex)))
    return index, errors


def file_text(guid, name, index):
    """Which file(s) a parameter is in, noting a different name in the file."""
    hits = index.get(guid)
    if not hits:
        return "Not found"
    return ", ".join(f if n == name else "%s (named '%s' there)" % (f, n) for f, n in hits)


# ---------- Reading the families ----------
def shared_params(fam):
    """OrderedDict {guid: (name, Instance / Type / NOT_FAMILY_PARAM)} of the shared parameters in a family.
    Raises if the family can't be opened."""
    fdoc = doc.EditFamily(fam)
    try:
        found = OrderedDict()
        for p in sorted(fdoc.FamilyManager.Parameters, key=lambda p: natural(p.Definition.Name)):
            if p.IsShared:
                found[str(p.GUID).lower()] = (p.Definition.Name, "Instance" if p.IsInstance else "Type")
        for spe in FilteredElementCollector(fdoc).OfClass(SharedParameterElement).ToElements():
            g = str(spe.GuidValue).lower()
            if g not in found:
                found[g] = (spe.Name, NOT_FAMILY_PARAM)
        return found
    finally:
        fdoc.Close(False)


# ---------- Picking ----------
class Item(forms.TemplateListItem):
    def __init__(self, value, label):
        super(Item, self).__init__(value, checked=True)
        self.label = label

    @property
    def name(self):
        return self.label


def pick_families(cats):
    """[(category, family name, [FamilySymbol])] chosen by the user, or None if cancelled."""
    names = sorted(cats, key=natural)
    chosen = forms.SelectFromList.show([Item(c, "%s  (%d famil%s)" % (c, len(cats[c]), "y" if len(cats[c]) == 1
                                                                       else "ies")) for c in names],
                                       title=TITLE + " - Categories", button_name="Next", multiselect=True)
    if not chosen:
        return None
    rows = [(c, f, cats[c][f]) for c in names if c in chosen for f in sorted(cats[c], key=natural)]
    if len(rows) > 1:
        picked = forms.SelectFromList.show([Item(i, "%s  (%s)" % (r[1], r[0])) for i, r in enumerate(rows)],
                                           title=TITLE + " - Families", button_name="Audit", multiselect=True)
        if not picked:
            return None
        rows = [rows[i] for i in sorted(picked)]
    return rows


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
        f.write(u"Category,Family,Number of Types,Shared Parameter,Instance / Type,GUID,Shared Parameter File\r\n")
        for r in results:
            params = r["params"] or {"": ("", "")}
            for g, (name, kind) in params.items():
                cells = [r["category"], r["family"], r["types"], name or r["note"], kind, g,
                         r["files"].get(g, "") if g else ""]
                f.write(u",".join(csv_cell(c) for c in cells) + u"\r\n")
    forms.alert("Saved:\n" + path, title=TITLE)


def main():
    cats = loaded_by_category(doc, include_tags=True)
    if not cats:
        forms.alert("No loaded families in this model.", title=TITLE)
        return
    rows = pick_families(cats)
    if not rows:
        return
    files = pick_files()
    if files is None:
        return
    index, file_errors = guid_index(files)

    results, cancelled = [], False
    with forms.ProgressBar(title="Reading families ({value} of {max_value})", cancellable=True) as pb:
        for i, (cat, fam_name, symbols) in enumerate(rows):
            if pb.cancelled:
                cancelled = True
                break
            fam = symbols[0].Family
            r = {"category": cat, "family": fam_name, "types": len(symbols), "params": None, "note": "",
                 "files": {}}
            if not fam.IsEditable:
                r["note"] = "Can't be opened for editing"
            else:
                try:
                    r["params"] = shared_params(fam)
                    r["files"] = dict((g, file_text(g, n, index)) for g, (n, _k) in r["params"].items())
                    if not r["params"]:
                        r["note"] = "None"
                except Exception as ex:
                    r["note"] = "Couldn't open: %s" % ex
            results.append(r)
            pb.update_progress(i + 1, len(rows))

    out = script.get_output()
    out.set_title(TITLE)
    out.print_md("## Family Audit - %s" % doc.Title)
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
        table.append([r["family"], r["category"], str(r["types"]), names, where])
    out.print_table(table, columns=["Family", "Category", "Types", "Shared Parameters", "Shared Parameter File"])
    out.print_md("\\* in the family but not one of its Family Types parameters (used by a label or a nested "
                 "family).")

    # Same name, different GUID: the usual cause of schedules and tags showing blanks
    by_name = {}
    for r in results:
        for g, (n, _k) in (r["params"] or {}).items():
            by_name.setdefault(n, {}).setdefault(g, []).append(r["family"])
    clashes = [(n, gs) for n, gs in by_name.items() if len(gs) > 1]
    if clashes:
        out.print_md("### Same name, different GUID")
        ctable = []
        for n, gs in sorted(clashes, key=lambda x: natural(x[0])):
            for g, fams in gs.items():
                ctable.append([n, g, file_text(g, n, index), ", ".join(sorted(set(fams), key=natural))])
        out.print_table(ctable, columns=["Shared Parameter", "GUID", "Shared Parameter File", "Families"])

    if results and forms.alert("Save the results as a CSV file?", title=TITLE, yes=True, no=True):
        save_csv(results)


if __name__ == "__main__":
    main()
