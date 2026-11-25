# -*- coding: utf-8 -*-
# conduit_trace module - version v8
# Change log (last change first):
#   v8 - Code audit (Auto Circuit - SLC v4 / NAC v5 / Voice v5, no change in use): trace_downstream keeps the splits
#        it is inside on a list instead of calling itself at each one, so a run with any number of tees in a row
#        can't run out of stack (which could stop the tool, or Revit). Same order as before, checked on 20,000
#        random conduit networks.
#   v7 - Auto Circuit - SLC v3 / NAC v4 / Voice v4: follow / trace_downstream take prefer (devices the user
#        chose): at a split their side comes first, ahead of the tee rule; end_on_its_side for a run to an end device.
#   v6 - VESDA Pipe Swap v1: conduit_connectors, connected_elements and walk take an optional domain (default
#        conduit, so nothing changes for the conduit tools); VESDA Pipe Swap walks pipe runs with Domain.DomainPiping.
#   v5 - Code consolidation step 3 (no tool change): eid_int comes from ew_common.
#   v4 - Code consolidation step 2 (Address SLC v6, Address NAC v3, Address Voice v3, Auto-Circuit v6): the only
#        copy of the conduit tracing (slc_addressing and slc_riser now use these functions); a split follows
#        SLC Riser's tee rule (riser_layout.tee_order: the side with the most devices is the main run, taken
#        last); _Graph, follow and conduits_between take an optional set of conduit types to follow.
"""Follows conduit from one device to the devices downstream of it, in order of connection.

The one copy of the conduit tracing: used by Address NAC / Voice, Address SLC (through slc_addressing),
Auto-Circuit and SLC Riser (through slc_riser). Only conduit of the chosen type(s) is followed (by default the
type of the picked conduit); fittings, boxes and devices are passed through. Where the conduit splits, the tee
rule shared with SLC Riser decides the order (riser_layout.tee_order)."""
from Autodesk.Revit.DB import BuiltInParameter, Domain, ConnectorType, ElementId
from Autodesk.Revit.DB.Electrical import Conduit

from riser_layout import tee_order     # the tee rule, shared with SLC Riser
import ew_common as ec        # shared helpers (lib/ew_common.py)


eid_int = ec.eid_int            # from ew_common


CONDUIT = Domain.DomainCableTrayConduit
PIPING = Domain.DomainPiping


def conduit_connectors(el, domain=CONDUIT):
    """Conduit connectors of a conduit, fitting or family instance (or, with domain=PIPING, its pipe connectors)."""
    cm = None
    try:
        cm = el.ConnectorManager                # conduit
    except Exception:
        pass
    if cm is None:
        try:
            cm = el.MEPModel.ConnectorManager   # devices, fittings, boxes, panels
        except Exception:
            cm = None
    if cm is None:
        return []
    out = []
    for c in cm.Connectors:
        try:
            if c.Domain == domain:
                out.append(c)
        except Exception:
            pass
    try:
        out.sort(key=lambda c: c.Id)
    except Exception:
        pass
    return out


def connected_elements(el, domain=CONDUIT):
    """One list per conduit connector (or connector of the given domain) of el: the elements physically joined
    to that connector."""
    groups = []
    own = eid_int(el.Id)
    for c in conduit_connectors(el, domain):
        group = []
        try:
            if c.IsConnected:
                for r in c.AllRefs:
                    try:
                        if r.ConnectorType == ConnectorType.Logical:
                            continue
                        owner = r.Owner
                        if owner is not None and eid_int(owner.Id) != own:
                            group.append(owner)
                    except Exception:
                        pass
        except Exception:
            pass
        groups.append(group)
    return groups


def element_type_name(doc, el):
    """Name of an element's type (e.g. the conduit type of a conduit), or ''."""
    try:
        etype = doc.GetElement(el.GetTypeId())
    except Exception:
        return ""
    if etype is None:
        return ""
    try:
        p = etype.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM)
        if p is not None and p.AsString():
            return p.AsString()
    except Exception:
        pass
    try:
        return etype.Name
    except Exception:
        return ""


