# -*- coding: utf-8 -*-
# family_qaqc module - version v1
# Change log (last change first):
#   v1 - Family Audit v1 / Family Placer v4: loaded families by category (moved here from Family Placer) and
#        reading shared parameter files by GUID.
"""Shared code for the Family QAQC tools (Family Placer, Family Audit). Check here before writing a new one.

natural                  sort key that puts 'Type 2' before 'Type 10'
loaded_by_category       {category: {family: [FamilySymbol]}} for every loaded, loadable family
read_shared_param_file   {guid: (name, group)} from a shared parameter file, read as text (Revit's setting is
                         left alone)
"""
import re
import codecs
from Autodesk.Revit.DB import FilteredElementCollector, FamilySymbol, CategoryType
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
