# -*- coding: utf-8 -*-
# Auto Conduit script - version v6
__title__ = "Auto\nConduit v6"
__doc__ = ("Pick devices or their tags in order (Esc when finished, then confirm); plans orthogonal conduit "
           "for the whole chain, choosing connectors to keep front approaches open, at a chosen elevation "
           "from the current view's level. Wall devices (per Auto Conduit - Config) are entered from the "
           "front or back only. Each run uses the conduit type set for the family it leaves.")

from pyrevit import revit, forms
from Autodesk.Revit.DB import ElementId, TransactionGroup, OverrideGraphicSettings
from Autodesk.Revit.UI.Selection import ObjectType
from Autodesk.Revit.Exceptions import OperationCanceledException
from System.Collections.Generic import List

import mounting_rules            # Auto Conduit - Config
import conduit_routing as cr     # routing and settings shared with Auto-Circuit (lib/conduit_routing.py)
from conduit_routing import (
    AVOID_EXISTING_CONDUIT, AVOID_MODEL_OBSTACLES, DEFAULT_ELEVATION_TEXT, DeviceOrTagFilter,
    HIGHLIGHT_PICKED, MARGIN, OPT_ADD_AGAIN, OPT_ADJUST, OPT_CANCEL, OPT_CANCEL_CHAIN, OPT_CLOSEST,
    OPT_CONTINUE, OPT_FINISH, OPT_IGNORE, OPT_REMOVE, OPT_SKIP, OPT_SKIP_DEV, OPT_UNDO, adjust_device,
    alignment_moves, choose_default_type, collect_obstacles, conduit_connectors, create_link, eid,
    element_label, free_top_count, highlight, make_highlight, parse_length, print_debug, resolve_element,
    resolve_link_types, shift_down, solve_chain,
)

doc = revit.doc
uidoc = revit.uidoc
cr.bind(doc, uidoc, "Auto Conduit")


def pick_elements_in_order():
    """Pick devices (or tags hosted to devices) one at a time. Esc asks whether you're finished.
    Picked devices are highlighted in the active view while picking; the highlight is a temporary
    override inside a transaction group that is always rolled back, so nothing is left in the model.
    Returns the list of device elements, or None if the tool was cancelled."""
    ogs = make_highlight() if HIGHLIGHT_PICKED else None
    tg = None
    if ogs is not None:
        try:
            tg = TransactionGroup(doc, "Auto Conduit selection")
            tg.Start()
        except Exception:
            tg, ogs = None, None
    try:
        return _pick_loop(ogs)
    finally:
        if tg is not None:
            try:
                tg.RollBack()   # removes every highlight
            except Exception:
                pass


