# -*- coding: utf-8 -*-
# Auto-Circuit script - version v1
__title__ = "Auto-\nCircuit v1"
__doc__ = ("Runs conduit between devices and addresses them as one circuit.\n\n"
           "1. Choose the circuit type (only NAC for now; Voice and SLC are not available yet).\n"
           "2. Continue a NAC circuit already in the project, continue from a selected device, or start a new "
           "one (same choices and N#-#.# addresses as Address NAC / Voice).\n"
           "3. Set the circuit limits: max current (default 1.2 A) and max device count; you are warned while "
           "picking if a device would go over.\n"
           "4. Pick devices or their tags in order (Esc when finished). A continued circuit starts from its last "
           "device. Non-NAC elements, such as the power supply, are connected but not addressed.\n"
           "5. Conduit is planned and created as in Auto Conduit, using Auto Conduit - Config (mounting and "
           "conduit type per family). After a confirmation, the connected devices get NAC Address / NAC Circuit "
           "in order, the new conduit gets Notification Circuit (e.g. N12), and NAC EOL is set on the last "
           "device of the circuit. Device types come from Address NAC / Voice - Config.\n\n"
           "Everything is one Undo.")

# Conduit routing and creation below are copied from Auto Conduit v4 (that tool is unchanged).
# Addressing follows Address NAC / Voice v5 and uses its shared module, nac_voice_types.

import heapq
import itertools
import math
from pyrevit import revit, forms, script
from Autodesk.Revit.DB import (
    XYZ, Domain, FilteredElementCollector, BuiltInCategory, ElementId,
    ElementMulticategoryFilter, BoundingBoxIntersectsFilter, Outline,
    BuiltInParameter, Transaction, TransactionGroup, TransactionStatus, FamilyInstance, IndependentTag,
    OverrideGraphicSettings, Color, FillPatternElement, ElementTransformUtils
)
from Autodesk.Revit.DB.Electrical import Conduit, ConduitType
from Autodesk.Revit.UI.Selection import ObjectType, ISelectionFilter
from Autodesk.Revit.Exceptions import OperationCanceledException
from System.Collections.Generic import List
from System.Windows import Visibility
from System.Windows.Input import Keyboard, ModifierKeys

import mounting_rules            # Auto Conduit - Config (read only here)
import nac_voice_types as nv     # Address NAC / Voice - Config and address format (read only here)

doc = revit.doc
uidoc = revit.uidoc
output = script.get_output()

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
        t = Transaction(doc, "Auto-Circuit: adjust device")
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
    t = Transaction(doc, "Auto-Circuit link")
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
    t = Transaction(doc, "Auto-Circuit highlight")
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


def shift_down():
    """True while a Shift key is held."""
    try:
        return (Keyboard.Modifiers & ModifierKeys.Shift) == ModifierKeys.Shift
    except Exception:
        return False



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


# ======================================================================================
# Auto-Circuit: circuit type, addressing (same rules as Address NAC / Voice) and the run
# ======================================================================================

TITLE = "Auto-Circuit"
BUTTON_LIMIT = 10     # more choices than this -> searchable list instead of buttons
PREVIEW_LIMIT = 25    # devices listed in the confirmation before anything is created
AMP_TOLERANCE = 1e-6
# Circuit types offered first. Only the ones in IMPLEMENTED can be run; the rest say "not available yet".
CIRCUIT_TYPES = ["NAC", "Voice", "SLC"]
IMPLEMENTED = {"NAC": "N"}     # circuit type -> kind code in nac_voice_types
OPT_ADD_ANYWAY = "Add it anyway"
OPT_FINISH_HERE = "Finished - create conduit without it"


# ---------------- devices and existing addresses ----------------

def all_devices():
    found = []
    for cat in nv.DEVICE_CATEGORIES:
        found.extend(FilteredElementCollector(doc).OfCategory(cat)
                     .WhereElementIsNotElementType().ToElements())
    return found


def address_on(el, kind):
    """(source, circuit, number) written on a device for that kind, or None."""
    p = nv.get_param(el, nv.PARAM_NAMES[kind]["address"])
    if p is None:
        return None
    try:
        return nv.parse_address(kind, p.AsString())
    except Exception:
        return None


def scan_existing(kind):
    """{(power supply, circuit): highest device number} from the addresses already written."""
    found = {}
    for el in all_devices():
        parsed = address_on(el, kind)
        if not parsed:
            continue
        key = (parsed[0], parsed[1])
        if parsed[2] > found.get(key, 0):
            found[key] = parsed[2]
    return found


def devices_with_address(kind, source, circuit, number):
    return [el for el in all_devices() if address_on(el, kind) == (source, circuit, number)]


def preselected_device():
    """The one device selected (directly or by its tag) when the tool was started, or None."""
    devices = {}
    try:
        for i in uidoc.Selection.GetElementIds():
            el = resolve_element(doc.GetElement(i))
            if el is not None and nv.is_device(el):
                devices[eid(el)] = el
    except Exception:
        return None
    return list(devices.values())[0] if len(devices) == 1 else None


