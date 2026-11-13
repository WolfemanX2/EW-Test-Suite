# -*- coding: utf-8 -*-
# Auto Conduit script - version v4
__title__ = "Auto\nConduit"
__doc__ = ("Pick devices or their tags in order (Esc when finished, then confirm); plans orthogonal conduit "
           "for the whole chain, choosing connectors to keep front approaches open, at a chosen elevation "
           "from the current view's level. Wall devices (per Routing Preferences) are entered from the "
           "front or back only. Each run uses the conduit type set for the family it leaves.")

import heapq
import itertools
import math
from pyrevit import revit, forms
from Autodesk.Revit.DB import (
    XYZ, Domain, FilteredElementCollector, BuiltInCategory, ElementId,
    ElementMulticategoryFilter, BoundingBoxIntersectsFilter, Outline,
    BuiltInParameter, Transaction, TransactionGroup, FamilyInstance, IndependentTag,
    OverrideGraphicSettings, Color, FillPatternElement, ElementTransformUtils
)
from Autodesk.Revit.DB.Electrical import Conduit, ConduitType
from Autodesk.Revit.UI.Selection import ObjectType, ISelectionFilter
from Autodesk.Revit.Exceptions import OperationCanceledException
from System.Collections.Generic import List
from System.Windows.Input import Keyboard, ModifierKeys

import mounting_rules

doc = revit.doc
uidoc = revit.uidoc

# ---------------- Settings (feet) ----------------
DEBUG = False                   # True = print obstacles, planner options and search statistics
AVOID_MODEL_OBSTACLES = False   # True = route around framing, columns, duct, pipe, tray and equipment
                                # (slowest option; False skips the model scan entirely)
AVOID_EXISTING_CONDUIT = False  # True = treat existing conduit and fittings as obstacles
AVOID_PLANNED_RUNS = True       # True = later links in a chain stay clear of earlier links in the same chain
                                # (cheap; keeps the runs in and out of one device from overlapping)
STUB_LEN = 1.0            # straight run out of each connector (must leave room for an elbow)
WALL_MIN_LEG = 2.0        # wall devices: MINIMUM straight horizontal leg out of the front/back; longer is fine
WALL_FRONT_SIGN = -1.0    # -1.0 = device front is opposite the family's FacingOrientation; 1.0 = same
CLEARANCE = 0.05          # inflate model obstacles by this
PLANNED_HALF = 0.08       # half-width of the box around runs planned earlier in the same chain
TURN_PENALTY = 2.0        # cost per bend (feet-equivalent)
FINAL_BEND_EXTRA = 0.5    # extra cost when a wall-device run must bend right before entering the device,
                          # so long straight approaches into the device are preferred
MARGIN = 5.0              # search region margin around the endpoints
MAX_OBSTACLES = 1500
MAX_EXPANSIONS = 300000
MAX_BRANCH = 6            # connector options considered per link
MAX_ATTEMPTS = 2000       # link-planning calculations per chain (repeat questions are cached and free)
MAX_NODES = 20000         # total search steps per chain, cached or not
MIN_SEG = 0.05            # drop duplicate points closer than this
MIN_RUN = 0.5             # reject routes with any segment shorter than this (elbows need room)
BACK_PENALTY = 0.5        # a back approach must be shorter than the front by more than this to be chosen
UP_THRESHOLD = 0.7        # connector counts as "top/upward" if direction Z component > this
REQUIRE_UPWARD = False    # ceiling devices: True = refuse links without an upward connector
DEFAULT_ELEVATION_TEXT = "15'-0\""
HIGHLIGHT_PICKED = True   # colour devices (and picked tags) in the active view while selecting; removed afterwards
HIGHLIGHT_COLOR = (255, 0, 160)   # R, G, B
HIGHLIGHT_WEIGHT = 6      # line weight (1-16) used for highlighted devices
OPT_ADD_AGAIN = "Add it again (conduit will return to this device)"
OPT_IGNORE = "Ignore this pick"
OPT_REMOVE = "Remove it from the chain"
OPT_UNDO = "Undo last pick"
OPT_SKIP_DEV = "Skip this device (connect the legs before it)"
OPT_ADJUST = "Adjust device location"
OPT_CANCEL_CHAIN = "Cancel (create nothing)"
OPT_CLOSEST = "Use closest connector"
OPT_SKIP = "Skip device"
OPT_FINISH = "Finished - create conduit"
OPT_CONTINUE = "Continue selecting"
OPT_CANCEL = "Cancel (discard selection)"
OBSTACLE_CATS = [
    BuiltInCategory.OST_StructuralFraming, BuiltInCategory.OST_StructuralColumns,
    BuiltInCategory.OST_DuctCurves, BuiltInCategory.OST_PipeCurves,
    BuiltInCategory.OST_CableTray,
    BuiltInCategory.OST_MechanicalEquipment, BuiltInCategory.OST_ElectricalEquipment,
]
EXISTING_CONDUIT_CATS = [
    BuiltInCategory.OST_Conduit, BuiltInCategory.OST_ConduitFitting,
]
# -------------------------------------------------

