# -*- coding: utf-8 -*-
# vesda_pipe_swap module - version v3
# Change log (last change first):
#   v3 - VESDA Pipe Swap v3: a swapped pipe's ADDRESS is written in full as "<Panel #>: PORT <n>", Panel # read
#        from the Fire Alarm Device (detector) the run connects to; "ASD-##" when it has none or none is found.
#   v2 - VESDA Pipe Swap v2: ADDRESS follows the new pipe type's number - "...PORT #" on the swapped pipes and
#        the P# of "P#:S#:H#" on the sampling points joined to them (S# and H# are left as they are).
#   v1 - VESDA Pipe Swap v1 / VESDA Pipe Swap - Config v1: new. Sampling point families (the config), collecting a
#        pipe run, and swapping pipe type plus elbows / tees from the new type's Routing Preferences while leaving
#        the sampling point families untouched.
"""Swaps the pipe type of a VESDA pipe run without Revit's Change Type rebuilding the run.

Revit's own Change Type re-applies the new type's Routing Preferences to every fitting in the selection, which
replaces the sampling point tees and can break the run. This instead:
  - changes each pipe's type and keeps its size,
  - swaps each ordinary fitting (elbow, tee, cross, transition, union, cap) for the part the new type's Routing
    Preferences gives for that fitting's kind and size, keeping it in place and connected,
  - never touches a fitting or accessory whose family is listed as a sampling point in VESDA Pipe Swap - Config,
  - checks every connection afterwards, rejoins any that came apart, and reports what it couldn't,
  - renumbers the ADDRESS parameter to the new type's number (port_number: the last number in the type name):
    pipes are written "<Panel #>: PORT 1" from the detector (Fire Alarm Device) the run connects to, or
    "ASD-##: PORT 1" when it has no Panel #; sampling points joined to a swapped pipe "P4:S0:H3" -> "P1:S0:H3".

Config        sampling_families() / save_sampling_families(names) / config_path()
Run           is_run_part, is_sampling, collect_run(starts, follow_run)
Swap          plan(...) -> Plan, Plan.apply(doc, target_type)  (call inside a transaction)"""
from Autodesk.Revit.DB import (BuiltInCategory, BuiltInParameter, ConnectorType, FamilyInstance,
                               PartType, RoutingPreferenceRuleGroupType, PrimarySizeCriterion)
from Autodesk.Revit.DB.Plumbing import Pipe

import re

import ew_common as ec          # shared helpers (lib/ew_common.py)
import conduit_trace as ct      # connector walk (lib/conduit_trace.py), used here with the piping domain
import config_store as cs       # settings files (lib/config_store.py)

TOOL = "VESDA Pipe Swap"
CONFIG_FILE = "vesda_pipe_swap.json"
RUN_CATEGORIES = (BuiltInCategory.OST_PipeCurves, BuiltInCategory.OST_PipeFitting,
                  BuiltInCategory.OST_PipeAccessory, BuiltInCategory.OST_FlexPipeCurves)
SAMPLING_CATEGORIES = (BuiltInCategory.OST_PipeFitting, BuiltInCategory.OST_PipeAccessory)
REJOIN_TOLERANCE = 0.05         # feet (about 5/8"): how far apart two open connectors may be and still be rejoined
SIZE_TOLERANCE = 0.0005         # feet
ADDRESS_PARAM = "ADDRESS"
PANEL_PARAM = "Panel #"
NO_PANEL = "ASD-##"             # pipe address prefix when the detector has no Panel # (or no detector is found)
SAMPLING_PIPE = re.compile(r"^(\s*P)(\d+)(?=\s*:)", re.IGNORECASE)    # "P4:S0:H3"

# Fitting kind -> the Routing Preferences group its replacement comes from
GROUPS = {
    int(PartType.Elbow): RoutingPreferenceRuleGroupType.Elbows,
    int(PartType.Tee): RoutingPreferenceRuleGroupType.Junctions,
    int(PartType.Cross): RoutingPreferenceRuleGroupType.Crosses,
    int(PartType.Transition): RoutingPreferenceRuleGroupType.Transitions,
    int(PartType.Union): RoutingPreferenceRuleGroupType.Unions,
    int(PartType.Cap): RoutingPreferenceRuleGroupType.Caps,
}
KIND_NAMES = {int(PartType.Elbow): "elbow", int(PartType.Tee): "tee", int(PartType.Cross): "cross",
              int(PartType.Transition): "transition", int(PartType.Union): "union", int(PartType.Cap): "cap"}