def _pick_loop(ogs):
    picks = []   # one entry per pick, in order: {"el": device, "ids": [ElementIds highlighted for it]}
    flt = DeviceOrTagFilter()
    state = {"ogs": ogs}

    def keys():
        return [eid(p["el"]) for p in picks]

    def remove(index):
        """Take one pick out of the chain and clear its highlight (unless another pick still uses it)."""
        gone = picks.pop(index)
        if state["ogs"] is None:
            return
        still = set(eid(i) for p in picks for i in p["ids"])
        clear = [i for i in gone["ids"] if eid(i) not in still]
        if clear:
            highlight(OverrideGraphicSettings(), clear)   # a blank override removes the colour

    while True:
        n = len(picks) + 1
        try:
            r = uidoc.Selection.PickObject(
                ObjectType.Element, flt,
                "Select device or tag #{} in order (Shift+click a picked device to remove it; "
                "Esc when finished)".format(n))
        except OperationCanceledException:
            if not picks:
                return None
            choice = forms.alert(
                "{} element(s) selected so far.\n\nAre you finished selecting?".format(len(picks)),
                title="Auto Conduit",
                options=[OPT_FINISH, OPT_CONTINUE, OPT_UNDO, OPT_CANCEL])
            if choice == OPT_FINISH:
                if len(picks) >= 2:
                    return [p["el"] for p in picks]
                forms.alert("Select at least two elements.")
                continue
            if choice == OPT_UNDO:
                remove(len(picks) - 1)
                continue
            if choice == OPT_CANCEL:
                return None
            continue   # Continue selecting, or dialog closed
        except Exception:
            return [p["el"] for p in picks] if len(picks) >= 2 else None
        shift = shift_down()   # read straight after the click, while the key is still held
        picked = doc.GetElement(r.ElementId)
        el = resolve_element(picked)
        if el is None:
            forms.alert("That tag isn't hosted to a device in this model (it may tag a linked element). "
                        "Pick the device or a different tag.")
            continue
        k = eid(el)
        if shift:
            # Shift+click = deselect, like Revit: removes the most recent pick of that device
            if k in keys():
                remove(len(picks) - 1 - keys()[::-1].index(k))
            continue
        if picks and k == eid(picks[-1]["el"]):
            continue   # ignore picking the same device twice in a row
        if k in keys():
            first = keys().index(k) + 1
            choice = forms.alert(
                "{} is already in this chain (pick #{}).\n\n"
                "Adding it again routes conduit back to it and creates a loop.".format(
                    element_label(el), first),
                title="Auto Conduit - device already selected",
                options=[OPT_IGNORE, OPT_REMOVE, OPT_ADD_AGAIN])
            if choice == OPT_REMOVE:
                remove(len(picks) - 1 - keys()[::-1].index(k))
                continue
            if choice != OPT_ADD_AGAIN:
                continue   # ignored, or dialog closed
        ids = [el.Id]
        if eid(picked) != k:
            ids.append(picked.Id)   # a tag was picked: mark the tag too
        picks.append({"el": el, "ids": ids})
        if state["ogs"] is not None and not highlight(state["ogs"], ids):
            state["ogs"] = None   # this view doesn't allow overrides; carry on without highlighting