DEBUG_LOG = []
OBSTACLE_INFO = []   # (element id, category, name, min xyz, max xyz) for each obstacle box (DEBUG only)


def dlog(msg):
    if DEBUG and len(DEBUG_LOG) < 400:
        DEBUG_LOG.append(msg)


def eid(x):
    """Integer value of an ElementId (works across Revit versions)."""
    i = x.Id if hasattr(x, "Id") else x
    try:
        return i.Value
    except Exception:
        return i.IntegerValue


def element_label(el):
    try:
        return "{} : {} (id {})".format(el.Symbol.Family.Name, el.Name, eid(el))
    except Exception:
        return "id {}".format(eid(el))


class DeviceOrTagFilter(ISelectionFilter):
    """Accepts family instances (devices) and tags."""
    def AllowElement(self, e):
        return isinstance(e, FamilyInstance) or isinstance(e, IndependentTag)

    def AllowReference(self, r, p):
        return False


def conduit_connectors(el):
    out = []
    cm = None
    try:
        cm = el.MEPModel.ConnectorManager
    except Exception:
        pass
    if cm is None:
        return out
    for c in cm.Connectors:
        try:
            if c.Domain == Domain.DomainCableTrayConduit:
                out.append(c)
        except Exception:
            pass
    return out


def tagged_elements(tag):
    """Elements in this model that a tag is hosted to."""
    out = []
    try:
        out = list(tag.GetTaggedLocalElements())
    except Exception:
        try:
            e = doc.GetElement(tag.TaggedLocalElementId)
            if e is not None:
                out = [e]
        except Exception:
            pass
    return out


def resolve_element(el):
    """A picked device returns itself; a picked tag returns the family instance it tags (or None)."""
    if isinstance(el, FamilyInstance):
        return el
    if isinstance(el, IndependentTag):
        cands = [e for e in tagged_elements(el) if isinstance(e, FamilyInstance)]
        for e in cands:
            if conduit_connectors(e):
                return e
        return cands[0] if cands else None
    return None


def is_up(c):
    return c.CoordinateSystem.BasisZ.Z > UP_THRESHOLD


def free_top_count(el):
    return len([c for c in conduit_connectors(el) if not c.IsConnected and is_up(c)])


def dominant_axis(x, y):
    """Axis-aligned unit direction closest to the horizontal vector (x, y)."""
    if abs(x) >= abs(y):
        return (1 if x >= 0 else -1, 0, 0)
    return (0, 1 if y >= 0 else -1, 0)


def horizontal_facing(el):
    """Unit (x, y) of the element's facing direction projected to plan, or None."""
    try:
        f = el.FacingOrientation
    except Exception:
        return None
    x, y = f.X, f.Y
    n = math.sqrt(x * x + y * y)
    if n < 1e-6:
        return None
    return (x / n, y / n)


def parse_length(text):
    """Parse a length string using project units; fall back to plain feet."""
    text = (text or "").strip()
    if not text:
        return None
    try:
        from Autodesk.Revit.DB import UnitFormatUtils, SpecTypeId
        ok, val = UnitFormatUtils.TryParse(doc.GetUnits(), SpecTypeId.Length, text)
        if ok:
            return val
    except Exception:
        pass
    try:
        return float(text)
    except Exception:
        return None


# ---------------- plain-tuple geometry (no Revit API calls in the hot loops) ----------------

def dist(p, q):
    dx, dy, dz = q[0] - p[0], q[1] - p[1], q[2] - p[2]
    return math.sqrt(dx * dx + dy * dy + dz * dz)


def in_region(bx, lo, hi):
    return not (bx[3] < lo[0] or bx[0] > hi[0] or bx[4] < lo[1] or bx[1] > hi[1]
                or bx[5] < lo[2] or bx[2] > hi[2])


def seg_boxes(pts):
    """Thin boxes for runs planned earlier in the chain, so later links avoid them."""
    out = []
    h = PLANNED_HALF
    for i in range(len(pts) - 1):
        p, q = pts[i], pts[i + 1]
        out.append((min(p[0], q[0]) - h, min(p[1], q[1]) - h, min(p[2], q[2]) - h,
                    max(p[0], q[0]) + h, max(p[1], q[1]) + h, max(p[2], q[2]) + h))
    return out