def choose(options, message):
    """One of options, or None. Buttons for a short list, a searchable list for a long one."""
    if len(options) > BUTTON_LIMIT:
        return forms.SelectFromList.show(options, title=message, button_name="Select", multiselect=False)
    return forms.CommandSwitchWindow.show(options, message=message)


# ---------------- step 1: circuit type ----------------

def choose_circuit_type():
    """Kind code of the chosen circuit type ("N" for NAC), or None if cancelled."""
    labels = dict((t if t in IMPLEMENTED else "%s (not available yet)" % t, t) for t in CIRCUIT_TYPES)
    ordered = [l for t in CIRCUIT_TYPES for l in labels if labels[l] == t]
    while True:
        choice = forms.CommandSwitchWindow.show(ordered, message="Auto-Circuit: which circuit type?")
        if not choice:
            return None
        ctype = labels[choice]
        if ctype in IMPLEMENTED:
            return IMPLEMENTED[ctype]
        forms.alert("%s circuits are not available in Auto-Circuit yet. Only NAC can be used for now."
                    % ctype, title=TITLE)


# ---------------- step 2: which circuit (same choices as Address NAC / Voice) ----------------

NEW_CIRCUIT_XAML = """
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="New circuit"
        SizeToContent="WidthAndHeight"
        WindowStartupLocation="CenterScreen"
        ResizeMode="NoResize"
        Topmost="True">
    <StackPanel Margin="16">
        <TextBlock x:Name="msg_text" TextWrapping="Wrap" MaxWidth="340" Margin="0,0,0,12"/>
        <StackPanel Orientation="Horizontal" Margin="0,0,0,8">
            <TextBlock x:Name="source_label" Width="240" VerticalAlignment="Center"/>
            <TextBox x:Name="source_box" Width="90"/>
        </StackPanel>
        <StackPanel Orientation="Horizontal" Margin="0,0,0,8">
            <TextBlock Text="Circuit number:" Width="240" VerticalAlignment="Center"/>
            <ComboBox x:Name="circuit_box" Width="90"/>
        </StackPanel>
        <StackPanel Orientation="Horizontal" Margin="0,0,0,8">
            <TextBlock Text="Starting device number:" Width="240" VerticalAlignment="Center"/>
            <TextBox x:Name="start_box" Width="90"/>
        </StackPanel>
        <TextBlock x:Name="error_text" Foreground="Firebrick" TextWrapping="Wrap" MaxWidth="340"
                   Margin="0,0,0,10"/>
        <StackPanel Orientation="Horizontal" HorizontalAlignment="Right">
            <Button Content="OK" Width="80" Margin="0,0,8,0" IsDefault="True" Click="ok_click"/>
            <Button Content="Back" Width="80" IsCancel="True" Click="cancel_click"/>
        </StackPanel>
    </StackPanel>
</Window>
"""


class NewCircuitDialog(forms.WPFWindow):
    """Power supply, circuit and starting device number. self.result = (source, circuit, start) or None."""
    def __init__(self, kind, existing):
        forms.WPFWindow.__init__(self, NEW_CIRCUIT_XAML, literal_string=True)
        self.kind = kind
        self.existing = existing
        self.result = None
        name = nv.KIND_NAMES[kind]
        self.Title = "%s - new %s circuit" % (TITLE, name)
        self.msg_text.Text = ("%s Address = %s#-#.#  (%s - circuit . device order)"
                              % (name, kind, nv.SOURCE_NAMES[kind]))
        label = "%s number:" % nv.SOURCE_NAMES[kind]
        self.source_label.Text = label[0].upper() + label[1:]
        self.source_box.Text = "1"
        for n in nv.CIRCUIT_RANGES[kind]:
            self.circuit_box.Items.Add(str(n))
        self.circuit_box.SelectedIndex = 0
        self.start_box.Text = "1"
        self.source_box.Focus()
        self.source_box.SelectAll()

    def _read(self, box, what, min_val):
        text = (box.Text or "").strip()
        if not text.isdigit() or int(text) < min_val:
            self.error_text.Text = "%s must be a whole number, %d or higher." % (what, min_val)
            box.Focus()
            box.SelectAll()
            return None
        return int(text)

    def ok_click(self, sender, args):
        source = self._read(self.source_box, "The %s number" % nv.SOURCE_NAMES[self.kind], 0)
        if source is None:
            return
        if self.circuit_box.SelectedItem is None:
            self.error_text.Text = "Choose a circuit number."
            return
        circuit = int(str(self.circuit_box.SelectedItem))
        start = self._read(self.start_box, "The starting device number", 1)
        if start is None:
            return
        last = self.existing.get((source, circuit))
        if last and start <= last:
            go_on = forms.alert("%s already has addresses up to %s in this project. Starting at %s can create "
                                "duplicate addresses.\n\nUse it anyway?"
                                % (nv.fmt_circuit(self.kind, source, circuit),
                                   nv.fmt_address(self.kind, source, circuit, last),
                                   nv.fmt_address(self.kind, source, circuit, start)),
                                title=self.Title, yes=True, no=True)
            if not go_on:
                self.error_text.Text = "Change the numbers, or press Back to choose something else."
                return
        self.result = (source, circuit, start)
        self.Close()

    def cancel_click(self, sender, args):
        self.result = None
        self.Close()