# ---------------- Config: which families are sampling points ----------------
def config_path():
    return cs.user_file(CONFIG_FILE)


def sampling_families():
    """Family names (as saved) that are sampling points."""
    data = cs.read_json(config_path(), {}) or {}
    return [n for n in data.get("sampling_families", []) if n]


def save_sampling_families(names):
    data = cs.read_json(config_path(), {}) or {}
    data["sampling_families"] = sorted(set(n for n in names if n), key=lambda n: n.lower())
    cs.write_json(config_path(), data)


# ---------------- What's in a run ----------------
def _cat(el):
    try:
        return ec.eid_int(el.Category.Id)
    except Exception:
        return None


def is_run_part(el):
    """A pipe, flex pipe, pipe fitting or pipe accessory."""
    c = _cat(el)
    return c is not None and any(c == int(x) for x in RUN_CATEGORIES)


def is_pipe(el):
    return isinstance(el, Pipe)


def family_name(el):
    try:
        return el.Symbol.Family.Name
    except Exception:
        return ""


def is_sampling(el, names_lower):
    """True for a fitting / accessory whose family is listed as a sampling point."""
    return isinstance(el, FamilyInstance) and family_name(el).lower() in names_lower


def is_fitting(el):
    return isinstance(el, FamilyInstance) and _cat(el) == int(BuiltInCategory.OST_PipeFitting)


def part_type(el):
    try:
        return int(el.MEPModel.PartType)
    except Exception:
        return None


def collect_run(starts, follow_run):
    """The elements to work on: the starts themselves, or everything joined to them through pipe connectors
    (pipes, fittings and accessories; equipment such as the detector ends the run)."""
    found = {}
    for s in starts:
        if s is None:
            continue
        if not follow_run:
            found[ec.eid(s)] = s
            continue
        if ec.eid(s) in found:
            continue
        parent, elements, order = ct.walk(s, is_run_part, domain=ct.PIPING)
        found.update(elements)
    return list(found.values())


# ---------------- Connections ----------------
def _connectors(el):
    return ct.conduit_connectors(el, ct.PIPING)


def _links(el):
    """Pairs (id, id) of el and each element physically joined to it."""
    own = ec.eid(el)
    out = set()
    for c in _connectors(el):
        try:
            if not c.IsConnected:
                continue
            for r in c.AllRefs:
                if r.ConnectorType == ConnectorType.Logical:
                    continue
                o = r.Owner
                if o is not None and ec.eid(o) != own:
                    out.add((min(own, ec.eid(o)), max(own, ec.eid(o))))
        except Exception:
            pass
    return out


def _alive(el):
    try:
        return el is not None and el.IsValidObject
    except Exception:
        return False


def _rejoin(a, b):
    """Join the closest open connectors of two elements, if they are within REJOIN_TOLERANCE. True if joined."""
    if not (_alive(a) and _alive(b)):
        return False
    best = None
    for ca in _connectors(a):
        if ca.IsConnected:
            continue
        for cb in _connectors(b):
            if cb.IsConnected:
                continue
            try:
                d = ca.Origin.DistanceTo(cb.Origin)
            except Exception:
                continue
            if d <= REJOIN_TOLERANCE and (best is None or d < best[0]):
                best = (d, ca, cb)
    if best is None:
        return False
    try:
        best[1].ConnectTo(best[2])
        return True
    except Exception:
        return False


# ---------------- Sizes and Routing Preferences ----------------
def _fitting_size(el):
    """Largest connector diameter of a fitting (feet), or None."""
    sizes = []
    for c in _connectors(el):
        try:
            sizes.append(c.Radius * 2.0)
        except Exception:
            pass
    return max(sizes) if sizes else None


def _family_part_type(symbol):
    try:
        return symbol.Family.get_Parameter(BuiltInParameter.FAMILY_CONTENT_PART_TYPE).AsInteger()
    except Exception:
        return None