def seg_hits_box(p, q, bx):
    """Exact test: does the segment p-q pass through the inside of the box?"""
    t0, t1 = 0.0, 1.0
    for k in range(3):
        d = q[k] - p[k]
        lo, hi = bx[k], bx[k + 3]
        if abs(d) < 1e-9:
            if p[k] <= lo or p[k] >= hi:
                return False
        else:
            ta = (lo - p[k]) / d
            tb = (hi - p[k]) / d
            if ta > tb:
                ta, tb = tb, ta
            if ta > t0:
                t0 = ta
            if tb < t1:
                t1 = tb
            if t0 >= t1:
                return False
    return (t1 - t0) > 1e-9


def pre_blocked(pre, boxes):
    if not boxes:
        return False
    for i in range(len(pre) - 1):
        p, q = pre[i], pre[i + 1]
        if dist(p, q) < 1e-6:
            continue
        for bx in boxes:
            if seg_hits_box(p, q, bx):
                return True
    return False


def simplify(pts):
    """Remove duplicate and collinear points."""
    out = []
    for p in pts:
        if out and dist(p, out[-1]) < MIN_SEG:
            continue
        out.append(p)
    i = 1
    while i < len(out) - 1:
        a, b, c = out[i - 1], out[i], out[i + 1]
        v1 = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
        v2 = (c[0] - b[0], c[1] - b[1], c[2] - b[2])
        cx = v1[1] * v2[2] - v1[2] * v2[1]
        cy = v1[2] * v2[0] - v1[0] * v2[2]
        cz = v1[0] * v2[1] - v1[1] * v2[0]
        cross = math.sqrt(cx * cx + cy * cy + cz * cz)
        l1 = math.sqrt(v1[0] * v1[0] + v1[1] * v1[1] + v1[2] * v1[2])
        l2 = math.sqrt(v2[0] * v2[0] + v2[1] * v2[1] + v2[2] * v2[2])
        dot = v1[0] * v2[0] + v1[1] * v2[1] + v1[2] * v2[2]
        if cross < 1e-6 * max(1.0, l1 * l2) and dot > 0:
            del out[i]
            if i > 1:
                i -= 1   # the previous corner may have become collinear
        else:
            i += 1
    return out


def has_reversal(pts):
    for i in range(1, len(pts) - 1):
        a, b, c = pts[i - 1], pts[i], pts[i + 1]
        l1, l2 = dist(a, b), dist(b, c)
        if l1 < 1e-9 or l2 < 1e-9:
            continue
        dot = ((b[0] - a[0]) * (c[0] - b[0]) + (b[1] - a[1]) * (c[1] - b[1])
               + (b[2] - a[2]) * (c[2] - b[2]))
        if dot / (l1 * l2) < -0.999:
            return True
    return False