def choose_circuit(kind, existing, preselected):
    """Continue a circuit already in the project, continue from a selected device, or start a new one.
    Returns {"source", "circuit", "next", "resumed", "from", "anchor"} or None if cancelled.
    anchor = the device the conduit starts from when continuing (the last device on the circuit), or None."""
    name = nv.KIND_NAMES[kind]
    labels, ordered = {}, []
    pre = address_on(preselected, kind) if preselected is not None else None
    if pre:
        selected_label = "Continue from selected (%s)" % nv.fmt_address(kind, pre[0], pre[1], pre[2])
    else:
        selected_label = "Continue from selected - pick a device..."
    ordered.append(selected_label)
    for key in sorted(existing):
        label = "Continue %s (last %s)" % (nv.fmt_circuit(kind, key[0], key[1]),
                                           nv.fmt_address(kind, key[0], key[1], existing[key]))
        labels[label] = key
        ordered.append(label)
    new_label = "New %s circuit" % name
    ordered.append(new_label)

    while True:
        choice = choose(ordered, "%s: which circuit do you want to run and address?" % name)
        if not choice:
            return None

        if choice == selected_label:
            parsed, el = pre, preselected
            if not parsed:
                try:
                    ref = uidoc.Selection.PickObject(
                        ObjectType.Element, DeviceOrTagFilter(),
                        "Select the device (or its tag) to continue %s from - Esc to go back" % name)
                except OperationCanceledException:
                    continue
                el = resolve_element(doc.GetElement(ref.ElementId))
                parsed = address_on(el, kind) if el is not None else None
                if not parsed:
                    forms.alert("That device has no %s in the %s#-#.# format to continue from."
                                % (nv.PARAM_NAMES[kind]["address"], kind), title=TITLE)
                    continue
            source, circuit, num = parsed
            return {"source": source, "circuit": circuit, "next": num + 1, "resumed": True,
                    "from": nv.fmt_address(kind, source, circuit, num), "anchor": el}

        if choice == new_label:
            dlg = NewCircuitDialog(kind, existing)
            dlg.ShowDialog()
            if dlg.result is None:
                continue
            source, circuit, start = dlg.result
            return {"source": source, "circuit": circuit, "next": start, "resumed": False,
                    "from": None, "anchor": None}

        source, circuit = labels[choice]
        last = existing[(source, circuit)]
        holders = devices_with_address(kind, source, circuit, last)
        return {"source": source, "circuit": circuit, "next": last + 1, "resumed": True,
                "from": nv.fmt_address(kind, source, circuit, last),
                "anchor": holders[0] if len(holders) == 1 else None}


# ---------------- step 3: circuit limits ----------------

LIMITS_XAML = """
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Circuit limits"
        SizeToContent="WidthAndHeight"
        WindowStartupLocation="CenterScreen"
        ResizeMode="NoResize"
        Topmost="True">
    <StackPanel Margin="16">
        <TextBlock x:Name="msg_text" TextWrapping="Wrap" MaxWidth="440" Margin="0,0,0,14"/>
        <StackPanel Orientation="Horizontal" Margin="0,0,0,2">
            <TextBlock Text="Max current (amps):" Width="260" VerticalAlignment="Center"/>
            <TextBox x:Name="current_box" Width="70"/>
        </StackPanel>
        <CheckBox x:Name="existing_check" Margin="0,4,0,12"/>
        <StackPanel Orientation="Horizontal" Margin="0,0,0,2">
            <TextBlock Text="Max device count for the circuit:" Width="260" VerticalAlignment="Center"/>
            <TextBox x:Name="count_box" Width="70"/>
        </StackPanel>
        <TextBlock x:Name="count_note" Foreground="Gray" TextWrapping="Wrap" MaxWidth="420" Margin="0,0,0,12"/>
        <TextBlock x:Name="error_text" Foreground="Firebrick" TextWrapping="Wrap" MaxWidth="440"
                   Margin="0,0,0,10"/>
        <StackPanel Orientation="Horizontal" HorizontalAlignment="Right">
            <Button Content="OK" Width="80" Margin="0,0,8,0" IsDefault="True" Click="ok_click"/>
            <Button Content="Cancel" Width="80" IsCancel="True" Click="cancel_click"/>
        </StackPanel>
    </StackPanel>
</Window>
"""


