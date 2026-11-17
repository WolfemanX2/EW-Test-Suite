# -*- coding: utf-8 -*-
# Tag Shared Params script - version v1
__title__ = "Tag Shared\nParams v1"
__doc__ = ("Adds a batch of shared parameters from the shared parameter file to tag families.\n\n"
           "In the Family Editor it changes the open tag. In a project you pick loaded tag families; each is "
           "opened, changed and reloaded.\n\n"
           "Two ways to add them:\n"
           "  For labels - the shared parameter is added to the tag family so it can be used in a label "
           "(the label itself still has to be edited to show it).\n"
           "  As family parameters - Instance or Type parameters of the tag itself, e.g. Yes/No "
           "visibility switches.\n\n"
           "Parameters already in a family are skipped. The set can be saved as a preset to reuse.")

from pyrevit import revit
import family_shared_params as fsp


def is_tag(fam):
    cat = fam.FamilyCategory
    try:
        return cat is not None and cat.IsTagCategory
    except Exception:
        return cat is not None and cat.Name.endswith("Tags")


fsp.run(revit.doc, "tag", "Tag Shared Params", is_tag, "tag")