def route(p_start, d_start, p_end, boxes, lo, hi, end_forbid=None, end_dir=None):
    """Planar A* on a Hanan-style grid in the Z plane of p_start.
    boxes must already be limited to obstacles that span that Z plane.
    The route starts travelling in d_start and may continue straight or turn at any grid line.
    end_forbid = a direction the route may not be travelling in when it reaches p_end.
    end_dir = the direction the conduit must continue in after p_end (straight into the device);
              arriving in any other direction costs one extra bend."""
    z = p_start[2]
    xs = set(round(v, 6) for v in (p_start[0], p_end[0], lo[0], hi[0], (p_start[0] + p_end[0]) / 2.0))
    ys = set(round(v, 6) for v in (p_start[1], p_end[1], lo[1], hi[1], (p_start[1] + p_end[1]) / 2.0))
    for b in boxes:
        xs.add(round(b[0], 6))
        xs.add(round(b[3], 6))
        ys.add(round(b[1], 6))
        ys.add(round(b[4], 6))
    gx, gy = sorted(xs), sorted(ys)
    nx, ny = len(gx), len(gy)
    ix = dict((v, i) for i, v in enumerate(gx))
    iy = dict((v, i) for i, v in enumerate(gy))

    start = (ix[round(p_start[0], 6)], iy[round(p_start[1], 6)])
    goal = (ix[round(p_end[0], 6)], iy[round(p_end[1], 6)])
    goal_x, goal_y = gx[goal[0]], gy[goal[1]]

    def d2(d):
        return (d[0], d[1]) if d is not None else None

    d_start, end_forbid, end_dir = d2(d_start), d2(end_forbid), d2(end_dir)

    blocked_cache = {}

    def edge_blocked(k1, k2):
        ek = (k1, k2) if k1 < k2 else (k2, k1)
        res = blocked_cache.get(ek)
        if res is None:
            mx = (gx[k1[0]] + gx[k2[0]]) / 2.0
            my = (gy[k1[1]] + gy[k2[1]]) / 2.0
            res = False
            for bx in boxes:
                if bx[0] < mx < bx[3] and bx[1] < my < bx[4]:
                    res = True
                    break
            blocked_cache[ek] = res
        return res

    def h(k):
        return abs(gx[k[0]] - goal_x) + abs(gy[k[1]] - goal_y)

    dirs = ((1, 0), (-1, 0), (0, 1), (0, -1))
    counter = itertools.count()
    heap = [(h(start), next(counter), 0.0, start, d_start, None)]
    best = {}
    parent = {}
    expansions = 0
    while heap:
        f, _, g, k, d, par = heapq.heappop(heap)
        state = (k, d)
        if state in best and best[state] <= g:
            continue
        best[state] = g
        parent[state] = par
        if k == goal and (end_forbid is None or d != end_forbid):
            path = []
            s = state
            while s is not None:
                path.append((gx[s[0][0]], gy[s[0][1]], z))
                s = parent[s]
            path.reverse()
            return path
        expansions += 1
        if expansions > MAX_EXPANSIONS:
            return None
        for nd in dirs:
            if d is not None and nd[0] == -d[0] and nd[1] == -d[1]:
                continue
            nk = (k[0] + nd[0], k[1] + nd[1])
            if nk[0] < 0 or nk[0] >= nx or nk[1] < 0 or nk[1] >= ny:
                continue
            if boxes and edge_blocked(k, nk):
                continue
            step = abs(gx[nk[0]] - gx[k[0]]) + abs(gy[nk[1]] - gy[k[1]])
            ng = g + step + (TURN_PENALTY if (d is not None and nd != d) else 0.0)
            if nk == goal and end_dir is not None and nd != end_dir:
                ng += TURN_PENALTY + FINAL_BEND_EXTRA   # the conduit must still turn into the device
            prev = best.get((nk, nd))
            if prev is not None and prev <= ng:
                continue
            heapq.heappush(heap, (ng + h(nk), next(counter), ng, nk, nd, state))
    return None


# ---------------- obstacles ----------------

def collect_obstacles(lo, hi, exclude_ids):
    """Inflated bounding boxes of model obstacles inside the region. Empty when avoidance is switched off."""
    del OBSTACLE_INFO[:]
    cat_list = []
    if AVOID_MODEL_OBSTACLES:
        cat_list += OBSTACLE_CATS
    if AVOID_EXISTING_CONDUIT:
        cat_list += EXISTING_CONDUIT_CATS
    if not cat_list:
        return []
    cats = List[BuiltInCategory](cat_list)
    collector = (FilteredElementCollector(doc)
                 .WherePasses(ElementMulticategoryFilter(cats))
                 .WhereElementIsNotElementType())
    try:
        # quick filter: lets Revit discard everything outside the region before Python sees it
        collector = collector.WherePasses(BoundingBoxIntersectsFilter(Outline(XYZ(*lo), XYZ(*hi))))
    except Exception:
        pass
    boxes = []
    for e in collector:
        if eid(e) in exclude_ids:
            continue
        bb = e.get_BoundingBox(None)
        if bb is None:
            continue
        mn, mx = bb.Min, bb.Max
        box = (mn.X - CLEARANCE, mn.Y - CLEARANCE, mn.Z - CLEARANCE,
               mx.X + CLEARANCE, mx.Y + CLEARANCE, mx.Z + CLEARANCE)
        if not in_region(box, lo, hi):
            continue
        boxes.append(box)
        if DEBUG:
            try:
                cat = e.Category.Name if e.Category else "?"
            except Exception:
                cat = "?"
            try:
                nm = e.Name
            except Exception:
                nm = ""
            OBSTACLE_INFO.append((eid(e), cat, nm, (mn.X, mn.Y, mn.Z), (mx.X, mx.Y, mx.Z)))
        if len(boxes) >= MAX_OBSTACLES:
            break
    return boxes


# ---------------- connectors and approaches ----------------

def closest_conn(conduit, pt):
    best, bd = None, 1e9
    for c in conduit.ConnectorManager.Connectors:
        d = c.Origin.DistanceTo(pt)
        if d < bd:
            best, bd = c, d
    return best


def port_key(el, c):
    o = c.Origin
    return (eid(el), round(o.X, 4), round(o.Y, 4), round(o.Z, 4))


