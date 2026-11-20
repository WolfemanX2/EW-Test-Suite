# -*- coding: utf-8 -*-
# family_qaqc module - version v5
# Change log (last change first):
#   v5 - Family Audit v6: nested_shared_families (shared families nested in a family, with instance counts).
#   v4 - Family Audit v5: remap_to_shared checks the data types match, runs in a SubTransaction and, when Revit's
#        ReplaceParameter fails (e.g. Symbol Visibility: "Parameter replacement failed"), rebuilds the parameter:
#        removes it and adds the shared one, then puts back values, formulas, element associations (visibility,
#        nested families) and dimension labels. Returns how it was done.
#   v3 - Family Audit v3: FamilyLoadOptions (reload a family, keeping the project's parameter values), moved here
#        from family_shared_params; plain_family_params.
#   v2 - Family Audit v2: SharedFileSwitch (open any shared parameter file through Revit and put the user's setting
#        back) and remap_to_shared (swap a family parameter for the matching shared parameter).
#   v1 - Family Audit v1 / Family Placer v4: loaded families by category (moved here from Family Placer) and
#        reading shared parameter files by GUID.
"""Shared code for the Family QAQC tools (Family Placer, Family Audit). Check here before writing a new one.

natural                  sort key that puts 'Type 2' before 'Type 10'
loaded_by_category       {category: {family: [FamilySymbol]}} for every loaded, loadable family
read_shared_param_file   {guid: (name, group)} from a shared parameter file, read as text (Revit's setting is
                         left alone)
SharedFileSwitch         get an ExternalDefinition from any shared parameter file; restores Revit's setting on close
plain_family_params      {name: FamilyParameter} of a family's own parameters that aren't shared or built in
nested_shared_families   [(name, category, instances)] of the shared families nested in an open family
FamilyLoadOptions        reload a family into the project, keeping the parameter values already there
remap_to_shared          swap a family parameter (shared or not) for a shared parameter, keeping its name, values,
                         formulas, element associations and dimension labels
"""
import re
import codecs
from Autodesk.Revit.DB import (FilteredElementCollector, FamilySymbol, CategoryType, BuiltInParameter,
                               IFamilyLoadOptions, FamilySource, SubTransaction, StorageType, Dimension,
                               LogicalOrFilter, ElementIsElementTypeFilter, Family, FamilyInstance)
from ew_common import type_name


