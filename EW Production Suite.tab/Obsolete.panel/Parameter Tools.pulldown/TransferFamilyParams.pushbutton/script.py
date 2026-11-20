# -*- coding: utf-8 -*-
# Transfer Family Params script - version v1
__title__ = "Transfer Family\nParams v1"
__doc__ = ("Copies parameters from one open family to other open families.\n\n"
           "Open the source and destination families in the Family Editor, then run this from any of them. "
           "Pick the source family, the destination family (or several), and the parameters to transfer.\n\n"
           "Shared parameters keep their GUID (no shared parameter file needed); family parameters keep their "
           "name, type of parameter, Instance/Type and Properties group. Optionally copies formulas and values "
           "(destination types are matched to source types by name; unmatched types get the source's current "
           "type value).")

import os
import tempfile
from collections import OrderedDict

from pyrevit import DB, forms, script

app = __revit__.Application  # noqa: F821
output = script.get_output()
TITLE = "Transfer Family Params"


# --- helpers ----------------------------------------------------------------
def spec_base(type_id):
    """'autodesk.spec.aec:length-2.0.0' -> 'autodesk.spec.aec:length' (versions can differ between files)."""
    tid = type_id.TypeId if hasattr(type_id, "TypeId") else (type_id or "")
    return tid.rsplit("-", 1)[0] if "-" in tid.split(":")[-1] else tid


def data_type(p):
    try:
        return p.Definition.GetDataType()
    except Exception:
        return DB.ForgeTypeId("")


def group_type(p):
    try:
        return p.Definition.GetGroupTypeId()
    except Exception:
        return DB.ForgeTypeId("")


def is_category_type(dt):
    """Family Type parameters (<Family Type...>) have a category as their data type."""
    try:
        return bool(dt.TypeId) and DB.Category.IsBuiltInCategory(dt)
    except Exception:
        return False


def spec_label(dt):
    if not dt or not dt.TypeId:
        return ""
    try:
        if is_category_type(dt):
            return u"Family Type: " + DB.LabelUtils.GetLabelFor(DB.Category.GetBuiltInCategory(dt))
    except Exception:
        return "Family Type"
    try:
        return DB.LabelUtils.GetLabelForSpec(dt)
    except Exception:
        return ""


def group_label(gt):
    try:
        return DB.LabelUtils.GetLabelForGroup(gt) if gt and gt.TypeId else "Other"
    except Exception:
        return "Other"


def is_builtin(p):
    try:
        return p.Definition.BuiltInParameter != DB.BuiltInParameter.INVALID
    except Exception:
        return False


def is_shared(p):
    try:
        return p.IsShared
    except Exception:
        return False


def doc_label(d):
    cat = d.OwnerFamily.FamilyCategory
    return u"{}   [{}]".format(d.Title, cat.Name if cat else "No category")


def family_types(fm):
    types = [t for t in fm.Types]
    if not types and fm.CurrentType is not None:
        types = [fm.CurrentType]
    return types


# --- reading values ---------------------------------------------------------
def read_value(src_doc, ftype, p):
    """(storage, value) of parameter p in FamilyType ftype, or None if it has no value."""
    try:
        if not ftype.HasValue(p):
            return None
    except Exception:
        return None
    st = p.StorageType
    if st == DB.StorageType.Double:
        return (st, ftype.AsDouble(p))
    if st == DB.StorageType.Integer:
        return (st, ftype.AsInteger(p))
    if st == DB.StorageType.String:
        return (st, ftype.AsString(p))
    if st == DB.StorageType.ElementId:
        eid = ftype.AsElementId(p)
        if eid is None or eid == DB.ElementId.InvalidElementId:
            return None
        return (st, src_doc.GetElement(eid))   # the element; matched by name in the destination
    return None


def match_element(dest_doc, el):
    """Finds the destination element with the same class and name (materials, nested family types, images)."""
    if el is None:
        return None
    cls = el.GetType()
    fam_name = getattr(el, "FamilyName", None)
    for cand in DB.FilteredElementCollector(dest_doc).OfClass(cls):
        try:
            if cand.Name == el.Name and getattr(cand, "FamilyName", None) == fam_name:
                return cand.Id
        except Exception:
            continue
    return None


# --- temporary shared parameter file -----------------------------------------
class TempSharedParams(object):
    """Recreates source shared parameters (same GUID, name, spec, visibility) in a temp file so they can be
    added to the destination without the user's shared parameter file. Restores the setting on close()."""

    def __init__(self):
        self.original = app.SharedParametersFilename
        self.path = os.path.join(tempfile.gettempdir(), "EWTestSuite_transfer_params.txt")
        with open(self.path, "w"):
            pass
        app.SharedParametersFilename = self.path
        self.file = app.OpenSharedParameterFile()
        self.group = self.file.Groups.Create("Transfer")
        self.cache = {}

    def definition(self, p):
        key = str(p.GUID).lower()
        if key in self.cache:
            return self.cache[key]
        opts = DB.ExternalDefinitionCreationOptions(p.Definition.Name, data_type(p))
        opts.GUID = p.GUID
        try:
            opts.Visible = p.Definition.Visible
        except Exception:
            pass
        d = self.group.Definitions.Create(opts)
        self.cache[key] = d
        return d

    def close(self):
        try:
            app.SharedParametersFilename = self.original or ""
        except Exception:
            pass
        try:
            os.remove(self.path)
        except Exception:
            pass