def free_ports(el, is_wall, allow_fallback, used):
    """Unconnected, unused Conduit connectors eligible for this element, as (connector, key) pairs.
    Top connectors are used when there are any."""
    free = []
    for c in conduit_connectors(el):
        if c.IsConnected:
            continue
        k = port_key(el, c)
        if k not in used:
            free.append((c, k))
    if not free:
        return [], "has no unconnected Conduit connector left"
    ups = [ck for ck in free if is_up(ck[0])]
    if ups:
        return ups, None
    if is_wall and allow_fallback:
        return free, None
    if is_wall:
        return [], "has no unconnected top Conduit connector"
    if REQUIRE_UPWARD:
        return [], "has no unconnected upward-facing Conduit connector"
    return free, None


def stub_and_riser(conn, z_target):
    """(origin, stub end, riser top) as tuples, or None if the riser would run back into the device."""
    d = conn.CoordinateSystem.BasisZ
    o = conn.Origin
    ox, oy, oz = o.X, o.Y, o.Z
    dz = d.Z
    sx, sy, sz = ox + d.X * STUB_LEN, oy + d.Y * STUB_LEN, oz + dz * STUB_LEN
    riser = z_target - sz
    if abs(riser) > 1e-6 and riser * dz < 0:
        return None
    return (ox, oy, oz), (sx, sy, sz), (sx, sy, z_target)


def build_approaches(el, conn, is_wall, z_target):
    """Point sequences from the connector to the planar routing start.
    Ceiling: connector -> stub -> riser top.
    Wall: connector -> stub -> riser top -> WALL_MIN_LEG out of the front (or back).
    The router may continue straight past that point, so the leg is a minimum, not a fixed length."""
    sr = stub_and_riser(conn, z_target)
    if sr is None:
        return []
    base = list(sr)
    up = sr[2]
    f = horizontal_facing(el) if is_wall else None
    if f is None:
        return [{"pre": base, "start": up, "dir": None, "back": 0}]
    out = []
    for sign, back in ((WALL_FRONT_SIGN, 0), (-WALL_FRONT_SIGN, 1)):
        vx, vy = f[0] * sign, f[1] * sign
        p = (up[0] + vx * WALL_MIN_LEG, up[1] + vy * WALL_MIN_LEG, z_target)
        out.append({"pre": base + [p], "start": p, "dir": dominant_axis(vx, vy), "back": back})
    return out


# ---------------- planning ----------------

