# -*- coding: utf-8 -*-
# Device Shared Params script - version v1
__title__ = "Device Shared\nParams v1"
__doc__ = ("Adds a batch of shared parameters from the shared parameter file to device families.\n\n"
           "In the Family Editor it changes the open family. In a project you pick loaded model families "
           "(Fire Alarm Devices listed first); each is opened, changed and reloaded, keeping the parameter "
           "values already in the project.\n\n"
           "Choose the parameters, Instance or Type (all, or pick which are Type), and the Properties group. "
           "Parameters already in a family are skipped. The set can be saved as a preset to reuse.")

from pyrevit import revit, DB
import family_shared_params as fsp


def is_device(fam):
    cat = fam.FamilyCategory
    return cat is not None and cat.CategoryType == DB.CategoryType.Model


fsp.run(revit.doc, "device", "Device Shared Params", is_device, "device (model)")