# --- picking ------------------------------------------------------------------
def pick_docs():
    fam_docs = [d for d in app.Documents if d.IsFamilyDocument and not d.IsLinked]
    if len(fam_docs) < 2:
        forms.alert("Open at least two families in the Family Editor (the source and the destination), "
                    "then run this again.", title=TITLE)
        return None, None
    labels = OrderedDict()
    for d in sorted(fam_docs, key=lambda x: x.Title.lower()):
        lbl = doc_label(d)
        while lbl in labels:
            lbl += " "
        labels[lbl] = d
    src = forms.SelectFromList.show(list(labels.keys()), title="1 - Source family (copy FROM)",
                                    multiselect=False, button_name="Next", width=600, height=450)
    if not src:
        return None, None
    src_doc = labels[src]
    rest = [l for l in labels if l != src]
    dests = forms.SelectFromList.show(rest, title="2 - Destination family (copy TO) - tick one or more",
                                      multiselect=True, button_name="Next", width=600, height=450)
    if not dests:
        return None, None
    return src_doc, [labels[l] for l in dests]


class ParamItem(forms.TemplateListItem):
    @property
    def name(self):
        p = self.item
        bits = ["Instance" if p.IsInstance else "Type",
                "Shared" if is_shared(p) else "Family"]
        spec = spec_label(data_type(p))
        if spec:
            bits.append(spec)
        txt = u"{}   ({})".format(p.Definition.Name, ", ".join(bits))
        if p.Formula:
            txt += u"   = " + p.Formula
        return txt


def pick_params(src_doc):
    params = [p for p in src_doc.FamilyManager.Parameters if not is_builtin(p)]
    if not params:
        forms.alert("The source family has no user parameters to transfer.", title=TITLE)
        return None
    params.sort(key=lambda p: (group_label(group_type(p)).lower(), p.Definition.Name.lower()))
    context = OrderedDict()
    context["<All parameters>"] = [ParamItem(p) for p in params]
    context["<Shared only>"] = [ParamItem(p) for p in params if is_shared(p)]
    context["<Family only>"] = [ParamItem(p) for p in params if not is_shared(p)]
    for p in params:
        context.setdefault(group_label(group_type(p)), []).append(ParamItem(p))
    picked = forms.SelectFromList.show(
        context, title=u"3 - Parameters to transfer from {}".format(src_doc.Title),
        multiselect=True, group_selector_title="Show:", button_name="Next", width=750, height=600)
    if not picked:
        return None
    # unique, in source order
    seen, out = set(), []
    for p in picked:
        if p.Id not in seen:
            seen.add(p.Id)
            out.append(p)
    return out


OPT_FORMULA = "Copy formulas"
OPT_VALUES = "Copy values (types matched by name; others get the source's current type value)"
OPT_UPDATE = "Also update parameters that already exist in the destination (formula / values)"


def pick_options():
    items = [forms.TemplateListItem(OPT_FORMULA, checked=True),
             forms.TemplateListItem(OPT_VALUES, checked=True),
             forms.TemplateListItem(OPT_UPDATE, checked=False)]
    picked = forms.SelectFromList.show(items, title="4 - What to copy (untick all = parameters only)",
                                       multiselect=True, button_name="Next", width=700, height=260)
    if picked is None:
        return None
    return set(picked)


# --- applying -------------------------------------------------------------------
def find_existing(fm, p):
    by_guid = None
    if is_shared(p):
        for q in fm.Parameters:
            try:
                if q.IsShared and q.GUID == p.GUID:
                    by_guid = q
                    break
            except Exception:
                pass
    if by_guid is not None:
        return by_guid
    try:
        return fm.get_Parameter(p.Definition.Name)
    except Exception:
        for q in fm.Parameters:
            if q.Definition.Name == p.Definition.Name:
                return q
    return None


def add_param(dest_doc, fm, p, temp):
    dt = data_type(p)
    gt = group_type(p)
    if is_shared(p):
        return fm.AddParameter(temp.definition(p), gt, p.IsInstance)
    if is_category_type(dt):
        cat = DB.Category.GetCategory(dest_doc, DB.Category.GetBuiltInCategory(dt))
        return fm.AddParameter(p.Definition.Name, gt, cat, p.IsInstance)
    return fm.AddParameter(p.Definition.Name, gt, dt, p.IsInstance)


def set_value(fm, dp, val, dest_doc):
    st, v = val
    if st == DB.StorageType.ElementId:
        eid = match_element(dest_doc, v)
        if eid is None:
            return u"'{}' not in destination".format(getattr(v, "Name", "?"))
        fm.Set(dp, eid)
    elif st == DB.StorageType.String:
        fm.Set(dp, v or "")
    else:
        fm.Set(dp, v)
    return None


