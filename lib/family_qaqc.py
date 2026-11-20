# -*- coding: utf-8 -*-
# family_qaqc module - version v3
# Change log (last change first):
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
FamilyLoadOptions        reload a family into the project, keeping the parameter values already there
remap_to_shared          swap a family parameter (shared or not) for a shared parameter, keeping its name, values
                         and formulas
"""
import re
import codecs
from Autodesk.Revit.DB import (FilteredElementCollector, FamilySymbol, CategoryType, BuiltInParameter,
                               IFamilyLoadOptions, FamilySource)
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


def remap_to_shared(fdoc, param, definition):
    """Replaces the family parameter param with the shared parameter definition, in an open transaction of the
    family document fdoc. Keeps Instance / Type, the group, values and formulas. Returns the new FamilyParameter.
    A shared parameter can't be swapped straight for another of the same name, so it is first turned into a
    plain family parameter under a temporary name."""
    fm = fdoc.FamilyManager
    group = _group(param)
    instance = param.IsInstance
    if param.IsShared:
        param = fm.ReplaceParameter(param, param.Definition.Name + "__remap_tmp", group, instance)
    return fm.ReplaceParameter(param, definition, group, instance)


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