class LimitsDialog(forms.WPFWindow):
    """Max current and max device count, checked while devices are picked (blank = no limit).
    self.result = {"amps": float or None, "count": int or None, "include": bool}, or None if cancelled."""
    def __init__(self, circuit_text, next_number, existing_amps, existing_count):
        forms.WPFWindow.__init__(self, LIMITS_XAML, literal_string=True)
        self.Title = "%s - %s limits" % (TITLE, circuit_text)
        self.result = None
        self.next_number = next_number
        self.msg_text.Text = ("You are warned while picking if the next device would go over a limit. "
                              "Leave a box blank for no limit.")
        self.current_box.Text = "%g" % nv.DEFAULT_MAX_CURRENT
        self.existing_check.Content = ("Count the %d device(s) already on %s (%s)"
                                       % (existing_count, circuit_text, nv.fmt_amps(existing_amps)))
        self.existing_check.IsChecked = True
        if existing_count == 0:
            self.existing_check.Visibility = Visibility.Collapsed
        self.count_box.Text = ""
        if next_number > 1:
            self.count_note.Text = ("The first new device is .%d, so the count includes the %d device(s) "
                                    "already numbered before it." % (next_number, next_number - 1))
        else:
            self.count_note.Visibility = Visibility.Collapsed
        self.current_box.Focus()
        self.current_box.SelectAll()

    def _fail(self, box, text):
        self.error_text.Text = text
        box.Focus()
        box.SelectAll()

    def ok_click(self, sender, args):
        amps = None
        text = (self.current_box.Text or "").strip().rstrip("aA").strip()
        if text:
            try:
                amps = float(text)
            except ValueError:
                amps = 0.0
            if amps <= 0:
                return self._fail(self.current_box, "The max current must be a number of amps above 0 "
                                                    "(e.g. 1.2), or blank for no limit.")
        count = None
        text = (self.count_box.Text or "").strip()
        if text:
            if not text.isdigit() or int(text) < 1:
                return self._fail(self.count_box, "The max device count must be a whole number, 1 or higher, "
                                                  "or blank for no limit.")
            count = int(text)
            if count < self.next_number:
                return self._fail(self.count_box, "The circuit already has %d device(s) numbered, so the max "
                                                  "count has to be at least %d to add any more."
                                  % (self.next_number - 1, self.next_number))
        self.result = {"amps": amps, "count": count, "include": bool(self.existing_check.IsChecked)}
        self.Close()

    def cancel_click(self, sender, args):
        self.result = None
        self.Close()


# ---------------- the circuit being run ----------------

