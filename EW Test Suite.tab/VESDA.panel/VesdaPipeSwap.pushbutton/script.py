# -*- coding: utf-8 -*-
# VESDA Pipe Swap script - version v3
# v3 - pipe ADDRESS written in full as '<Panel #>: PORT #' from the detector the run connects to ('ASD-##' if none)
# v2 - ADDRESS renumbered to the new pipe type's number: 'PORT #' on pipes, P# of 'P#:S#:H#' on sampling points
# v1 - new: swap a VESDA run's pipe type and its elbows / tees without touching the sampling point families
__title__ = "VESDA\nPipe Swap v3"
__doc__ = ("Changes the pipe type of a VESDA pipe run without breaking it, unlike Revit's Change Type. Pipes get "
           "the new type and keep their size; elbows, tees (and crosses, transitions, unions, caps) are swapped for "
           "the parts set in the new type's Routing Preferences, kept in place and connected. Fittings and "
           "accessories whose family is listed in VESDA Pipe Swap - Config as a sampling point are never changed.\n\n"
           "Select pipes, fittings or their tags first, or pick when asked. Choose 'Whole connected run' to follow "
           "the pipe from what you picked (it stops at equipment such as the detector) or 'Selected only'. "
           "Afterwards every connection is checked; any that came apart are rejoined, or left selected and listed.\n\n"
           "ADDRESS is renumbered to the new type's number (the last number in its name, e.g. 'VESDA Pipe 1' = 1): "
           "swapped pipes are set to '<Panel #>: PORT 1', Panel # taken from the detector (Fire Alarm Device) the run "
           "connects to, or 'ASD-##: PORT 1' if it has none; sampling points on a swapped pipe 'P4:S0:H3' become "
           "'P1:S0:H3' (S# and H# are not changed).")

from pyrevit import revit, forms
from Autodesk.Revit.DB import FilteredElementCollector, Transaction, ElementId
from Autodesk.Revit.DB.Plumbing import PipeType
from Autodesk.Revit.UI.Selection import ObjectType
from Autodesk.Revit.Exceptions import OperationCanceledException
from System.Collections.Generic import List

import ew_common as ec              # shared helpers (lib/ew_common.py)
import vesda_pipe_swap as vps       # the swap (lib/vesda_pipe_swap.py)

TITLE = "VESDA Pipe Swap"
WHOLE_RUN = "Whole connected run"
SELECTED_ONLY = "Selected only"
CONTINUE = "Continue (no sampling points protected)"
CANCEL = "Cancel"
KEEP = "Keep the swap (problem elements stay selected)"
UNDO = "Undo the swap"

doc = revit.doc
uidoc = revit.uidoc


class _Undo(Exception):
    pass


def _type_name(t):
    return ec.type_name(t)


def picked_now():
    """The current selection, with tags turned into the pipes / fittings they're hosted to."""
    out = []
    for i in uidoc.Selection.GetElementIds():
        el = ec.resolve_pick(doc.GetElement(i), vps.is_run_part)
        if el is not None:
            out.append(el)
    return out


def ask_picks(follow_run):
    flt = ec.PickFilter(vps.is_run_part)
    try:
        if follow_run:
            ref = uidoc.Selection.PickObject(ObjectType.Element, flt, "Pick a pipe or fitting (or its tag) in the run")
            return [ec.resolve_pick(doc.GetElement(ref), vps.is_run_part)]
        refs = uidoc.Selection.PickObjects(ObjectType.Element, flt,
                                           "Pick the pipes and fittings (or their tags), then Finish")
        return [ec.resolve_pick(doc.GetElement(r), vps.is_run_part) for r in refs]
    except OperationCanceledException:
        return []


def main():
    sampling = vps.sampling_families()
    if not sampling:
        answer = forms.CommandSwitchWindow.show(
            [CONTINUE, CANCEL],
            message="No sampling point families are set yet. Set them in Tool Configs > VESDA Pipe Swap - Config so "
                    "they're left alone.")
        if answer != CONTINUE:
            return
    sampling_lower = set(n.lower() for n in sampling)

    pipe_types = sorted(FilteredElementCollector(doc).OfClass(PipeType).ToElements(), key=_type_name)
    if not pipe_types:
        ec.alert("There are no pipe types in this project.", title=TITLE)
        return

    scope = forms.CommandSwitchWindow.show([WHOLE_RUN, SELECTED_ONLY], message="What should be swapped?")
    if not scope:
        return
    follow_run = scope == WHOLE_RUN

    starts = picked_now() or ask_picks(follow_run)
    starts = [s for s in starts if s is not None]
    if not starts:
        return

    elements = vps.collect_run(starts, follow_run)
    pipes = [e for e in elements if vps.is_pipe(e)]

    # Which of the current pipe types to swap (asked only when the run has more than one).
    current = {}
    for p in pipes:
        t = doc.GetElement(p.GetTypeId())
        key = ec.eid_int(p.GetTypeId())
        current.setdefault(key, [t, 0])[1] += 1
    swap_ids = set(current)
    if len(current) > 1:
        class Choice(object):
            def __init__(self, tid, t, n):
                self.tid, self.name = tid, "%s  (%d pipe%s)" % (_type_name(t), n, "" if n == 1 else "s")
        choices = sorted([Choice(k, v[0], v[1]) for k, v in current.items()], key=lambda c: c.name)
        items = [forms.TemplateListItem(c, checked=True, name_attr="name") for c in choices]
        picked = forms.SelectFromList.show(items, title="%s: pipe types to change" % TITLE, multiselect=True,
                                           button_name="Next")
        if not picked:
            return
        swap_ids = set(c.tid for c in picked)

    names = [_type_name(t) for t in pipe_types]
    target_name = forms.CommandSwitchWindow.show(names, message="Swap to which pipe type?")
    if not target_name:
        return
    target = pipe_types[names.index(target_name)]

    plan = vps.Plan(elements, swap_ids, sampling_lower, picked_fittings_only=not follow_run)
    if not plan.pipes and not plan.fittings:
        ec.alert("Nothing to swap: no pipes of the chosen types or fittings were found.", title=TITLE)
        return

    def work():
        plan.apply(doc, target)
        if plan.sampling_changed:
            raise _Undo("Revit changed or removed %d sampling point(s), so nothing was swapped."
                        % len(plan.sampling_changed))
        if plan.broken or plan.size_problems:
            answer = forms.CommandSwitchWindow.show([KEEP, UNDO], message=plan.summary(target_name))
            if answer != KEEP:
                raise _Undo("The swap was undone.")

    error = ec.commit(Transaction(doc, TITLE), work)
    if error:
        ec.alert(error, title=TITLE)
        return

    problems = plan.problem_elements()
    show = problems or plan.changed_elements()
    if show:
        uidoc.Selection.SetElementIds(List[ElementId]([e.Id for e in show]))
    if not (plan.broken or plan.size_problems):
        ec.alert(plan.summary(target_name), title=TITLE)


main()