def _size_ok(rule, size):
    if size is None:
        return True
    try:
        for i in range(rule.NumberOfCriteria):
            crit = rule.GetCriterion(i)
            if isinstance(crit, PrimarySizeCriterion):
                if size < crit.MinimumSize - SIZE_TOLERANCE or size > crit.MaximumSize + SIZE_TOLERANCE:
                    return False
    except Exception:
        pass
    return True


def replacement(doc, pipe_type, kind, size, sampling_lower):
    """The fitting type the pipe type's Routing Preferences give for this kind of fitting at this size, or None.
    The first rule (in Routing Preferences order) whose size range fits and whose family is that kind of fitting.
    Sampling point families are never picked."""
    group = GROUPS.get(kind)
    if group is None:
        return None
    rpm = pipe_type.RoutingPreferenceManager
    any_kind = []
    for i in range(rpm.GetNumberOfRules(group)):
        try:
            rule = rpm.GetRule(group, i)
            sym = doc.GetElement(rule.MEPPartId)
        except Exception:
            continue
        if sym is None or not _size_ok(rule, size):
            continue
        try:
            if sym.Family.Name.lower() in sampling_lower:
                continue
        except Exception:
            pass
        if _family_part_type(sym) == kind:
            return sym
        any_kind.append(sym)
    # A tee must come back as a tee (the Junctions group also holds taps); other groups only hold their own kind.
    if kind == int(PartType.Tee):
        return None
    return any_kind[0] if any_kind else None


# ---------------- ADDRESS ----------------
def port_number(pipe_type):
    """The pipe type's number: the last whole number in its name ("VESDA Pipe 1" -> 1), or None."""
    found = re.findall(r"\d+", ec.type_name(pipe_type) or "")
    return int(found[-1]) if found else None


def readdress(el, pattern, number):
    """Put number in el's ADDRESS where pattern's 2nd group is. Returns "changed", "same", or "skipped" (no
    ADDRESS, read-only, or not in the expected format)."""
    p = el.LookupParameter(ADDRESS_PARAM)
    if p is None or p.IsReadOnly:
        return "skipped"
    text = p.AsString() or ""
    if not pattern.search(text):
        return "skipped"
    new = pattern.sub(lambda m: m.group(1) + str(number) + "", text, 1)
    if new == text:
        return "same"
    p.Set(new)
    return "changed"


def detectors(pipes):
    """{pipe id: the Fire Alarm Device (detector) its run connects to, or None}. Each run is walked once."""
    out = {}
    for p in pipes:
        if ec.eid(p) in out:
            continue
        parent, elements, order = ct.walk(p, is_run_part, domain=ct.PIPING)
        found = None
        for el in elements.values():
            for group in ct.connected_elements(el, ct.PIPING):
                for n in group:
                    if found is None and ec.is_device(n):
                        found = n
            if found is not None:
                break
        for i in elements:
            out[i] = found
    return out


def pipe_address(detector, port):
    """'<Panel #>: PORT <port>', or 'ASD-##: PORT <port>' when there's no detector or it has no Panel #."""
    panel = ec.named_value(detector, PANEL_PARAM) if detector is not None else ""
    return "%s: PORT %d" % (panel or NO_PANEL, port)


def set_address(el, text):
    """Set el's ADDRESS. Returns "changed", "same" or "skipped" (no ADDRESS parameter, or read-only)."""
    p = el.LookupParameter(ADDRESS_PARAM)
    if p is None or p.IsReadOnly:
        return "skipped"
    if (p.AsString() or "") == text:
        return "same"
    p.Set(text)
    return "changed"