class CircuitRun(object):
    def __init__(self, kind):
        self.kind = kind
        self.name = nv.KIND_NAMES[kind]
        self.state = None           # {"source", "circuit", "next", "resumed", "from", "anchor"}
        self.limits = {"amps": None, "count": None, "include": True}
        self.table = {}
        self.session_types = {}     # types not in the lookup table: key -> label chosen this run
        self.info = {}              # element id -> what the device takes (see classify)
        self.members = {}           # element id -> amps of the devices already on the circuit
        self.problems = []
        self.eol_lines = []

    def address(self, number):
        s = self.state
        return nv.fmt_address(self.kind, s["source"], s["circuit"], number)

    def circuit_text(self):
        return nv.fmt_circuit(self.kind, self.state["source"], self.state["circuit"])

    def conduit_text(self):
        return nv.fmt_conduit(self.kind, self.state["source"], self.state["circuit"])

    def anchor_id(self):
        a = self.state.get("anchor") if self.state else None
        return eid(a) if a is not None else None

    # ---- set up ----
    def setup(self):
        try:
            self.table = nv.load_table()
        except Exception as ex:
            forms.alert("Could not read the NAC / Voice lookup table:\n%s\n\nPath: %s\n\nTypes will be asked "
                        "about as they are picked." % (ex, nv.table_path()), title=TITLE)
            self.table = {}
        picked = choose_circuit(self.kind, scan_existing(self.kind), preselected_device())
        if picked is None:
            return False
        picked["start"] = picked["next"]
        self.state = picked
        for el in all_devices():
            parsed = address_on(el, self.kind)
            if parsed and parsed[0] == picked["source"] and parsed[1] == picked["circuit"]:
                self.members[eid(el)] = nv.get_current(doc, el) or 0.0
        dlg = LimitsDialog(self.circuit_text(), picked["next"], sum(self.members.values()), len(self.members))
        dlg.ShowDialog()
        if dlg.result is None:
            return False
        self.limits = dlg.result
        return True

    # ---- what a device takes (lookup table, as in Address NAC / Voice) ----
    def device_label(self, el, key):
        label = self.table.get(key) or self.session_types.get(key)
        if label:
            return label
        available = nv.kinds_on_element(el)
        options = [t for t in nv.TYPE_LABELS if all(k in available for k in nv.TYPE_KINDS[t])]
        if not options:
            return None
        if len(options) == 1:
            label = options[0]
        else:
            label = forms.CommandSwitchWindow.show(
                options, message="%s is not in the NAC / Voice lookup table. What is it? (Asked once per run; "
                                 "define it in Address NAC / Voice - Config to keep it.)" % key)
            if not label:
                return None
        self.session_types[key] = label
        return label

    def classify(self, el):
        """{"key", "addr": True/False, "why", "targets", "amps", "had"} for a device, worked out once per run."""
        k = eid(el)
        if k in self.info:
            return self.info[k]
        key = nv.family_key(doc, el) if isinstance(el, FamilyInstance) else element_label(el)
        out = {"key": key, "addr": False, "why": None, "targets": None, "amps": None, "had": None}
        if k == self.anchor_id():
            out["why"] = "the device the circuit continues from"
        elif not nv.is_device(el):
            out["why"] = "not a Fire Alarm Device - conduit only"
        else:
            label = self.device_label(el, key)
            if label is None:
                out["why"] = "no %s parameters, or skipped" % self.name
            elif self.kind not in nv.TYPE_KINDS[label]:
                out["why"] = label
            else:
                names = nv.PARAM_NAMES[self.kind]
                addr_p = nv.get_param(el, names["address"])
                if addr_p is None or addr_p.IsReadOnly:
                    out["why"] = "no writable %s" % names["address"]
                else:
                    circ_p = nv.get_param(el, names["circuit"])
                    if circ_p is not None and circ_p.IsReadOnly:
                        circ_p = None
                    out.update({"addr": True, "targets": (addr_p, circ_p), "amps": nv.get_current(doc, el),
                                "had": address_on(el, self.kind)})
        self.info[k] = out
        return out

    # ---- limits while picking ----
    def totals(self, ids):
        """(device count incl. those already numbered, amps) if the addressable devices in ids were added."""
        new_ids = []
        for i in ids:
            if i not in new_ids and self.info.get(i, {}).get("addr"):
                new_ids.append(i)
        count = self.state["next"] - 1 + len(new_ids)
        amps = sum(self.info[i]["amps"] or 0.0 for i in new_ids)
        if self.limits["include"]:
            amps += sum(a for i, a in self.members.items() if i not in new_ids)
        return count, amps

    def status_text(self, ids):
        count, amps = self.totals(ids)
        parts = ["next %s" % self.address(count + 1), "%d device(s)" % count]
        if self.limits["count"]:
            parts[-1] += " of %d" % self.limits["count"]
        parts.append(nv.fmt_amps(amps) + (" of %s" % nv.fmt_amps(self.limits["amps"]) if self.limits["amps"] else ""))
        return ", ".join(parts)

    def over_limit(self, ids, new_id):
        """Why adding new_id would go over a limit, or None."""
        count, amps = self.totals(ids + [new_id])
        info = self.info[new_id]
        if self.limits["count"] and count > self.limits["count"]:
            return ("It would be device .%d on %s, over the max device count of %d."
                    % (count, self.circuit_text(), self.limits["count"]))
        if self.limits["amps"] and amps > self.limits["amps"] + AMP_TOLERANCE:
            return ("Its current (%s) would bring %s to %s, over the max %s."
                    % (nv.fmt_amps(info["amps"] or 0.0), self.circuit_text(), nv.fmt_amps(amps),
                       nv.fmt_amps(self.limits["amps"])))
        return None

    # ---- writing ----
    def items_for(self, connected):
        """[(element, info)] to address, in order of the chain, each device once."""
        out, seen = [], set()
        for el in connected:
            k = eid(el)
            if k in seen:
                continue
            seen.add(k)
            info = self.classify(el)
            if info["addr"]:
                out.append((el, info))
        return out

    def write(self, items, conduits):
        """Addresses + circuit on the devices and Notification Circuit on the conduits, in one transaction.
        Returns (touched circuits, conduits given the circuit, conduits without the parameter, error or None)."""
        kind, s = self.kind, self.state
        touched = set([(kind, s["source"], s["circuit"])])
        for _el, info in items:
            if info["had"]:
                touched.add((kind, info["had"][0], info["had"][1]))   # the circuit it leaves needs its EOL redone
        pname = nv.CONDUIT_PARAM_NAMES.get(kind)
        conduit_sets, no_param = [], 0
        if pname:
            for c in conduits:
                p = nv.get_param(c, pname)
                if p is None or p.IsReadOnly:
                    no_param += 1
                else:
                    conduit_sets.append(p)
        error = None
        t = Transaction(doc, "Auto-Circuit: address devices")
        try:
            t.Start()
            for p in conduit_sets:
                p.Set(nv.merge_conduit_value(p.AsString(), kind, self.conduit_text()))
            for n, (_el, info) in enumerate(items):
                addr_p, circ_p = info["targets"]
                addr_p.Set(self.address(s["next"] + n))
                if circ_p is not None:
                    circ_p.Set(self.circuit_text())
            if t.Commit() != TransactionStatus.Committed:
                error = "the change was rolled back"
        except Exception as ex:
            try:
                if t.GetStatus() == TransactionStatus.Started:
                    t.RollBack()
            except Exception:
                pass
            error = str(ex)
        if error:
            return set(), 0, no_param, error
        s["next"] += len(items)
        for _el, info in items:
            if info["targets"][1] is None:
                self.problems.append("%s: no writable %s, so only the address was filled."
                                     % (info["key"], nv.PARAM_NAMES[kind]["circuit"]))
        return touched, len(conduit_sets), no_param, None

    def set_eol(self, touched):
        """Last device of each circuit touched: EOL = Yes; every other device on it: No (as Address NAC / Voice)."""
        if not touched:
            return
        circuits = {}
        for el in all_devices():
            parsed = address_on(el, self.kind)
            if parsed and (self.kind, parsed[0], parsed[1]) in touched:
                circuits.setdefault((self.kind, parsed[0], parsed[1]), []).append((parsed[2], el))
        changes = []
        for key in sorted(touched):
            kind, source, circuit = key
            members = circuits.get(key, [])
            if not members:
                continue
            last = max(n for n, _el in members)
            name = nv.EOL_PARAM_NAMES[kind]
            ends, missing = [], 0
            for n, el in members:
                p = nv.get_yes_no(el, name)
                if p is None:
                    missing += 1
                    if n == last:
                        self.problems.append("%s: the last device (element %d) has no writable %s parameter."
                                             % (nv.fmt_address(kind, source, circuit, n), eid(el), name))
                    continue
                value = 1 if n == last else 0
                if n == last:
                    ends.append(eid(el))
                if p.AsInteger() != value:
                    changes.append((p, value))
            circuit_text = nv.fmt_circuit(kind, source, circuit)
            if len(ends) > 1:
                self.problems.append("%s: %d devices share the last address %s; all are set to %s = Yes."
                                     % (circuit_text, len(ends), nv.fmt_address(kind, source, circuit, last), name))
            if ends:
                self.eol_lines.append("%s: %s = Yes on %s (element %s)"
                                      % (circuit_text, name, nv.fmt_address(kind, source, circuit, last),
                                         ", ".join(str(i) for i in ends)))
            if missing:
                self.problems.append("%s: %d device(s) have no writable %s parameter." % (circuit_text, missing, name))
        if not changes:
            return
        t = Transaction(doc, "Auto-Circuit: set EOL")
        try:
            t.Start()
            for p, value in changes:
                p.Set(value)
            if t.Commit() != TransactionStatus.Committed:
                self.problems.append("EOL parameters were not set: the change was rolled back.")
                self.eol_lines = []
        except Exception as ex:
            try:
                if t.GetStatus() == TransactionStatus.Started:
                    t.RollBack()
            except Exception:
                pass
            self.problems.append("EOL parameters were not set: %s" % ex)
            self.eol_lines = []