def link_options(ea, eb, wall_a, wall_b, fb_a, fb_b, z_target, used, static_boxes, planned_boxes,
                 link_no, cache):
    """All valid routes for one link, best first. Returns (options, reason).
    Results are cached: the answer only depends on which connectors are still free and on the
    earlier planned runs that pass near this link."""
    ca, ra = free_ports(ea, wall_a, fb_a, used)
    if not ca:
        return [], "{} {}".format(element_label(ea), ra)
    cb, rb = free_ports(eb, wall_b, fb_b, used)
    if not cb:
        return [], "{} {}".format(element_label(eb), rb)

    apps_cache = cache["apps"]

    def side_approaches(el, ports, is_wall):
        out = []
        for c, k in ports:
            apps = apps_cache.get(k)
            if apps is None:
                apps = build_approaches(el, c, is_wall, z_target)
                apps_cache[k] = apps
            for ap in apps:
                out.append((c, k, ap))
        return out

    sa = side_approaches(ea, ca, wall_a)
    sb = side_approaches(eb, cb, wall_b)
    if not sa or not sb:
        return [], ("the chosen elevation is on the wrong side of a connector "
                    "(riser would run back into the device); use a higher elevation")

    # one search region per link (covers every candidate connector on both devices)
    lo = [1e30, 1e30, 1e30]
    hi = [-1e30, -1e30, -1e30]
    for _, _, ap in sa + sb:
        for p in ap["pre"]:
            for k in range(3):
                if p[k] < lo[k]:
                    lo[k] = p[k]
                if p[k] > hi[k]:
                    hi[k] = p[k]
    lo = tuple(v - MARGIN for v in lo)
    hi = tuple(v + MARGIN for v in hi)

    near = tuple(bx for bx in planned_boxes if in_region(bx, lo, hi))
    key = (link_no, tuple(k for _, k in ca), tuple(k for _, k in cb), near)
    hit = cache["links"].get(key)
    if hit is not None:
        cache["hits"] += 1
        return hit
    if cache["misses"] >= MAX_ATTEMPTS:
        return [], "search limit reached (MAX_ATTEMPTS)"
    cache["misses"] += 1

    boxes = [bx for bx in static_boxes if in_region(bx, lo, hi)]
    boxes.extend(near)
    flat = [bx for bx in boxes if bx[2] < z_target < bx[5]]   # only these can block the level run

    def tag(k, ap):
        return "@({:.2f},{:.2f}) {}".format(k[1], k[2], "back" if ap["back"] else "front")

    reason = "no pairs tested"

    def clear(side, which):
        ok, why = [], None
        for item in side:
            if pre_blocked(item[2]["pre"], boxes):
                why = "a riser or wall leg at the {} device is blocked by an obstacle".format(which)
                if DEBUG:
                    dlog("Link {}: {} {}: {}".format(link_no, which, tag(item[1], item[2]), why))
            else:
                ok.append(item)
        return ok, why

    ok_a, why_a = clear(sa, "first")
    ok_b, why_b = clear(sb, "second")
    reason = why_b or why_a or reason

    results = []
    for a, ka, A in ok_a:
        for b, kb, B in ok_b:
            if dist(A["start"], B["start"]) < 1e-6:
                plane = [A["start"]]
            else:
                end_dir = tuple(-c for c in B["dir"]) if B["dir"] else None
                plane = route(A["start"], A["dir"], B["start"], flat, lo, hi,
                              end_forbid=B["dir"], end_dir=end_dir)
            if not plane:
                why = "no clear orthogonal path at the chosen elevation"
            else:
                pts = simplify(A["pre"] + plane + B["pre"][::-1])
                why = None
                if len(pts) < 2 or has_reversal(pts):
                    why = "route doubles back on itself"
                else:
                    segs = [dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]
                    if min(segs) < MIN_RUN:
                        why = ("shortest segment is {:.2f} ft (< MIN_RUN {:.2f}); elbows won't fit. "
                               "Try a different elevation or smaller MIN_RUN").format(min(segs), MIN_RUN)
            if why:
                reason = why
                if DEBUG:
                    dlog("Link {}: A{} -> B{}: {}".format(link_no, tag(ka, A), tag(kb, B), why))
                continue
            length = sum(segs)
            backs = A["back"] + B["back"]
            if DEBUG:
                dlog("Link {}: A{} -> B{}: OK, length {:.2f} ft, {} bends".format(
                    link_no, tag(ka, A), tag(kb, B), length, len(pts) - 2))
            # cost = length plus a back penalty: front wins unless the back is shorter by more than BACK_PENALTY
            results.append({"len": length, "backs": backs, "cost": length + BACK_PENALTY * backs,
                            "pts": pts, "a": a, "b": b, "ka": ka, "kb": kb})

    if results:
        results.sort(key=lambda r: r["cost"])
        out = (results, None)
    else:
        out = ([], reason)
    cache["links"][key] = out
    return out


def solve_chain(seq, walls, fallback, z_target, static_boxes):
    """Search connector choices for the whole chain and keep the lowest cost plan.
    Cost = total length + BACK_PENALTY per back approach.
    Returns (plan, reason, fail_index, partial):
      success: (plan, None, None, None)
      failure: (None, why, index of the link that could not be routed (0-based; it joins seq[index] to
                seq[index + 1]), the best plan for the links before it - possibly empty)"""
    total = len(seq) - 1

    cache = {"apps": {}, "links": {}, "hits": 0, "misses": 0}

    def options(i, used, pboxes):
        ea, eb = seq[i], seq[i + 1]
        ia, ib = eid(ea), eid(eb)
        return link_options(ea, eb, ia in walls, ib in walls, ia in fallback, ib in fallback,
                            z_target, used, static_boxes, pboxes, i + 1, cache)

    # remaining[i] = the cost of links i onward if each had every connector free and no earlier runs
    # in its way. A plan can practically never beat that, so branches that can't win are dropped early.
    # (These calculations are cached and reused by the search itself.)
    remaining = [0.0] * (total + 1)
    for i in range(total - 1, -1, -1):
        opts, _ = options(i, frozenset(), ())
        remaining[i] = remaining[i + 1] + (opts[0]["cost"] if opts else 0.0)

    best = [None, None]   # [cost, chosen links]
    nodes = [0]
    partial = [0, None, []]   # deepest run of links from the start that could be planned: [links, cost, plan]
    fail = [-1, "no connector combination found"]   # deepest link that failed: [index, message]

    def rec(i, used, pboxes, cost, chosen):
        if i == total:
            if best[0] is None or cost < best[0]:
                best[0] = cost
                best[1] = list(chosen)
                dlog("Complete plan found, cost {:.2f}".format(cost))
            return
        if i > partial[0] or (i == partial[0] and i > 0 and cost < partial[1]):
            partial[0], partial[1], partial[2] = i, cost, list(chosen)
        nodes[0] += 1
        if nodes[0] > MAX_NODES:
            if fail[0] < 0:
                fail[0], fail[1] = i, "search limit reached (MAX_NODES)"
            return
        opts, reason = options(i, used, pboxes)
        if not opts:
            msg = "Link {} of {} failed: {}".format(i + 1, total, reason)
            if i > fail[0]:   # keep the first message at the deepest link: it comes from the best options
                fail[0], fail[1] = i, msg
            dlog(msg)
            return
        for o in opts[:MAX_BRANCH]:
            c2 = cost + o["cost"]
            if best[0] is not None and c2 + remaining[i + 1] >= best[0]:
                break   # options are sorted, so nothing later in the list can win either
            nxt = pboxes + tuple(seg_boxes(o["pts"])) if AVOID_PLANNED_RUNS else pboxes
            chosen.append(o)
            rec(i + 1, used | frozenset((o["ka"], o["kb"])), nxt, c2, chosen)
            chosen.pop()

    rec(0, frozenset(), (), 0.0, [])
    dlog("Search: {} steps, {} link calculations, {} cache hits".format(
        nodes[0], cache["misses"], cache["hits"]))
    if best[1] is not None:
        return best[1], None, None, None
    return None, fail[1], max(fail[0], 0), partial[2][:max(fail[0], 0)]