def main():
    elems = pick_elements_in_order()
    if not elems or len(elems) < 2:
        return

    # ---- routing preferences: mounting + conduit type ----
    rules = mounting_rules.load_rules()
    walls = set(eid(e) for e in elems
                if mounting_rules.get_mounting_for_element(e, rules) == mounting_rules.WALL)

    n = len(elems)
    need = {}
    for i, e in enumerate(elems):
        need[eid(e)] = need.get(eid(e), 0) + (1 if i in (0, n - 1) else 2)

    skip = set()
    fallback = set()
    checked = set()
    for e in elems:
        k = eid(e)
        if k not in walls or k in checked:
            continue
        checked.add(k)
        tops = free_top_count(e)
        if tops >= need[k]:
            continue
        choice = forms.alert(
            "Wall device {} has {} unconnected top Conduit connector(s) but needs {}.\n\n"
            "Skip this device, or use its closest available connector(s)?".format(
                element_label(e), tops, need[k]),
            options=[OPT_CLOSEST, OPT_SKIP])
        if not choice:
            return
        if choice == OPT_SKIP:
            skip.add(k)
        else:
            fallback.add(k)

    seq = []
    for e in elems:
        if eid(e) in skip:
            continue
        if seq and eid(seq[-1]) == eid(e):
            continue
        seq.append(e)
    if len(seq) < 2:
        forms.alert("Fewer than two elements remain after skipping devices.")
        return

    # ---- conduit type per run (set per family in Auto Conduit - Config) ----
    link_types, missing = resolve_link_types(seq, rules)
    if missing:
        forms.alert("These conduit types from Auto Conduit - Config were not found in this project:\n\n{}\n\n"
                    "Runs using them will use the default conduit type instead.".format("\n".join(missing)))
    if any(t is None for t in link_types):
        default_type = choose_default_type()
        if default_type is None:
            return
        link_types = [t if t is not None else default_type for t in link_types]

    # ---- level = current view's level ----
    level = doc.ActiveView.GenLevel
    if level is None:
        for el in seq:
            if el.LevelId != ElementId.InvalidElementId:
                level = doc.GetElement(el.LevelId)
                break
    if level is None:
        forms.alert("Could not determine a level. Run this from a plan or section view that has an associated level.")
        return

    offset = None
    while offset is None:
        txt = forms.ask_for_string(default=DEFAULT_ELEVATION_TEXT,
                                   prompt="Conduit elevation above '{}':".format(level.Name),
                                   title="Conduit Elevation")
        if txt is None:
            return
        offset = parse_length(txt)
        if offset is None:
            forms.alert("Could not read '{}' as a length. Try something like 15'-0\" or 180.".format(txt))
    z_target = level.Elevation + offset

    # ---- obstacle snapshot for the whole chain (skipped when every AVOID_ model setting is off) ----
    static_boxes = []
    if AVOID_MODEL_OBSTACLES or AVOID_EXISTING_CONDUIT:
        xs, ys, zs = [], [], [z_target]
        for e in seq:
            bb = e.get_BoundingBox(None)
            if bb is not None:
                xs += [bb.Min.X, bb.Max.X]
                ys += [bb.Min.Y, bb.Max.Y]
                zs += [bb.Min.Z, bb.Max.Z]
            for c in conduit_connectors(e):
                o = c.Origin
                xs.append(o.X)
                ys.append(o.Y)
                zs.append(o.Z)
        lo = (min(xs) - MARGIN, min(ys) - MARGIN, min(zs) - MARGIN)
        hi = (max(xs) + MARGIN, max(ys) + MARGIN, max(zs) + MARGIN)
        static_boxes = collect_obstacles(lo, hi, set(eid(e) for e in seq))

    # ---- plan the whole chain before creating anything ----
    total_links = len(seq) - 1
    culprit = None        # device at the link that could not be routed
    no_adjust = set()     # devices where an adjustment was tried and didn't help
    while True:
        plan, reason, fail_i, partial = solve_chain(seq, walls, fallback, z_target, static_boxes)
        if plan is not None:
            culprit = None
            break
        prev, culprit = seq[fail_i], seq[fail_i + 1]
        moves = [] if eid(culprit) in no_adjust else alignment_moves(prev, culprit, walls, z_target)
        text = "{}\n\nFrom: {}\nTo:     {}".format(reason, element_label(prev), element_label(culprit))
        options = []
        if partial:
            options.append(OPT_SKIP_DEV)
            text += "\n\n'{}' creates the {} link(s) before it.".format(OPT_SKIP_DEV, len(partial))
        if moves:
            options.append(OPT_ADJUST)
            text += ("\n\n'{}' moves the second device {} so it lines up with the first, "
                     "then plans the chain again.".format(OPT_ADJUST, moves[0][1]))
        options.append(OPT_CANCEL_CHAIN)
        text += "\n\nEither way, the second device is left selected so you can find it."
        choice = forms.alert(text, title="Auto Conduit - link could not be routed", options=options)
        if choice == OPT_ADJUST:
            moved = adjust_device(prev, culprit, moves, walls, fallback, z_target, static_boxes)
            if moved is None:
                no_adjust.add(eid(culprit))
                forms.alert("The device could not be moved into line (it may be hosted or pinned), "
                            "so nothing was changed.")
            continue   # plan again, with the device in its new place if it moved
        if choice == OPT_SKIP_DEV:
            plan = partial
            break
        print_debug(z_target)
        uidoc.Selection.SetElementIds(List[ElementId]([culprit.Id]))
        return
    print_debug(z_target)

    # ---- create every planned link ----
    tg = TransactionGroup(doc, "Auto Conduit chain")
    tg.Start()
    made_links = 0
    failure = None
    try:
        for i, o in enumerate(plan):
            try:
                create_link(o["a"], o["b"], o["pts"], link_types[i], level.Id)
            except Exception as ex:
                failure = "Link {} of {} failed while creating conduit: {}".format(i + 1, total_links, ex)
                break
            made_links += 1
    finally:
        if made_links > 0:
            tg.Assimilate()
        else:
            tg.RollBack()

    if culprit is not None:
        uidoc.Selection.SetElementIds(List[ElementId]([culprit.Id]))
    if failure:
        forms.alert("{}\n\n{} link(s) before it were created.".format(failure, made_links))
    elif culprit is not None:
        forms.alert("Created {} of {} link(s). {} was skipped and is now selected; the devices after it "
                    "were not connected.".format(made_links, total_links, element_label(culprit)))

main()