# ---------------- picking (Auto Conduit's pick loop, with the circuit's running totals) ----------------

def pick_chain(run):
    """Pick devices (or tags) in order. A continued circuit starts from its last device, already in the chain.
    Returns the list of elements, or None if cancelled. Highlights are rolled back afterwards."""
    ogs = make_highlight() if HIGHLIGHT_PICKED else None
    tg = None
    if ogs is not None:
        try:
            tg = TransactionGroup(doc, "Auto-Circuit selection")
            tg.Start()
        except Exception:
            tg, ogs = None, None
    try:
        return _pick_loop(ogs, run)
    finally:
        if tg is not None:
            try:
                tg.RollBack()
            except Exception:
                pass


def _pick_loop(ogs, run):
    picks = []   # {"el": element, "ids": [ElementIds highlighted for it]}
    flt = DeviceOrTagFilter()
    state = {"ogs": ogs}

    def keys():
        return [eid(p["el"]) for p in picks]

    def add(el, ids):
        picks.append({"el": el, "ids": ids})
        if state["ogs"] is not None and not highlight(state["ogs"], ids):
            state["ogs"] = None

    def remove(index):
        gone = picks.pop(index)
        if state["ogs"] is None:
            return
        still = set(eid(i) for p in picks for i in p["ids"])
        clear = [i for i in gone["ids"] if eid(i) not in still]
        if clear:
            highlight(OverrideGraphicSettings(), clear)

    def finish():
        if len(picks) >= 2:
            return [p["el"] for p in picks]
        forms.alert("Select at least two elements.", title=TITLE)
        return None

    anchor = run.state.get("anchor")
    if anchor is not None:
        run.classify(anchor)
        add(anchor, [anchor.Id])
    elif run.state["resumed"]:
        forms.alert("The last device on %s (%s) could not be found as a single device, so the conduit starts "
                    "from your first pick." % (run.circuit_text(), run.state["from"]), title=TITLE)

    while True:
        start_note = ""
        if anchor is not None and picks and eid(picks[0]["el"]) == eid(anchor):
            start_note = " from %s" % run.state["from"]
        try:
            r = uidoc.Selection.PickObject(
                ObjectType.Element, flt,
                "%s%s: pick device or tag #%d in order (%s). Shift+click a picked device to remove it; "
                "Esc when finished" % (run.circuit_text(), start_note, len(picks) + 1, run.status_text(keys())))
        except OperationCanceledException:
            if not picks:
                return None
            choice = forms.alert(
                "{} element(s) selected so far ({}).\n\nAre you finished selecting?".format(
                    len(picks), run.status_text(keys())),
                title=TITLE, options=[OPT_FINISH, OPT_CONTINUE, OPT_UNDO, OPT_CANCEL])
            if choice == OPT_FINISH:
                done = finish()
                if done:
                    return done
                continue
            if choice == OPT_UNDO:
                remove(len(picks) - 1)
                continue
            if choice == OPT_CANCEL:
                return None
            continue
        except Exception:
            return [p["el"] for p in picks] if len(picks) >= 2 else None
        shift = shift_down()
        picked = doc.GetElement(r.ElementId)
        el = resolve_element(picked)
        if el is None:
            forms.alert("That tag isn't hosted to a device in this model (it may tag a linked element). "
                        "Pick the device or a different tag.", title=TITLE)
            continue
        k = eid(el)
        if shift:
            if k in keys():
                remove(len(picks) - 1 - keys()[::-1].index(k))
            continue
        if picks and k == eid(picks[-1]["el"]):
            continue
        if k in keys():
            first = keys().index(k) + 1
            choice = forms.alert(
                "{} is already in this chain (pick #{}).\n\n"
                "Adding it again routes conduit back to it and creates a loop. It is addressed only once.".format(
                    element_label(el), first),
                title="Auto-Circuit - device already selected",
                options=[OPT_IGNORE, OPT_REMOVE, OPT_ADD_AGAIN])
            if choice == OPT_REMOVE:
                remove(len(picks) - 1 - keys()[::-1].index(k))
                continue
            if choice != OPT_ADD_AGAIN:
                continue
        else:
            info = run.classify(el)
            if info["addr"]:
                why = run.over_limit(keys(), k)
                if why:
                    choice = forms.alert("{}\n\n{}".format(element_label(el), why),
                                         title="Auto-Circuit - circuit limit",
                                         options=[OPT_FINISH_HERE, OPT_IGNORE, OPT_ADD_ANYWAY])
                    if choice == OPT_FINISH_HERE:
                        done = finish()
                        if done:
                            return done
                        continue
                    if choice != OPT_ADD_ANYWAY:
                        continue
            else:
                forms.toast("Not addressed ({}) - conduit only.".format(info["why"]), title=TITLE)
        ids = [el.Id]
        if eid(picked) != k:
            ids.append(picked.Id)
        add(el, ids)