# ---------------- recovering from a link that can't be routed ----------------

def inches_text(v):
    return "{:.2f} in".format(abs(v) * 12.0)


def alignment_moves(ea, eb, walls, z_target):
    """Small moves of device eb that would line it up with ea, smallest first: [(XYZ, description)].
    A device that sits slightly off the line of the one before it needs a jog shorter than MIN_RUN,
    which can't be built; nudging it onto the line removes the jog."""
    def starts(el):
        out = []
        for c in conduit_connectors(el):
            if c.IsConnected:
                continue
            for ap in build_approaches(el, c, eid(el) in walls, z_target):
                out.append(ap["start"])
        return out

    found = {}
    for a in starts(ea):
        for b in starts(eb):
            dx, dy = b[0] - a[0], b[1] - a[1]
            for off, other, axis in ((dx, dy, 0), (dy, dx, 1)):
                # slightly off in this direction, and properly apart (or exactly lined up) in the other
                if 1e-4 < abs(off) < MIN_RUN and not (1e-4 < abs(other) < MIN_RUN):
                    key = (axis, round(-off, 4))
                    found[key] = abs(off)
    out = []
    for (axis, move), size in sorted(found.items(), key=lambda kv: kv[1]):
        vec = XYZ(move, 0, 0) if axis == 0 else XYZ(0, move, 0)
        way = (("east (+X)" if move > 0 else "west (-X)") if axis == 0
               else ("north (+Y)" if move > 0 else "south (-Y)"))
        out.append((vec, "{} toward project {}".format(inches_text(size), way)))
    return out


def adjust_device(ea, eb, moves, walls, fallback, z_target, static_boxes):
    """Move eb by the first of the candidate moves that makes the link from ea routable.
    Returns the description of the move made, or None if none worked (nothing is changed then)."""
    for vec, text in moves[:6]:
        t = Transaction(doc, "Auto Conduit: adjust device")
        t.Start()
        try:
            ElementTransformUtils.MoveElement(doc, eb.Id, vec)
            doc.Regenerate()
            ia, ib = eid(ea), eid(eb)
            cache = {"apps": {}, "links": {}, "hits": 0, "misses": 0}
            opts, _ = link_options(ea, eb, ia in walls, ib in walls, ia in fallback, ib in fallback,
                                   z_target, frozenset(), static_boxes, (), 0, cache)
            if opts:
                t.Commit()
                return text
            t.RollBack()
        except Exception:
            try:
                if t.HasStarted() and not t.HasEnded():
                    t.RollBack()
            except Exception:
                pass
    return None


# ---------------- creation ----------------

def create_link(a, b, pts, ctype, level_id):
    """Create conduit + fittings for one link in its own transaction. Returns list of conduits."""
    t = Transaction(doc, "Auto Conduit link")
    t.Start()
    try:
        xyz = [XYZ(*p) for p in pts]
        conduits = [Conduit.Create(doc, ctype.Id, xyz[i], xyz[i + 1], level_id)
                    for i in range(len(xyz) - 1)]
        try:
            dia = a.Radius * 2.0
            if dia > 0:
                for c in conduits:
                    p = c.get_Parameter(BuiltInParameter.RBS_CONDUIT_DIAMETER_PARAM)
                    if p and not p.IsReadOnly:
                        p.Set(dia)
        except Exception:
            pass
        for conduit, dev_conn in ((conduits[0], a), (conduits[-1], b)):
            closest_conn(conduit, dev_conn.Origin).ConnectTo(dev_conn)
        for i in range(len(conduits) - 1):
            shared = xyz[i + 1]
            ca = closest_conn(conduits[i], shared)
            cb = closest_conn(conduits[i + 1], shared)
            try:
                doc.Create.NewElbowFitting(ca, cb)
            except Exception:
                try:
                    ca.ConnectTo(cb)
                except Exception:
                    pass
        t.Commit()
        return conduits
    except Exception:
        t.RollBack()
        raise