# ---------------- The swap ----------------
class Plan(object):
    """What a swap will change. Built from the collected elements and the current pipe types to swap."""
    def __init__(self, elements, swap_type_ids, sampling_lower, picked_fittings_only):
        self.sampling_lower = sampling_lower
        self.pipes = [e for e in elements if is_pipe(e) and ec.eid_int(e.GetTypeId()) in swap_type_ids]
        self.sampling = [e for e in elements if is_sampling(e, sampling_lower)]
        pipe_ids = set(ec.eid(p) for p in self.pipes)
        # Sampling points to renumber: those joined to a swapped pipe (picked or not).
        joined = {}
        for p in self.pipes:
            for group in ct.connected_elements(p, ct.PIPING):
                for n in group:
                    if is_sampling(n, sampling_lower):
                        joined[ec.eid(n)] = n
        self.sampling_on_pipes = list(joined.values())
        known = set(ec.eid(e) for e in self.sampling)
        self.sampling += [e for i, e in joined.items() if i not in known]     # protect them too
        self.fittings, self.kept_by_other_pipe = [], []
        for e in elements:
            if not is_fitting(e) or is_sampling(e, sampling_lower):
                continue
            if picked_fittings_only:
                self.fittings.append(e)
                continue
            # A fitting is swapped when it joins a pipe being swapped and no pipe that is staying as it is.
            joined_pipes = []
            for group in ct.connected_elements(e, ct.PIPING):
                joined_pipes.extend(n for n in group if is_pipe(n))
            # (A fitting joined only to other fittings, e.g. an elbow on a tee, is part of the run and is swapped.)
            if any(ec.eid(n) not in pipe_ids for n in joined_pipes):
                self.kept_by_other_pipe.append(e)
            else:
                self.fittings.append(e)
        # Results
        self.pipes_changed = 0
        self.fittings_changed = 0
        self.size_problems = []         # pipes whose size the new type couldn't keep
        self.no_rule = {}               # "kind at size" -> count, fittings left as they were
        self.other_kind = 0             # fittings of a kind with no Routing Preferences group (left as they were)
        self.broken = []                # (id, id) connections that came apart and couldn't be rejoined
        self.sampling_changed = []      # sampling points Revit changed or removed (the swap is undone)
        self.port = None                # the number put in ADDRESS (None: the type name has no number)
        self.addr_changed = {"pipe": 0, "sampling": 0}
        self.addr_skipped = {"pipe": 0, "sampling": 0}
        self.no_panel = 0               # pipes given ASD-## (no detector found, or it has no Panel #)

    def _watch(self):
        """{id: element} whose connections are checked afterwards: everything changed, the sampling points, and
        their neighbours."""
        out = {}
        for e in self.pipes + self.fittings + self.sampling:
            out[ec.eid(e)] = e
            for group in ct.connected_elements(e, ct.PIPING):
                for n in group:
                    out[ec.eid(n)] = n
        return out

    def _all_links(self, watch):
        links = set()
        for el in watch.values():
            if _alive(el):
                links |= _links(el)
        return links

    def apply(self, doc, target_type):
        watch = self._watch()
        self._watched = watch
        before = self._all_links(watch)
        sampling_types = [(s, ec.eid(s), s.GetTypeId()) for s in self.sampling]

        # 1. Pipes: new type, same size.
        for p in self.pipes:
            dp = p.get_Parameter(BuiltInParameter.RBS_PIPE_DIAMETER_PARAM)
            size = dp.AsDouble() if dp is not None else None
            if p.GetTypeId() != target_type.Id:
                p.ChangeTypeId(target_type.Id)
                self.pipes_changed += 1
            doc.Regenerate()
            dp = p.get_Parameter(BuiltInParameter.RBS_PIPE_DIAMETER_PARAM)
            if size is not None and dp is not None and abs(dp.AsDouble() - size) > SIZE_TOLERANCE:
                try:
                    dp.Set(size)
                except Exception:
                    pass
                if abs(dp.AsDouble() - size) > SIZE_TOLERANCE:
                    self.size_problems.append(p)

        # 2. Fittings: the new type's part for the same kind and size.
        for f in self.fittings:
            kind = part_type(f)
            if kind not in GROUPS:
                self.other_kind += 1
                continue
            size = _fitting_size(f)
            sym = replacement(doc, target_type, kind, size, self.sampling_lower)
            if sym is None:
                label = "%s at %s" % (KIND_NAMES.get(kind, "fitting"), _size_text(size))
                self.no_rule[label] = self.no_rule.get(label, 0) + 1
                continue
            if f.GetTypeId() == sym.Id:
                continue
            if not sym.IsActive:
                sym.Activate()
                doc.Regenerate()
            f.ChangeTypeId(sym.Id)
            self.fittings_changed += 1
        doc.Regenerate()

        # 3. Sampling points must be exactly as they were.
        for el, sid, tid in sampling_types:
            if not _alive(el):
                self.sampling_changed.append(sid)
            elif el.GetTypeId() != tid:
                try:
                    el.ChangeTypeId(tid)
                except Exception:
                    self.sampling_changed.append(sid)

        # 4. ADDRESS: port / P# number of the new type.
        self.port = port_number(target_type)
        if self.port is not None:
            found = detectors(self.pipes)
            for el in self.pipes:
                if not _alive(el):
                    continue
                det = found.get(ec.eid(el))
                text = pipe_address(det, self.port)
                if text.startswith(NO_PANEL + ":"):
                    self.no_panel += 1
                self._count("pipe", set_address(el, text))
            for el in self.sampling_on_pipes:
                if _alive(el):
                    self._count("sampling", readdress(el, SAMPLING_PIPE, self.port))

        # 5. Connections: rejoin anything that came apart.
        doc.Regenerate()
        after = self._all_links(watch)
        for a, b in sorted(before - after):
            if not _rejoin(watch.get(a), watch.get(b)):
                self.broken.append((a, b))
        doc.Regenerate()

    def _count(self, kind, result):
        if result == "changed":
            self.addr_changed[kind] += 1
        elif result == "skipped":
            self.addr_skipped[kind] += 1

    def summary(self, target_name):
        lines = ["Swapped to %s:" % target_name,
                 "  %d pipe(s) changed" % self.pipes_changed,
                 "  %d fitting(s) changed" % self.fittings_changed,
                 "  %d sampling point(s) left as they were" % len(self.sampling)]
        if self.port is None:
            lines.append("  ADDRESS not renumbered: '%s' has no number in its name" % target_name)
        else:
            lines.append("  ADDRESS set to PORT %d on %d pipe(s) and P%d on %d sampling point(s)"
                         % (self.port, self.addr_changed["pipe"], self.port, self.addr_changed["sampling"]))
            if self.no_panel:
                lines.append("  %d pipe(s) addressed %s: PORT %d - no detector with a Panel # found on the run"
                             % (self.no_panel, NO_PANEL, self.port))
            if self.addr_skipped["pipe"]:
                lines.append("  %d pipe(s) have no editable ADDRESS parameter" % self.addr_skipped["pipe"])
            if self.addr_skipped["sampling"]:
                lines.append("  %d sampling point ADDRESS value(s) left as they were: blank or not 'P#:S#:H#'"
                             % self.addr_skipped["sampling"])
        if self.kept_by_other_pipe:
            lines.append("  %d fitting(s) left as they were: they also join a pipe that isn't being swapped"
                         % len(self.kept_by_other_pipe))
        if self.other_kind:
            lines.append("  %d fitting(s) of another kind left as they were" % self.other_kind)
        if self.no_rule:
            lines.append("")
            lines.append("No Routing Preferences part in %s for (left as they were):" % target_name)
            for label in sorted(self.no_rule):
                lines.append("  %d x %s" % (self.no_rule[label], label))
        if self.size_problems:
            lines.append("")
            lines.append("%d pipe(s) couldn't keep their size in %s (check its pipe segment sizes)."
                         % (len(self.size_problems), target_name))
        if self.broken:
            lines.append("")
            lines.append("%d connection(s) came apart and couldn't be rejoined; those elements are selected."
                         % len(self.broken))
        return "\n".join(lines)

    def problem_elements(self):
        """The elements to leave selected: pipes that lost their size and both ends of each break."""
        out = dict((ec.eid(p), p) for p in self.size_problems)
        watched = getattr(self, "_watched", {})
        for pair in self.broken:
            for i in pair:
                el = watched.get(i)
                if _alive(el):
                    out[i] = el
        return list(out.values())

    def changed_elements(self):
        return [e for e in self.pipes + self.fittings if _alive(e)]


def _size_text(size):
    if size is None:
        return "unknown size"
    inches = size * 12.0
    return ('%g"' % round(inches, 3))