def transfer(src_doc, dest_doc, params, opts, temp):
    """Returns rows [(param, result)]. Runs its own transaction on dest_doc."""
    sfm, fm = src_doc.FamilyManager, dest_doc.FamilyManager
    src_types = dict((t.Name, t) for t in sfm.Types)
    src_current = sfm.CurrentType
    rows, mapping = [], []   # mapping: (source param, dest param, status text)

    t = DB.Transaction(dest_doc, "Transfer Family Params")
    t.Start()
    try:
        # 1. parameters
        for p in params:
            name = p.Definition.Name
            ex = find_existing(fm, p)
            if ex is not None:
                same_kind = (spec_base(data_type(ex)) == spec_base(data_type(p))
                             and (not is_shared(p) or (is_shared(ex) and ex.GUID == p.GUID)))
                if not same_kind:
                    rows.append((name, "Skipped: destination has a different parameter with this name"))
                    continue
                if OPT_UPDATE in opts:
                    mapping.append((p, ex, "Already there - updated"))
                else:
                    rows.append((name, "Already there ({})".format("Instance" if ex.IsInstance else "Type")))
                continue
            try:
                dp = add_param(dest_doc, fm, p, temp)
                mapping.append((p, dp, "Added ({})".format("Instance" if p.IsInstance else "Type")))
            except Exception as e:
                rows.append((name, u"Failed to add: {}".format(e)))

        notes = dict((sp.Id, []) for sp, _, _ in mapping)

        # 2. values (per destination type)
        if OPT_VALUES in opts and mapping:
            original = fm.CurrentType
            for dtype in family_types(fm):
                stype = src_types.get(dtype.Name, src_current) if dtype.Name else src_current
                if stype is None:
                    continue
                try:
                    if fm.CurrentType is None or fm.CurrentType.Name != dtype.Name:
                        fm.CurrentType = dtype
                except Exception:
                    pass
                for sp, dp, _ in mapping:
                    if OPT_FORMULA in opts and sp.Formula:
                        continue   # formula sets the value
                    if dp.Formula:
                        continue   # destination formula drives it
                    val = read_value(src_doc, stype, sp)
                    if val is None:
                        continue
                    try:
                        err = set_value(fm, dp, val, dest_doc)
                        if err and err not in notes[sp.Id]:
                            notes[sp.Id].append(err)
                    except Exception as e:
                        msg = u"value not set ({}): {}".format(dtype.Name or "type", e)
                        notes[sp.Id].append(msg)
            try:
                if original is not None:
                    fm.CurrentType = original
            except Exception:
                pass

        # 3. formulas (after every parameter exists, so formulas can refer to each other)
        if OPT_FORMULA in opts:
            for sp, dp, _ in mapping:
                if not sp.Formula:
                    continue
                try:
                    fm.SetFormula(dp, sp.Formula)
                except Exception as e:
                    notes[sp.Id].append(u"formula not set ({}) - does it use a parameter that isn't in this "
                                        u"family?".format(str(e).split("\n")[0]))

        t.Commit()
    except Exception:
        if t.HasStarted() and not t.HasEnded():
            t.RollBack()
        raise

    for sp, dp, status in mapping:
        txt = status
        if notes[sp.Id]:
            txt += u"; " + u"; ".join(notes[sp.Id])
        rows.append((sp.Definition.Name, txt))
    return rows


# --- main -------------------------------------------------------------------------
def main():
    src_doc, dest_docs = pick_docs()
    if not src_doc:
        return
    params = pick_params(src_doc)
    if not params:
        return
    opts = pick_options()
    if opts is None:
        return

    what = ["parameters"]
    if OPT_FORMULA in opts:
        what.append("formulas")
    if OPT_VALUES in opts:
        what.append("values")
    msg = u"Copy {} from:\n  {}\n\nto:\n  {}\n\n{} parameter(s):\n  {}".format(
        ", ".join(what), src_doc.Title, u"\n  ".join(d.Title for d in dest_docs), len(params),
        u"\n  ".join(p.Definition.Name for p in params[:25]) + (u"\n  ..." if len(params) > 25 else u""))
    if not forms.alert(msg, yes=True, no=True, title=TITLE):
        return

    temp = TempSharedParams() if any(is_shared(p) for p in params) else None
    table = []
    try:
        for d in dest_docs:
            try:
                for name, res in transfer(src_doc, d, params, opts, temp):
                    table.append([d.Title, name, res])
            except Exception as e:
                table.append([d.Title, "-", u"Family failed: {}".format(e)])
    finally:
        if temp:
            temp.close()

    output.print_md("## {}".format(TITLE))
    output.print_md(u"Source: **{}**".format(src_doc.Title))
    output.print_table(table, columns=["Destination", "Parameter", "Result"])
    added = sum(1 for r in table if r[2].startswith("Added"))
    output.print_md("**{} parameter(s) added.** Each destination family has one Undo; save the families "
                    "(and reload them into the project) to keep the changes.".format(added))


main()