# ---------------- report ----------------

def report(run, made_links, total_links, conduits_made, conduits_set, no_param, addressed, passed, notes):
    s = run.state
    output.print_md("### Auto-Circuit: {} circuit {}".format(run.name, run.circuit_text()))
    how = "new circuit"
    if s["resumed"]:
        how = "continued from %s" % s["from"]
    output.print_md("- {} ({})".format(run.circuit_text(), how))
    output.print_md("- Conduit: {} of {} link(s) created, {} conduit segment(s)".format(
        made_links, total_links, conduits_made))
    if conduits_set:
        output.print_md("- {} conduit segment(s) given {} = {}".format(
            conduits_set, nv.CONDUIT_PARAM_NAMES[run.kind], run.conduit_text()))
    if no_param:
        run.problems.append("{} conduit segment(s) have no writable {} parameter.".format(
            no_param, nv.CONDUIT_PARAM_NAMES[run.kind]))
    output.print_md("- Devices addressed: **{}**".format(len(addressed)))
    for el, info, text in addressed:
        extra = ""
        if info["amps"] is not None:
            extra = " ({})".format(nv.fmt_amps(info["amps"]))
        output.print_md("    - {} : {} - {}{}".format(eid(el), info["key"], text, extra))
    count, amps = run.totals([eid(el) for el, _i, _t in addressed])
    output.print_md("- Circuit total: {} device(s), {}{}".format(
        count, nv.fmt_amps(amps), "" if run.limits["include"] else " (devices added this run only)"))
    for line in run.eol_lines:
        output.print_md("- EOL {}".format(line))
    if passed:
        output.print_md("- Connected but not addressed:")
        for el, info in passed:
            output.print_md("    - {} : {} ({})".format(eid(el), info["key"], info["why"]))
    if run.session_types:
        output.print_md("- Types not in the NAC / Voice lookup table (used for this run only):")
        for k in sorted(run.session_types):
            output.print_md("    - {} -> {}".format(k, run.session_types[k]))
    output.print_md("- Routing preferences: `{}`".format(mounting_rules.rules_path()))
    output.print_md("- NAC / Voice lookup table: `{}`".format(nv.table_path()))
    for line in notes:
        output.print_md("- {}".format(line))
    for msg in run.problems:
        output.print_md("- Issue: {}".format(msg))


# ---------------- main ----------------