def natural(text):
    """Sort key that puts 'Type 2' before 'Type 10'."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", text or "")]


def loaded_by_category(doc, include_tags=False):
    """{category name: {family name: [FamilySymbol, ...]}} for every loaded family (not in-place).
    Tag categories are left out unless include_tags (tags can't be placed on their own)."""
    out = {}
    for s in FilteredElementCollector(doc).OfClass(FamilySymbol).ToElements():
        try:
            fam = s.Family
            cat = s.Category
            if fam is None or cat is None or fam.IsInPlace:
                continue
            if not include_tags and cat.CategoryType == CategoryType.Annotation and "Tag" in cat.Name:
                continue
            out.setdefault(cat.Name, {}).setdefault(fam.Name, []).append(s)
        except Exception:
            continue
    for fams in out.values():
        for name in fams:
            fams[name].sort(key=lambda s: natural(type_name(s)))
    return out


def _decode(raw):
    """Text of a shared parameter file: Revit writes them as UTF-16, but hand-edited ones are often UTF-8/ANSI."""
    if raw.startswith(codecs.BOM_UTF16_LE) or raw.startswith(codecs.BOM_UTF16_BE):
        return raw.decode("utf-16")
    if raw.startswith(codecs.BOM_UTF8):
        return raw[len(codecs.BOM_UTF8):].decode("utf-8")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def read_shared_param_file(path):
    """{guid (lower case): (parameter name, group name)} for every parameter in the file. Raises if it can't be
    read."""
    with open(path, "rb") as f:
        text = _decode(f.read())
    groups, params = {}, []
    for line in text.splitlines():
        cols = line.split("\t")
        if cols[0] == "GROUP" and len(cols) >= 3:
            groups[cols[1].strip()] = cols[2].strip()
        elif cols[0] == "PARAM" and len(cols) >= 6:
            params.append((cols[1].strip().lower(), cols[2].strip(), cols[5].strip()))
    return dict((g, (n, groups.get(grp, ""))) for g, n, grp in params)


class SharedFileSwitch(object):
    """Revit only reads the shared parameter file named in its settings. This points it at each file in turn and
    puts the user's setting back on close() (use in try/finally)."""

    def __init__(self, app):
        self.app = app
        self.original = app.SharedParametersFilename
        self.current = None
        self.file = None

    def definition(self, path, guid):
        """ExternalDefinition with that GUID in the file at path, or None."""
        if path != self.current:
            self.app.SharedParametersFilename = path
            self.file = self.app.OpenSharedParameterFile()
            self.current = path
        if self.file is None:
            return None
        for g in self.file.Groups:
            for d in g.Definitions:
                if str(d.GUID).lower() == guid:
                    return d
        return None

    def close(self):
        try:
            if self.app.SharedParametersFilename != self.original:
                self.app.SharedParametersFilename = self.original or ""
        except Exception:
            pass


def _group(param):
    try:
        return param.Definition.GetGroupTypeId()     # Revit 2022+
    except Exception:
        return param.Definition.ParameterGroup      # older


def _spec(d):
    """Data type of a definition, comparable across Revit versions (None if it can't be read)."""
    for get in (lambda: d.GetDataType(), lambda: d.ParameterType):     # Revit 2022+ / older
        try:
            return get()
        except Exception:
            continue
    return None


def _spec_label(spec):
    try:
        from Autodesk.Revit.DB import LabelUtils
        return LabelUtils.GetLabelForSpec(spec)
    except Exception:
        return str(spec)


def _value(ftype, param):
    """A family type's value of param, read by its storage type (None if it has none)."""
    st = param.StorageType
    if not ftype.HasValue(param):
        return None
    if st == StorageType.Integer:
        return ftype.AsInteger(param)
    if st == StorageType.Double:
        return ftype.AsDouble(param)
    if st == StorageType.String:
        return ftype.AsString(param)
    if st == StorageType.ElementId:
        return ftype.AsElementId(param)
    return None


def _all_elements(fdoc):
    """Every element and element type in the family (where a parameter can be associated)."""
    return FilteredElementCollector(fdoc).WherePasses(
        LogicalOrFilter(ElementIsElementTypeFilter(False), ElementIsElementTypeFilter(True))).ToElements()


def _rebuild(fdoc, param, definition):
    """Removes param and adds the shared parameter in its place, putting back its values, its formula, formulas
    that use it, element parameters associated to it and dimensions labeled with it. Returns a summary."""
    fm = fdoc.FamilyManager
    name = param.Definition.Name
    group = _group(param)
    instance = param.IsInstance
    own_formula = param.Formula if param.IsDeterminedByFormula else None
    values = []
    if own_formula is None:
        for ft in fm.Types:
            values.append((ft, _value(ft, param)))
    # other parameters' formulas that use it (blocked removal / broke the replacement): cleared, then put back
    formulas = [(q, q.Formula) for q in fm.Parameters
                if q.Id != param.Id and q.IsDeterminedByFormula and q.Formula and name in q.Formula]
    links, labels = [], []
    for el in _all_elements(fdoc):
        try:
            if isinstance(el, Dimension) and el.FamilyLabel is not None and el.FamilyLabel.Id == param.Id:
                labels.append(el)
        except Exception:
            pass
        try:
            for ep in el.Parameters:
                try:
                    a = fm.GetAssociatedFamilyParameter(ep)
                    if a is not None and a.Id == param.Id:
                        links.append((el, ep.Id))
                except Exception:
                    continue
        except Exception:
            continue

    for q, _f in formulas:
        fm.SetFormula(q, None)
    for d in labels:
        d.FamilyLabel = None
    fm.RemoveParameter(param)
    new = fm.AddParameter(definition, group, instance)

    current = fm.CurrentType
    for ft, v in values:
        if v is None:
            continue
        fm.CurrentType = ft
        fm.Set(new, v)
    if current is not None:
        fm.CurrentType = current
    if own_formula:
        fm.SetFormula(new, own_formula)
    for q, f in formulas:
        fm.SetFormula(q, f)
    relinked = 0
    for el, pid in links:
        for ep in el.Parameters:
            if ep.Id == pid:
                fm.AssociateElementParameterToFamilyParameter(ep, new)
                relinked += 1
                break
    for d in labels:
        d.FamilyLabel = new
    bits = []
    if relinked:
        bits.append("%d association%s" % (relinked, "" if relinked == 1 else "s"))
    if formulas:
        bits.append("%d formula%s" % (len(formulas), "" if len(formulas) == 1 else "s"))
    if labels:
        bits.append("%d dimension label%s" % (len(labels), "" if len(labels) == 1 else "s"))
    return "rebuilt" + (", kept " + ", ".join(bits) if bits else "")


def remap_to_shared(fdoc, param, definition):
    """Swaps the family parameter param (shared or not) for the shared parameter definition, inside an open
    transaction of the family document fdoc. Keeps its name, Instance / Type, group, values, formulas, element
    associations and dimension labels. Returns how it was done ("replaced" or "rebuilt, kept ..."); raises with
    the reason if it couldn't be done (and leaves the family as it was).
    Revit's ReplaceParameter is tried first (a shared parameter goes through a temporary plain one, as one shared
    parameter can't be swapped straight for another of the same name); when that fails the parameter is rebuilt."""
    a, b = _spec(param.Definition), _spec(definition)
    if a is not None and b is not None and a != b:
        raise Exception("data types differ: %s in the family, %s in the file" % (_spec_label(a), _spec_label(b)))
    fm = fdoc.FamilyManager
    group = _group(param)
    instance = param.IsInstance
    st = SubTransaction(fdoc)
    st.Start()
    try:
        p = param
        if p.IsShared:
            p = fm.ReplaceParameter(p, p.Definition.Name + "__remap_tmp", group, instance)
        fm.ReplaceParameter(p, definition, group, instance)
        st.Commit()
        return "replaced"
    except Exception as ex:
        first = str(ex)
        st.RollBack()
    st = SubTransaction(fdoc)
    st.Start()
    try:
        how = _rebuild(fdoc, param, definition)
        st.Commit()
        return how
    except Exception as ex:
        st.RollBack()
        raise Exception("%s (rebuilding it also failed: %s)" % (first, ex))


def plain_family_params(fdoc):
    """{name: FamilyParameter} of the family's own parameters that are neither shared nor built in."""
    out = {}
    for p in fdoc.FamilyManager.Parameters:
        try:
            if p.IsShared or p.Definition.BuiltInParameter != BuiltInParameter.INVALID:
                continue
            out[p.Definition.Name] = p
        except Exception:
            continue
    return out


class FamilyLoadOptions(IFamilyLoadOptions):
    """Overwrite the family; keep parameter values already in the project."""

    def OnFamilyFound(self, familyInUse, overwriteParameterValues):
        overwriteParameterValues.Value = False
        return True

    def OnSharedFamilyFound(self, sharedFamily, familyInUse, source, overwriteParameterValues):
        source.Value = FamilySource.Family
        overwriteParameterValues.Value = False
        return True


def nested_shared_families(fdoc):
    """[(family name, category name, number of instances placed)] of the shared families nested in the open
    family document fdoc, sorted by name."""
    counts = {}
    for inst in FilteredElementCollector(fdoc).OfClass(FamilyInstance).ToElements():
        try:
            fid = inst.Symbol.Family.Id
            counts[fid] = counts.get(fid, 0) + 1
        except Exception:
            continue
    own = fdoc.OwnerFamily.Id if fdoc.OwnerFamily is not None else None
    out = []
    for fam in FilteredElementCollector(fdoc).OfClass(Family).ToElements():
        try:
            if fam.Id == own:
                continue
            p = fam.get_Parameter(BuiltInParameter.FAMILY_SHARED)
            if p is None or p.AsInteger() != 1:
                continue
            cat = fam.FamilyCategory.Name if fam.FamilyCategory is not None else ""
            out.append((fam.Name, cat, counts.get(fam.Id, 0)))
        except Exception:
            continue
    return sorted(out, key=lambda x: natural(x[0]))
