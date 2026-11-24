# -*- coding: utf-8 -*-
# VESDA Pipe Swap - Config script - version v1
# v1 - new: tick which pipe fitting / pipe accessory families are VESDA sampling points
__title__ = "VESDA Pipe Swap - Config v1"
__doc__ = ("Choose which Pipe Fitting and Pipe Accessory families are VESDA sampling points. VESDA Pipe Swap never "
           "changes these. The list shows the families loaded in this project; families saved earlier that aren't "
           "loaded here stay ticked so they're kept. Saved per user, by family name, so it works in every project.")

from pyrevit import revit, forms
from Autodesk.Revit.DB import FilteredElementCollector, Family

import ew_common as ec              # shared helpers (lib/ew_common.py)
import vesda_pipe_swap as vps       # config file (lib/vesda_pipe_swap.py)

TITLE = "VESDA Pipe Swap - Config"
doc = revit.doc


class Row(object):
    def __init__(self, family, label):
        self.family = family
        self.label = label


def main():
    try:
        saved = vps.sampling_families()
    except Exception as ex:
        ec.alert("Could not read the settings:\n%s\n\nPath: %s" % (ex, vps.config_path()), title=TITLE)
        return
    saved_lower = set(n.lower() for n in saved)

    cat_ids = set(int(c) for c in vps.SAMPLING_CATEGORIES)
    loaded = {}
    for fam in FilteredElementCollector(doc).OfClass(Family):
        try:
            cat = fam.FamilyCategory
            if cat is not None and ec.eid_int(cat.Id) in cat_ids:
                loaded[fam.Name] = cat.Name
        except Exception:
            pass

    rows = [Row(n, "%s   [%s]" % (n, c)) for n, c in loaded.items()]
    loaded_lower = set(n.lower() for n in loaded)
    rows += [Row(n, "%s   (not loaded in this project)" % n) for n in saved if n.lower() not in loaded_lower]
    if not rows:
        ec.alert("No Pipe Fitting or Pipe Accessory families are loaded in this project.", title=TITLE)
        return
    rows.sort(key=lambda r: r.label.lower())

    first_time = not saved
    items = []
    for r in rows:
        ticked = r.family.lower() in saved_lower
        if first_time and "sampl" in r.family.lower():
            ticked = True       # a starting guess the first time; untick anything that isn't a sampling point
        items.append(forms.TemplateListItem(r, checked=ticked, name_attr="label"))

    picked = forms.SelectFromList.show(items, title="%s: tick the sampling point families" % TITLE,
                                       multiselect=True, button_name="Save")
    if picked is None:
        return
    try:
        vps.save_sampling_families([r.family for r in picked])
    except Exception as ex:
        ec.alert("Could not save the settings:\n%s\n\nPath: %s" % (ex, vps.config_path()), title=TITLE)
        return
    ec.alert("Saved %d sampling point famil%s." % (len(picked), "y" if len(picked) == 1 else "ies"), title=TITLE)


main()