def main():
    # ---- 1. circuit type, 2. which circuit, 3. limits ----
    kind = choose_circuit_type()
    if kind is None:
        return
    run = CircuitRun(kind)
    if not run.setup():
        return

    # ---- 4. pick the chain ----
    elems = pick_chain(run)
    if not elems or len(elems) < 2:
        return

    # ---- routing preferences: mounting + conduit type (Auto Conduit - Config) ----
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
            "Skip this device (it is not connected or addressed), or use its closest available "
            "connector(s)?".format(element_label(e), tops, need[k]),
            title=TITLE, options=[OPT_CLOSEST, OPT_SKIP])
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
        forms.alert("Fewer than two elements remain after skipping devices.", title=TITLE)
        return

    link_types, missing = resolve_link_types(seq, rules)
    if missing:
        forms.alert("These conduit types from Auto Conduit - Config were not found in this project:\n\n{}\n\n"
                    "Runs using them will use the default conduit type instead.".format("\n".join(missing)),
                    title=TITLE)
    if any(t is None for t in link_types):
        default_type = choose_default_type()
        if default_type is None:
            return
        link_types = [t if t is not None else default_type for t in link_types]

    level = doc.ActiveView.GenLevel
    if level is None:
        for el in seq:
            if el.LevelId != ElementId.InvalidElementId:
                level = doc.GetElement(el.LevelId)
                break
    if level is None:
        forms.alert("Could not determine a level. Run this from a plan or section view that has an associated "
                    "level.", title=TITLE)
        return

    offset = None
    while offset is None:
        txt = forms.ask_for_string(default=DEFAULT_ELEVATION_TEXT,
                                   prompt="Conduit elevation above '{}':".format(level.Name),
                                   title="Auto-Circuit - Conduit Elevation")
        if txt is None:
            return
        offset = parse_length(txt)
        if offset is None:
            forms.alert("Could not read '{}' as a length. Try something like 15'-0\" or 180.".format(txt),
                        title=TITLE)
    z_target = level.Elevation + offset

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

    # ---- 5. plan the whole chain before creating anything ----
    total_links = len(seq) - 1
    culprit = None
    no_adjust = set()
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
            text += ("\n\n'{}' creates the {} link(s) before it and addresses only the devices they "
                     "connect.".format(OPT_SKIP_DEV, len(partial)))
        if moves:
            options.append(OPT_ADJUST)
            text += ("\n\n'{}' moves the second device {} so it lines up with the first, "
                     "then plans the chain again.".format(OPT_ADJUST, moves[0][1]))
        options.append(OPT_CANCEL_CHAIN)
        text += "\n\nEither way, the second device is left selected so you can find it."
        choice = forms.alert(text, title="Auto-Circuit - link could not be routed", options=options)
        if choice == OPT_ADJUST:
            moved = adjust_device(prev, culprit, moves, walls, fallback, z_target, static_boxes)
            if moved is None:
                no_adjust.add(eid(culprit))
                forms.alert("The device could not be moved into line (it may be hosted or pinned), "
                            "so nothing was changed.", title=TITLE)
            continue
        if choice == OPT_SKIP_DEV:
            plan = partial
            break
        print_debug(z_target)
        uidoc.Selection.SetElementIds(List[ElementId]([culprit.Id]))
        return
    print_debug(z_target)

    # ---- 6. confirm the addresses ----
    connected = seq[:len(plan) + 1]
    items = run.items_for(connected)
    passed = []
    seen = set()
    for el in connected:
        k = eid(el)
        if k in seen:
            continue
        seen.add(k)
        info = run.classify(el)
        if not info["addr"]:
            passed.append((el, info))
    first = run.state["next"]
    lines = []
    for i, (el, info) in enumerate(items[:PREVIEW_LIMIT]):
        line = "{}  {}".format(run.address(first + i), info["key"])
        if info["amps"] is not None:
            line += "  ({})".format(nv.fmt_amps(info["amps"]))
        lines.append(line)
    if len(items) > PREVIEW_LIMIT:
        lines.append("... and {} more".format(len(items) - PREVIEW_LIMIT))
    if not items:
        lines.append("(no devices on the chain take a {} address)".format(run.name))
    notes = ["Circuit total: {}.".format(run.status_text([eid(el) for el, _i in items]).split(", ", 1)[1])]
    readdress = len([1 for _el, info in items if info["had"]])
    if readdress:
        notes.append("{} of them already have a {}, which will be replaced.".format(
            readdress, nv.PARAM_NAMES[kind]["address"]))
    if passed:
        notes.append("{} element(s) on the chain are connected but not addressed (see the report).".format(
            len(passed)))
    go_on = forms.alert("Create {} conduit link(s) and address {} device(s) on {}?\n\n{}\n\n{}".format(
        len(plan), len(items), run.circuit_text(), "\n".join(lines), "\n".join(notes)),
        title=TITLE, yes=True, no=True)
    if not go_on:
        return

    # ---- 7. create the conduit, address, set EOL - one undo ----
    tg = TransactionGroup(doc, "Auto-Circuit")
    tg.Start()
    made_links = 0
    conduits = []
    failure = None
    addressed = []
    conduits_set, no_param = 0, 0
    try:
        for i, o in enumerate(plan):
            try:
                conduits.extend(create_link(o["a"], o["b"], o["pts"], link_types[i], level.Id))
            except Exception as ex:
                failure = "Link {} of {} failed while creating conduit: {}".format(i + 1, total_links, ex)
                break
            made_links += 1
        if made_links > 0:
            if made_links < len(plan):
                items = run.items_for(seq[:made_links + 1])   # only the devices that were connected
            if items:
                touched, conduits_set, no_param, error = run.write(items, conduits)
                if error:
                    run.problems.append("Nothing was addressed: {}".format(error))
                else:
                    addressed = [(el, info, run.address(first + i)) for i, (el, info) in enumerate(items)]
                    try:
                        run.set_eol(touched)
                    except Exception as ex:
                        run.problems.append("EOL parameters were not set: {}".format(ex))
    finally:
        if made_links > 0:
            tg.Assimilate()
        else:
            tg.RollBack()

    notes = []
    if failure:
        notes.append(failure)
    if culprit is not None:
        uidoc.Selection.SetElementIds(List[ElementId]([culprit.Id]))
        notes.append("{} could not be connected and is now selected; the devices after it were not connected "
                     "or addressed.".format(element_label(culprit)))
    if made_links == 0:
        forms.alert("{}\n\nNothing was created.".format(failure or "No conduit was created."), title=TITLE)
        return
    report(run, made_links, total_links, len(conduits), conduits_set, no_param, addressed,
           [p for p in passed if eid(p[0]) not in set(eid(a[0]) for a in addressed) and p[1]["why"]], notes)


main()