def trace_downstream(conduit, anchor, ports, allowed, is_device, sort_key=None, prefer=None):
    """Devices reached by following conduit away from the anchor device, in order of connection.

    conduit     id of the conduit that was picked: it gives the direction (and, through `allowed`, the type)
    anchor      id of the device the run starts from; the trace never passes back through it
    ports(i)    -> one list of neighbour ids per conduit connector of element i
    allowed(i)  -> False for an element that must not be followed (a conduit of another type)
    is_device(i)-> True for a device
    sort_key(i) -> optional: orders the tee'd branches by their first device (e.g. its SLC address);
                   None = connector order

    The side of the picked conduit that leads back to the anchor is upstream; everything on the other side
    is downstream. Where the conduit splits, SLC Riser's tee rule decides the order (riser_layout.tee_order):
    the side with the most devices beyond the split is the main run and comes last; the other sides (the tee'd
    branches) come first, each in full, in connector order (or sort_key order). On a tie for the most devices
    the side that comes later is the main run.
    prefer      -> optional ids of devices the user chose (the next device, the last device): at a split, the
                   side holding one of them comes first, ahead of the tee rule, so a run up to them stays on
                   their side of the split.
    Returns (ordered device ids, None), or (None, reason) when the conduit does not lead back to the anchor."""
    def step(i, blocked):
        return [n for group in ports(i) for n in group if n not in blocked and allowed(n)]

    # Which end of the picked conduit leads back to the anchor? (fewest elements in between, if both do)
    ends = [[n for n in group if allowed(n)] for group in ports(conduit)]
    ends = [e for e in ends if e]
    best = None     # (distance, index of the upstream end)
    for index, end in enumerate(ends):
        seen, frontier, distance = set([conduit]), list(end), 0
        seen.update(end)
        while frontier:
            if anchor in frontier:
                if best is None or distance < best[0]:
                    best = (distance, index)
                break
            following = []
            for i in frontier:
                for n in step(i, seen):
                    seen.add(n)
                    following.append(n)
            frontier, distance = following, distance + 1
    if best is None:
        return None, "not connected"
    downstream = [n for index, end in enumerate(ends) if index != best[1] for n in end]

    visited = set([conduit, anchor])
    visited.update(ends[best[1]])
    wanted = set(prefer or ())

    def side_key(sides):
        """Sort value of each side at a split: its connector order, or sort_key of its first device."""
        if sort_key is None:
            return lambda k: k
        return lambda k: (0, sort_key(sides[k][0])) if sides[k] else (1, k)

    def run_from(node):
        """Walk the straight run from node. Returns (devices on it, the ids onward from the split it ends at, or
        None when it just ends)."""
        order = []
        while True:
            visited.add(node)
            if is_device(node):
                order.append(node)
            onward = []
            for n in step(node, visited):
                if n not in onward:
                    onward.append(n)
            if not onward:
                return order, None
            if len(onward) != 1:
                return order, onward
            node = onward[0]

    def merge(order, sides):
        """The sides of a split added to the run before it. The tee rule shared with SLC Riser: the tee'd
        branches first, the main run (most devices) last."""
        ks = tee_order(range(len(sides)), lambda k: len(sides[k]), side_key(sides))
        if wanted:
            # A side holding a device the user chose goes first (the rest keep the tee rule's order).
            ks = [k for k in ks if wanted.intersection(sides[k])] + \
                 [k for k in ks if not wanted.intersection(sides[k])]
        for k in ks:
            order.extend(sides[k])
        return order

    def collect(start):
        """Devices from start onward. Each side of a split is followed in turn, in connector order, and kept on a
        list of open splits rather than by the function calling itself: a run with any number of tees in a row
        can't overflow Revit's stack. Each side is still taken in full before the next is started."""
        order, onward = run_from(start)
        if onward is None:
            return order
        splits = [(order, onward, [])]      # (devices before the split, sides still to follow, sides done)
        while True:
            before, pending, done = splits[-1]
            while pending and pending[0] in visited:
                pending.pop(0)               # reached through an earlier side
            if pending:
                order, onward = run_from(pending.pop(0))
                if onward is not None:
                    splits.append((order, onward, []))
                    continue
                done.append(order)
                continue
            finished = merge(before, done)
            splits.pop()
            if not splits:
                return finished
            splits[-1][2].append(finished)

    order = []
    for n in downstream:
        if n not in visited:
            order.extend(collect(n))
    return order, None


def _type_number(t):
    """A type id as a plain number, from an ElementId or a number, so ids compare the same in any Revit version."""
    return int(eid_int(t)) if isinstance(t, ElementId) else int(t)