# ---------------- UI ----------------

def make_highlight():
    """Graphic override used to mark picked devices, or None if it can't be built."""
    try:
        col = Color(*HIGHLIGHT_COLOR)
        ogs = OverrideGraphicSettings()
        ogs.SetProjectionLineColor(col)
        ogs.SetProjectionLineWeight(HIGHLIGHT_WEIGHT)
    except Exception:
        return None
    try:   # solid colour fill as well, where the Revit version supports it
        for fp in FilteredElementCollector(doc).OfClass(FillPatternElement):
            if fp.GetFillPattern().IsSolidFill:
                ogs.SetSurfaceForegroundPatternId(fp.Id)
                ogs.SetSurfaceForegroundPatternColor(col)
                break
    except Exception:
        pass
    return ogs


def highlight(ogs, ids):
    """Apply the highlight override to elements in the active view. Returns False if Revit refused."""
    t = Transaction(doc, "Auto Conduit highlight")
    try:
        t.Start()
        view = doc.ActiveView
        for i in ids:
            view.SetElementOverrides(i, ogs)
        t.Commit()
        uidoc.RefreshActiveView()
        return True
    except Exception:
        try:
            if t.HasStarted() and not t.HasEnded():
                t.RollBack()
        except Exception:
            pass
        return False


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


def shift_down():
    """True while a Shift key is held."""
    try:
        return (Keyboard.Modifiers & ModifierKeys.Shift) == ModifierKeys.Shift
    except Exception:
        return False


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


def print_debug(z_target):
    if not DEBUG:
        return
    print("AVOID_MODEL_OBSTACLES = {}, AVOID_EXISTING_CONDUIT = {}, AVOID_PLANNED_RUNS = {}".format(
        AVOID_MODEL_OBSTACLES, AVOID_EXISTING_CONDUIT, AVOID_PLANNED_RUNS))
    print("z_target (conduit centerline elevation) = {:.2f} ft".format(z_target))
    print("Obstacle boxes collected: {}".format(len(OBSTACLE_INFO)))
    shown = 0
    for (i, cat, nm, mn, mx) in OBSTACLE_INFO:
        if mn[2] - CLEARANCE < z_target < mx[2] + CLEARANCE:
            print("Obstacle at elevation: {} | {} | id {} | x[{:.2f}..{:.2f}] y[{:.2f}..{:.2f}] z[{:.2f}..{:.2f}]".format(
                cat, nm, i, mn[0], mx[0], mn[1], mx[1], mn[2], mx[2]))
            shown += 1
            if shown >= 80:
                print("... (more not shown)")
                break
    if shown == 0:
        print("No collected obstacle spans the conduit elevation.")
    for line in DEBUG_LOG:
        print(line)


def resolve_link_types(seq, rules):
    """Conduit type for each link = the type set for the family of the device the run leaves.
    Returns the per-link list (a ConduitType, or None where no type applies) and the labels not found."""
    link_types = []
    missing = []
    found = {}   # label -> ConduitType or None, so each label is looked up once
    for i in range(len(seq) - 1):
        label = mounting_rules.get_conduit_type_name_for_element(seq[i], rules)
        t = None
        if label:
            if label not in found:
                found[label] = mounting_rules.find_conduit_type(doc, label)
                if found[label] is None:
                    missing.append(label)
            t = found[label]
        link_types.append(t)
    return link_types, missing


def choose_default_type():
    """Default conduit type for runs with no family-specific type. Prompts only if the project has several."""
    types = list(FilteredElementCollector(doc).OfClass(ConduitType))
    if not types:
        forms.alert("No conduit types in project.")
        return None
    if len(types) == 1:
        return types[0]
    names = dict((mounting_rules.conduit_type_label(t), t) for t in types)
    pick = forms.SelectFromList.show(sorted(names.keys()), title="Default Conduit Type", multiselect=False)
    return names[pick] if pick else None


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

    # ---- conduit type per run (set per family in Routing Preferences) ----
    link_types, missing = resolve_link_types(seq, rules)
    if missing:
        forms.alert("These conduit types from Routing Preferences were not found in this project:\n\n{}\n\n"
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
