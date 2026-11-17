# -*- coding: utf-8 -*-
# conduit_trace module - version v2
"""Follows conduit from one device to the devices downstream of it, in order of connection.

Used by Address NAC / Voice. Same method as Address SLC's 'follow the conduit': only conduit of the picked type
is followed; fittings, boxes and devices are passed through."""
from Autodesk.Revit.DB import BuiltInParameter, Domain, ConnectorType
from Autodesk.Revit.DB.Electrical import Conduit


def eid_int(eid):
    """Integer value of an ElementId in any Revit version."""
    try:
        return eid.Value            # Revit 2024+
    except Exception:
        return eid.IntegerValue     # older Revit


def conduit_connectors(el):
    """Conduit connectors of a conduit, fitting or family instance."""
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
            if c.Domain == Domain.DomainCableTrayConduit:
                out.append(c)
        except Exception:
            pass
    try:
        out.sort(key=lambda c: c.Id)
    except Exception:
        pass
    return out


def connected_elements(el):
    """One list per conduit connector of el: the elements physically joined to that connector."""
    groups = []
    own = eid_int(el.Id)
    for c in conduit_connectors(el):
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


def trace_downstream(conduit, anchor, ports, allowed, is_device):
    """Devices reached by following conduit away from the anchor device, in order of connection.

    conduit     id of the conduit that was picked: it gives the direction (and, through `allowed`, the type)
    anchor      id of the device the run starts from; the trace never passes back through it
    ports(i)    -> one list of neighbour ids per conduit connector of element i
    allowed(i)  -> False for an element that must not be followed (a conduit of another type)
    is_device(i)-> True for a device

    The side of the picked conduit that leads back to the anchor is upstream; everything on the other side
    is downstream. Where the conduit splits, the branch with fewer devices is listed first, then the longer.
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

    def collect(start):
        """Devices from start onward. A straight run is walked in a loop; only a split recurses."""
        order, node = [], start
        while True:
            visited.add(node)
            if is_device(node):
                order.append(node)
            onward = []
            for n in step(node, visited):
                if n not in onward:
                    onward.append(n)
            if not onward:
                return order
            if len(onward) == 1:
                node = onward[0]
                continue
            branches = []
            for n in onward:
                if n not in visited:
                    branches.append(collect(n))
            branches.sort(key=len)      # stable: equal branches keep connector order
            for branch in branches:
                order.extend(branch)
            return order

    order = []
    for n in downstream:
        if n not in visited:
            order.extend(collect(n))
    return order, None


class _Graph(object):
    """Elements joined by conduit, read on demand. Only conduit of one type is followed."""
    def __init__(self, conduit):
        self.type_id = eid_int(conduit.GetTypeId())
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
        return not isinstance(el, Conduit) or eid_int(el.GetTypeId()) == self.type_id


def follow(doc, anchor, conduit, is_device):
    """Devices downstream of the anchor device along the picked conduit's type, in order.
    Returns ([elements], None), or (None, reason)."""
    g = _Graph(conduit)
    order, problem = trace_downstream(g.remember(conduit), g.remember(anchor), g.ports, g.allowed,
                                      lambda i: is_device(g.elements[i]))
    if problem:
        return None, problem
    return [g.elements[i] for i in order], None


def conduits_between(anchor, conduit, devices):
    """Conduits of the picked conduit's type on the way from the anchor device to each of the devices.
    The anchor's other side (towards the panel) is not included."""
    g = _Graph(conduit)
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