class _Graph(object):
    """Elements joined by conduit, read on demand. Only conduit of the chosen types is followed.
    conduit_types: conduit type ids (ElementIds or ints) to follow; None = the type of the picked conduit."""
    def __init__(self, conduit, conduit_types=None):
        if conduit_types:
            self.type_ids = set(_type_number(t) for t in conduit_types)
        else:
            self.type_ids = set([_type_number(conduit.GetTypeId())])
        self.elements, self.port_cache = {}, {}

    def remember(self, el):
        i = eid_int(el.Id)
        self.elements.setdefault(i, el)
        return i

    def ports(self, i):
        if i not in self.port_cache:
            self.port_cache[i] = [[self.remember(e) for e in group]
                                  for group in connected_elements(self.elements[i])]
        return self.port_cache[i]

    def allowed(self, i):
        el = self.elements[i]
        return not isinstance(el, Conduit) or _type_number(el.GetTypeId()) in self.type_ids


def follow(doc, anchor, conduit, is_device, conduit_types=None, sort_key=None, prefer=None):
    """Devices downstream of the anchor device, in order, along conduit of the chosen types (None = the picked
    conduit's type). sort_key(element) optionally orders tee'd branches by their first device. prefer: element
    ids of devices the user chose - at a split their side comes first (see trace_downstream).
    Returns ([elements], None), or (None, reason)."""
    g = _Graph(conduit, conduit_types)
    key = None if sort_key is None else (lambda i: sort_key(g.elements[i]))
    order, problem = trace_downstream(g.remember(conduit), g.remember(anchor), g.ports, g.allowed,
                                      lambda i: is_device(g.elements[i]), key, prefer)
    if problem:
        return None, problem
    return [g.elements[i] for i in order], None


def end_on_its_side(doc, items, item_id, anchor, conduit, is_device, prefer, end_id):
    """items (devices of a run, in any order; item_id(item) -> element id) up to and including the end device,
    in order of connection with the end device's side of every split first (and the prefer devices' side), so the
    run stays on the way to the end device instead of taking a branch the tee rule puts first."""
    order, problem = follow(doc, anchor, conduit, is_device, prefer=set(prefer or ()) | set([end_id]))
    if not problem:
        place = dict((eid_int(el.Id), n) for n, el in enumerate(order))
        items = sorted(items, key=lambda it: place.get(item_id(it), len(place)))
    for n, it in enumerate(items):
        if item_id(it) == end_id:
            return items[:n + 1]
    return items


def conduits_between(anchor, conduit, devices, conduit_types=None):
    """Conduits of the chosen types (None = the picked conduit's type) on the way from the anchor device to each
    of the devices. The anchor's other side (towards the panel) is not included."""
    g = _Graph(conduit, conduit_types)
    start, picked = g.remember(anchor), g.remember(conduit)
    wanted = set(g.remember(d) for d in devices)
    # Way from the anchor to every element (conduit runs are trees, so there is one way to each device).
    parent, frontier = {start: None}, [start]
    while frontier and not wanted.issubset(parent):
        following = []
        for i in frontier:
            for group in g.ports(i):
                for n in group:
                    if n in parent or not g.allowed(n):
                        continue
                    parent[n] = i
                    following.append(n)
        frontier = following
    found = []
    seen = set()
    for d in wanted:
        i = d
        while i is not None and i not in seen:
            seen.add(i)
            if isinstance(g.elements[i], Conduit):
                found.append(g.elements[i])
            i = parent.get(i)
    if picked not in seen and picked in parent:
        found.append(g.elements[picked])
    return found


def conduit_length(el):
    """Length of a conduit in feet (0 if it can't be read)."""
    try:
        p = el.get_Parameter(BuiltInParameter.CURVE_ELEM_LENGTH)
        if p is not None and p.HasValue:
            return p.AsDouble()
    except Exception:
        pass
    try:
        return el.Location.Curve.Length
    except Exception:
        return 0.0


def walk(start, can_enter, limit=5000, domain=CONDUIT):
    """Breadth-first walk over physically joined elements from start (joined through connectors of the domain).
    can_enter(element) -> False keeps the walk out of an element (it is not passed through).
    Returns (parent {id: parent id}, elements {id: element}, ids in the order reached)."""
    root = eid_int(start.Id)
    parent, elements, order = {root: None}, {root: start}, [root]
    frontier = [start]
    while frontier and len(order) < limit:
        following = []
        for el in frontier:
            i = eid_int(el.Id)
            for group in connected_elements(el, domain):
                for n in group:
                    j = eid_int(n.Id)
                    if j in parent:
                        continue
                    try:
                        ok = can_enter(n)
                    except Exception:
                        ok = False
                    if not ok:
                        continue
                    parent[j], elements[j] = i, n
                    order.append(j)
                    following.append(n)
        frontier = following
    return parent, elements, order
