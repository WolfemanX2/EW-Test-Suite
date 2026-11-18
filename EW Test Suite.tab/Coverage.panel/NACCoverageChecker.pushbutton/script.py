# -*- coding: utf-8 -*-
# NAC Coverage Checker script - version v1
__title__ = "NAC\nCoverage"
__doc__ = ("Checks visible (strobe) coverage with line of sight. Every Fire Alarm Device that has a candela value "
           "gets its NFPA 72 coverage square (wall or ceiling table), and a grid of points in each room is tested: "
           "a point is covered when it lies inside a strobe's square AND nothing in the model or the loaded links "
           "blocks the straight line from the strobe lens to that point.\n\n"
           "Run it from a floor plan and choose:\n"
           " - Entire view: every room / space on the plan's level\n"
           " - Pick a room: click inside one room or space\n"
           " - Clear results: removes the colored points from this view\n\n"
           "Green = covered, yellow = outside every strobe's square, red = inside a square but line of sight is blocked. "
           "The results are a display only (nothing is added to the model) and disappear when the model is closed. "
           "Wall / Ceiling comes from Auto Conduit - Config when the family has a rule there.")

import math
import re

from pyrevit import revit, forms, script
import Autodesk.Revit.DB as DB
import Autodesk.Revit.DB.Analysis as AN
from Autodesk.Revit.DB import (
    XYZ, ElementId, FilteredElementCollector, BuiltInCategory, BuiltInParameter, RevitLinkInstance,
    FamilyInstance, ElementMulticategoryFilter, ReferenceIntersector, FindReferenceTarget, View3D,
    ViewFamilyType, ViewFamily, ViewType, ViewDetailLevel, Transaction, Color, StorageType, Level, Wall
)
from Autodesk.Revit.Exceptions import OperationCanceledException
from System.Collections.Generic import List

try:
    import mounting_rules          # lib/mounting_rules.py (Auto Conduit - Config)
except Exception:
    mounting_rules = None

doc = revit.doc
uidoc = revit.uidoc
output = script.get_output()

TITLE = "NAC Coverage Checker"

# ---------------- Settings ----------------
# Lengths are in feet.
CANDELA_PARAMS = ["Candela", "Candela Rating", "Candela Setting", "CD"]  # first one found on the instance, then the type
GRID_STEP = 2.0             # spacing of the test points. 1.0 is finer but about 4x slower
VIEW_HEIGHT = 5.0           # height above the floor of the points the strobes must see
DISPLAY_HEIGHT = 0.5        # height above the floor the colored points are drawn at (must be inside the plan's view range)
LENS_Z_OFFSET = 0.0         # added to the device's location point to get the lens height
ORIGIN_OFFSET = 0.25        # sight lines start this far in front of the lens (out of the wall / below the ceiling)
IGNORE_NEAR = 0.2           # hits closer than this to the lens are ignored (the device's own box, ceiling tile edge)
END_TOL = 0.1               # a hit this close to the target point doesn't count as blocking
WALL_PROBE = 0.6            # a wall within this distance on one side of a wall device = that side is the wall
CEILING_PROBE = 0.75        # something within this distance above a device with no rule = ceiling mounted
MAX_LENS_AFF = 30.0         # NFPA 72 tables stop at a 30 ft ceiling-mounted lens
WALL_MIN_AFF = 80.0 / 12    # wall lens below this: room size reduced by twice the difference (NFPA 72 18.5.5.4)
LEVEL_TOL = 1.0             # a room in a link is on the plan's level when its level is within this height
MARKER_SIZE = 0.02          # size of the colored points; raise it if they look too small at your view scale
ROOM_SOURCES = ["spaces", "rooms", "links"]   # first source that has rooms/spaces on the level is used:
                            # MEP Spaces in this model, then Rooms in this model, then Rooms in loaded links
ANALYSIS_VIEW_NAME = "NAC Coverage Checker"   # 3D view used to test sight lines (created if missing)
STYLE_NAME = "NAC Coverage"                   # analysis display style (edit under Manage > Analysis Display Styles)
RESULT_NAME = "NAC Coverage"

# Categories that never block a sight line. Everything else visible in the 3D view above does
# (walls, ceilings, soffits, beams, ducts, columns, casework, furniture, doors, glass, ...).
IGNORE_CATS = [
    BuiltInCategory.OST_FireAlarmDevices,
    BuiltInCategory.OST_Rooms, BuiltInCategory.OST_MEPSpaces, BuiltInCategory.OST_Areas,
    BuiltInCategory.OST_Conduit, BuiltInCategory.OST_ConduitFitting,
    BuiltInCategory.OST_Sprinklers,
    BuiltInCategory.OST_Lines,
]

# NFPA 72 Table 18.5.5.5.1(a), wall-mounted, one light per room: (max square room side, minimum candela).
# VERIFY against the edition your AHJ has adopted and edit here if needed.
WALL_TABLE = [
    (20, 15), (28, 30), (30, 34), (40, 60), (45, 75), (50, 94),
    (54, 110), (55, 115), (63, 150), (68, 177), (70, 184),
]
# NFPA 72 Table 18.5.5.5.1(b), ceiling-mounted, one light per room:
# (max square room side, (candela for lens up to 10 ft, up to 20 ft, up to 30 ft)). None = not listed.
# VERIFY against the edition your AHJ has adopted and edit here if needed.
CEILING_TABLE = [
    (20, (15, 30, 55)),
    (30, (30, 45, 75)),
    (40, (60, 80, None)),
    (50, (95, 115, None)),
]
# ------------------------------------------

WALL = "Wall"
CEILING = "Ceiling"
COVERED, OUT_OF_RANGE, BLOCKED = 2.0, 1.0, 0.0


def _api(name):
    """Analysis display classes live in DB in some Revit versions and DB.Analysis in others."""
    cls = getattr(DB, name, None)
    return cls if cls is not None else getattr(AN, name)


def eid(x):
    i = x.Id if hasattr(x, "Id") else x
    try:
        return i.Value
    except Exception:
        return i.IntegerValue


def horiz(v):
    if v is None:
        return None
    w = XYZ(v.X, v.Y, 0)
    return w.Normalize() if w.GetLength() > 1e-6 else None


def cat_is(el, bic):
    try:
        return el.Category is not None and eid(el.Category.Id) == int(bic)
    except Exception:
        return False


# ---------------- Sight lines ----------------
class Sight(object):
    def __init__(self, view3d):
        flt = ElementMulticategoryFilter(List[BuiltInCategory](IGNORE_CATS), True)
        self.ri = ReferenceIntersector(flt, FindReferenceTarget.Face, view3d)
        self.ri.FindReferencesInRevitLinks = True
        self.rays = 0

    def nearest(self, origin, direction):
        """Distance to the first surface along the ray, or None."""
        self.rays += 1
        ctx = self.ri.FindNearest(origin, direction)
        return ctx.Proximity if ctx is not None else None

    def first_hit(self, origin, direction):
        """Like nearest(), but skips hits closer than IGNORE_NEAR."""
        d = self.nearest(origin, direction)
        if d is None or d > IGNORE_NEAR:
            return d
        best = None
        for c in self.ri.Find(origin, direction):
            p = c.Proximity
            if p > IGNORE_NEAR and (best is None or p < best):
                best = p
        return best

    def clear(self, origin, target):
        v = target - origin
        dist = v.GetLength()
        if dist < 1e-6:
            return True
        hit = self.first_hit(origin, v.Normalize())
        return hit is None or hit >= dist - END_TOL


def analysis_view():
    """3D view for the sight-line tests: no template, no section box, fine detail, same phase as the plan."""
    view = None
    for v in FilteredElementCollector(doc).OfClass(View3D):
        if not v.IsTemplate and v.Name == ANALYSIS_VIEW_NAME:
            view = v
            break
    t = Transaction(doc, "NAC Coverage Checker - prepare 3D view")
    t.Start()
    try:
        if view is None:
            vft = [x for x in FilteredElementCollector(doc).OfClass(ViewFamilyType)
                   if x.ViewFamily == ViewFamily.ThreeDimensional][0]
            view = View3D.CreateIsometric(doc, vft.Id)
            view.Name = ANALYSIS_VIEW_NAME
        try:
            if view.ViewTemplateId != ElementId.InvalidElementId:
                view.ViewTemplateId = ElementId.InvalidElementId
        except Exception:
            pass
        try:
            if view.IsSectionBoxActive:
                view.IsSectionBoxActive = False
        except Exception:
            pass
        try:
            view.DetailLevel = ViewDetailLevel.Fine
        except Exception:
            pass
        try:
            phase = doc.ActiveView.get_Parameter(BuiltInParameter.VIEW_PHASE).AsElementId()
            p = view.get_Parameter(BuiltInParameter.VIEW_PHASE)
            if p.AsElementId() != phase:
                p.Set(phase)
        except Exception:
            pass
        t.Commit()
    except Exception:
        t.RollBack()
        raise
    return view


# ---------------- Strobes ----------------
NUM_RE = re.compile(r"\d+(?:\.\d+)?")


def read_candela(el):
    """(candela, None) or (None, problem). problem is None when the device has no candela parameter at all."""
    sources = [el]
    try:
        sources.append(doc.GetElement(el.GetTypeId()))
    except Exception:
        pass
    problem = None
    for src in sources:
        if src is None:
            continue
        for name in CANDELA_PARAMS:
            p = src.LookupParameter(name)
            if p is None:
                continue
            v = None
            if p.StorageType == StorageType.Double:
                v = p.AsDouble()
            elif p.StorageType == StorageType.Integer:
                v = p.AsInteger()
            elif p.StorageType == StorageType.String:
                s = p.AsString() or p.AsValueString() or ""
                nums = NUM_RE.findall(s)
                if len(nums) == 1:
                    v = float(nums[0])
                elif len(nums) > 1:
                    problem = u"'{}' = '{}' lists more than one value".format(name, s)
                    continue
            if v is not None and v > 0:
                return float(v), None
            if problem is None:
                problem = u"'{}' is empty".format(name)
    return None, problem


def wall_size(cd, aff):
    size = 0
    for side, req in WALL_TABLE:
        if cd + 0.01 >= req:
            size = max(size, side)
    if aff < WALL_MIN_AFF:
        size -= 2.0 * (WALL_MIN_AFF - aff)
    return max(size, 0)


def ceiling_size(cd, aff):
    if aff <= 10.01:
        col = 0
    elif aff <= 20.01:
        col = 1
    elif aff <= MAX_LENS_AFF + 0.01:
        col = 2
    else:
        return 0
    size = 0
    for side, reqs in CEILING_TABLE:
        req = reqs[col]
        if req is not None and cd + 0.01 >= req:
            size = max(size, side)
    return size


class Strobe(object):
    def __init__(self, el, cd, mount, lens, normal, axis):
        self.el = el
        self.id = el.Id
        self.cd = cd
        self.mount = mount
        self.lens = lens
        self.n = normal          # wall: horizontal direction into the room
        self.u = axis            # along the wall / first side of the ceiling square
        self.v = XYZ(-axis.Y, axis.X, 0)
        if mount == WALL:
            self.origin = lens + normal.Multiply(ORIGIN_OFFSET)
        else:
            self.origin = lens - XYZ.BasisZ.Multiply(ORIGIN_OFFSET)
        try:
            self.label = u"{} : {}".format(el.Symbol.Family.Name, el.Name)
        except Exception:
            self.label = el.Name

    def size(self, floor_z):
        aff = self.lens.Z - floor_z
        if self.mount == WALL:
            return wall_size(self.cd, aff)
        return ceiling_size(self.cd, aff)

    def reach(self, size):
        return size * (1.12 if self.mount == WALL else 0.71)

    def covers(self, x, y, size):
        dx = x - self.lens.X
        dy = y - self.lens.Y
        if self.mount == WALL:
            b = dx * self.n.X + dy * self.n.Y
            if b < -0.05 or b > size:
                return False
            a = dx * self.u.X + dy * self.u.Y
            return abs(a) <= size / 2.0
        a = dx * self.u.X + dy * self.u.Y
        b = dx * self.v.X + dy * self.v.Y
        return abs(a) <= size / 2.0 and abs(b) <= size / 2.0


def mounting_of(fi, lens, sight, rules):
    """'Wall' / 'Ceiling' and how it was decided, or (None, reason)."""
    try:
        fam = fi.Symbol.Family.Name
    except Exception:
        fam = None
    if mounting_rules is not None and fam:
        try:
            m = mounting_rules.get_mounting(fam, rules)
        except Exception:
            m = None
        if m in (WALL, CEILING):
            return m, "Auto Conduit - Config"
    bz = fi.GetTransform().BasisZ
    host = fi.Host
    if host is not None and not isinstance(host, Level):
        if cat_is(host, BuiltInCategory.OST_Ceilings):
            return CEILING, "host"
        if isinstance(host, Wall):
            return WALL, "host"
        if abs(bz.Z) > 0.7:
            return CEILING, "host face"
        if abs(bz.Z) < 0.3:
            return WALL, "host face"
    up = sight.nearest(lens, XYZ.BasisZ)
    if up is not None and up < CEILING_PROBE:
        return CEILING, "ceiling above"
    f = horiz(fi.FacingOrientation)
    if f is not None:
        for d in (f, f.Negate()):
            h = sight.nearest(lens, d)
            if h is not None and h < WALL_PROBE:
                return WALL, "wall beside"
    return None, "no Auto Conduit - Config rule and no wall or ceiling found next to it"


def wall_normal(fi, lens, sight):
    """Horizontal direction from the wall into the room."""
    bz = fi.GetTransform().BasisZ
    cand = horiz(bz) if abs(bz.Z) < 0.3 else None      # face-based on a wall: face normal points into the room
    if cand is None:
        cand = horiz(fi.FacingOrientation) or XYZ.BasisY
    fwd = sight.nearest(lens, cand)
    back = sight.nearest(lens, cand.Negate())
    fwd_near = fwd is not None and fwd < WALL_PROBE
    back_near = back is not None and back < WALL_PROBE
    if fwd_near and not back_near:
        cand = cand.Negate()
    return cand


def collect_strobes(sight, z_low, z_high, issues):
    rules = None
    if mounting_rules is not None:
        try:
            rules = mounting_rules.load_rules()
        except Exception:
            rules = None
    strobes = []
    no_param = 0
    devices = (FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_FireAlarmDevices)
               .WhereElementIsNotElementType())
    for el in devices:
        if not isinstance(el, FamilyInstance):
            continue
        loc = getattr(el.Location, "Point", None)
        if loc is None:
            continue
        lens = XYZ(loc.X, loc.Y, loc.Z + LENS_Z_OFFSET)
        if lens.Z < z_low - 1.0 or lens.Z > z_high:
            continue
        cd, problem = read_candela(el)
        if cd is None:
            if problem is None:
                no_param += 1
            else:
                issues.append((el.Id, "Candela not read: " + problem))
            continue
        mount, how = mounting_of(el, lens, sight, rules)
        if mount is None:
            issues.append((el.Id, "Skipped: Wall or Ceiling unknown ({}). Add a rule in Auto Conduit - Config.".format(how)))
            continue
        if mount == WALL:
            n = wall_normal(el, lens, sight)
            axis = XYZ(-n.Y, n.X, 0)
        else:
            n = XYZ.BasisZ.Negate()
            axis = horiz(el.HandOrientation) or XYZ.BasisX
        strobes.append(Strobe(el, cd, mount, lens, n, axis))
    return strobes, no_param


# ---------------- Rooms and spaces ----------------
def loaded_links():
    links = []
    for li in FilteredElementCollector(doc).OfClass(RevitLinkInstance):
        try:
            ldoc = li.GetLinkDocument()
        except Exception:
            ldoc = None
        if ldoc is not None:
            links.append((li, ldoc, li.GetTotalTransform()))
    return links


class Zone(object):
    """A room or space, in host coordinates."""
    def __init__(self, el, is_space, source, tf):
        self.el = el
        self.is_space = is_space
        self.source = source
        self.tf = tf
        self.inv = tf.Inverse if tf is not None else None
        lvl_z = el.Level.ProjectElevation
        self.floor_z = tf.OfPoint(XYZ(0, 0, lvl_z)).Z if tf is not None else lvl_z
        try:
            base = el.BaseOffset
        except Exception:
            base = 0.0
        self.test_dz = base + 1.0
        bb = el.get_BoundingBox(None)
        pts = [XYZ(x, y, bb.Min.Z) for x in (bb.Min.X, bb.Max.X) for y in (bb.Min.Y, bb.Max.Y)]
        if tf is not None:
            pts = [tf.OfPoint(p) for p in pts]
        self.minx = min(p.X for p in pts)
        self.maxx = max(p.X for p in pts)
        self.miny = min(p.Y for p in pts)
        self.maxy = max(p.Y for p in pts)
        num = el.get_Parameter(BuiltInParameter.ROOM_NUMBER)
        name = el.get_Parameter(BuiltInParameter.ROOM_NAME)
        num = num.AsString() if num else ""
        name = name.AsString() if name else ""
        self.label = u"{} {}".format(num or "", name or "").strip() or u"(unnamed)"

    def contains(self, x, y):
        p = XYZ(x, y, self.floor_z + self.test_dz)
        if self.inv is not None:
            p = self.inv.OfPoint(p)
        try:
            return self.el.IsPointInSpace(p) if self.is_space else self.el.IsPointInRoom(p)
        except Exception:
            return False

    def grid(self, step):
        x = math.floor(self.minx / step) * step + step / 2.0
        while x < self.maxx:
            y = math.floor(self.miny / step) * step + step / 2.0
            while y < self.maxy:
                if self.contains(x, y):
                    yield x, y
                y += step
            x += step


def placed(el):
    try:
        return el.Area > 0 and el.Location is not None and el.Level is not None
    except Exception:
        return False


def zones_on_level(level):
    z = level.ProjectElevation
    for source in ROOM_SOURCES:
        found = []
        if source in ("spaces", "rooms"):
            bic = BuiltInCategory.OST_MEPSpaces if source == "spaces" else BuiltInCategory.OST_Rooms
            for el in FilteredElementCollector(doc).OfCategory(bic).WhereElementIsNotElementType():
                if placed(el) and el.LevelId == level.Id:
                    found.append(Zone(el, source == "spaces", "This model", None))
        else:
            for li, ldoc, tf in loaded_links():
                for el in FilteredElementCollector(ldoc).OfCategory(BuiltInCategory.OST_Rooms).WhereElementIsNotElementType():
                    if not placed(el):
                        continue
                    zone = Zone(el, False, li.Name.split(" : ")[0], tf)
                    if abs(zone.floor_z - z) <= LEVEL_TOL:
                        found.append(zone)
        if found:
            return found
    return []


def zone_at(pt):
    for source in ROOM_SOURCES:
        if source == "spaces":
            el = doc.GetSpaceAtPoint(pt)
            if el is not None:
                return Zone(el, True, "This model", None)
        elif source == "rooms":
            el = doc.GetRoomAtPoint(pt)
            if el is not None:
                return Zone(el, False, "This model", None)
        else:
            for li, ldoc, tf in loaded_links():
                el = ldoc.GetRoomAtPoint(tf.Inverse.OfPoint(pt))
                if el is not None:
                    return Zone(el, False, li.Name.split(" : ")[0], tf)
    return None


# ---------------- Display ----------------
def display_style_id():
    style_cls = _api("AnalysisDisplayStyle")
    sid = style_cls.FindByName(doc, STYLE_NAME)
    if sid != ElementId.InvalidElementId:
        return sid
    markers = _api("AnalysisDisplayMarkersAndTextSettings")()
    markers.MarkerType = _api("AnalysisDisplayStyleMarkerType").Square
    try:
        markers.MarkerSize = MARKER_SIZE
    except Exception:
        pass
    try:
        markers.TextLabelType = _api("AnalysisDisplayStyleMarkerTextLabelType").Hide
    except Exception:
        pass
    colors = _api("AnalysisDisplayColorSettings")()
    colors.MinColor = Color(220, 40, 40)       # 0 = blocked
    colors.MaxColor = Color(40, 170, 60)       # 2 = covered
    entry_cls = _api("AnalysisDisplayColorEntry")
    colors.SetIntermediateColors(List[entry_cls]([entry_cls(Color(250, 190, 0))]))   # 1 = out of range
    try:
        colors.ColorSettingsType = _api("AnalysisDisplayStyleColorSettingsType").GradientColor
    except Exception:
        pass
    legend = _api("AnalysisDisplayLegendSettings")()
    legend.ShowLegend = True
    try:
        legend.NumberOfSteps = 2
        legend.ShowDataDescription = True
    except Exception:
        pass
    return style_cls.CreateAnalysisDisplayStyle(doc, STYLE_NAME, markers, colors, legend).Id


def result_index(sfm):
    for i in sfm.GetRegisteredResults():
        if sfm.GetResultSchema(i).Name == RESULT_NAME:
            return i
    schema = AN.AnalysisResultSchema(RESULT_NAME, "0 = blocked, 1 = outside every strobe's square, 2 = covered")
    return sfm.RegisterResult(schema)


def clear_results(view):
    sfm = AN.SpatialFieldManager.GetSpatialFieldManager(view)
    if sfm is not None:
        sfm.Clear()
        return True
    return False


def show_results(view, prims):
    t = Transaction(doc, "NAC Coverage Checker - display style")
    t.Start()
    try:
        sid = display_style_id()
        try:
            view.AnalysisDisplayStyleId = sid
        except Exception:
            pass   # a view template may control this; results still show with the template's style
        t.Commit()
    except Exception:
        t.RollBack()
        raise
    sfm = AN.SpatialFieldManager.GetSpatialFieldManager(view)
    if sfm is None:
        sfm = AN.SpatialFieldManager.CreateSpatialFieldManager(view, 1)
    else:
        sfm.Clear()
    ri = result_index(sfm)
    for pts, vals in prims:
        if not pts:
            continue
        idx = sfm.AddSpatialFieldPrimitive()
        domain = AN.FieldDomainPointsByXYZ(List[XYZ](pts))
        values = List[AN.ValueAtPoint]([AN.ValueAtPoint(List[float]([v])) for v in vals])
        sfm.UpdateSpatialFieldPrimitive(idx, domain, AN.FieldValues(values), ri)


# ---------------- Check ----------------
class Cancelled(Exception):
    pass


class ZoneResult(object):
    def __init__(self, zone):
        self.zone = zone
        self.pts = []
        self.vals = []
        self.used = set()
        self.nearby = 0

    def count(self, v):
        return sum(1 for x in self.vals if x == v)


def check_zone(zone, strobes, sight, pb_state):
    res = ZoneResult(zone)
    cands = []
    for s in strobes:
        aff = s.lens.Z - zone.floor_z
        if aff < 0 or aff > MAX_LENS_AFF + 1.0:
            continue
        size = s.size(zone.floor_z)
        if size <= 0:
            continue
        r = s.reach(size)
        if (s.lens.X + r < zone.minx or s.lens.X - r > zone.maxx or
                s.lens.Y + r < zone.miny or s.lens.Y - r > zone.maxy):
            continue
        cands.append((s, size))
    res.nearby = len(cands)
    eye_z = zone.floor_z + VIEW_HEIGHT
    show_z = zone.floor_z + DISPLAY_HEIGHT
    for x, y in zone.grid(GRID_STEP):
        inside = [(s, size) for s, size in cands if s.covers(x, y, size)]
        if not inside:
            v = OUT_OF_RANGE
        else:
            v = BLOCKED
            inside.sort(key=lambda c: (c[0].lens.X - x) ** 2 + (c[0].lens.Y - y) ** 2)
            target = XYZ(x, y, eye_z)
            for s, size in inside:
                if sight.clear(s.origin, target):
                    v = COVERED
                    res.used.add(eid(s.id))
                    break
        res.pts.append(XYZ(x, y, show_z))
        res.vals.append(v)
        pb_state["done"] += 1
        if pb_state["done"] % 25 == 0:
            pb_state["pb"].update_progress(min(pb_state["done"], pb_state["total"]), pb_state["total"])
            if pb_state["pb"].cancelled:
                raise Cancelled()
    return res


def estimate_points(zone):
    area = max(zone.el.Area, 0.0)
    return int(area / (GRID_STEP * GRID_STEP)) + 1


def pct(n, total):
    return "{:.0f}%".format(100.0 * n / total) if total else "-"


def report(results, strobes, no_param, issues, scope, cancelled):
    output.print_md("# NAC Coverage Checker")
    output.print_md("{} | test points every {:g} ft at {:g} ft above the floor | {} strobe(s) with a candela value{}"
                    .format(scope, GRID_STEP, VIEW_HEIGHT, len(strobes),
                            " | **cancelled - partial results**" if cancelled else ""))
    output.print_md("Green = covered, yellow = outside every strobe's coverage square, "
                    "red = inside a square but the line of sight is blocked.")
    rows = []
    tot = [0, 0, 0, 0]
    for r in results:
        n = len(r.vals)
        c, o, b = r.count(COVERED), r.count(OUT_OF_RANGE), r.count(BLOCKED)
        tot[0] += n
        tot[1] += c
        tot[2] += o
        tot[3] += b
        rows.append([r.zone.label, r.zone.source, n, pct(c, n), pct(b, n), pct(o, n), len(r.used)])
    rows.sort(key=lambda row: row[0])
    if rows:
        rows.append(["**Total**", "", tot[0], pct(tot[1], tot[0]), pct(tot[3], tot[0]), pct(tot[2], tot[0]), ""])
        output.print_table(rows, columns=["Room / Space", "From", "Points", "Covered", "Blocked",
                                          "Out of range", "Strobes seen"])
    if no_param:
        output.print_md("{} Fire Alarm Device(s) near this level have no candela parameter ({}) and were ignored "
                        "(detectors, pull stations, horns...).".format(no_param, ", ".join(CANDELA_PARAMS)))
    notes = []
    for s in strobes:
        aff = None
        if s.mount == CEILING:
            for r in results:
                aff = s.lens.Z - r.zone.floor_z
                break
            if aff is not None and aff > MAX_LENS_AFF:
                notes.append((s.id, "Ceiling lens {:.1f} ft above the floor: above the 30 ft table, no coverage counted."
                              .format(aff)))
    if issues or notes:
        output.print_md("### Devices to check")
        output.print_table([[output.linkify(i), msg] for i, msg in issues + notes], columns=["Device", "Issue"])
    return tot


def main():
    view = doc.ActiveView
    if view.ViewType != ViewType.FloorPlan or view.GenLevel is None:
        forms.alert("Open a floor plan first. The colored results are drawn in the active floor plan.", title=TITLE)
        return
    choice = forms.CommandSwitchWindow.show(["Entire view", "Pick a room", "Clear results"],
                                            message="NAC Coverage Checker: what should be checked?")
    if not choice:
        return
    if choice == "Clear results":
        if not clear_results(view):
            forms.alert("No coverage results are shown in this view.", title=TITLE)
        return

    level = view.GenLevel
    if choice == "Pick a room":
        try:
            pt = uidoc.Selection.PickPoint("Click inside the room or space to check")
        except OperationCanceledException:
            return
        zone = zone_at(XYZ(pt.X, pt.Y, level.ProjectElevation + 1.0))
        if zone is None:
            forms.alert("No room or space found there (checked MEP Spaces, Rooms, and Rooms in loaded links).",
                        title=TITLE)
            return
        zones = [zone]
        scope = u"Room: {}".format(zone.label)
    else:
        zones = zones_on_level(level)
        if not zones:
            forms.alert("No placed rooms or spaces found on level '{}' (checked MEP Spaces, Rooms, and Rooms "
                        "in loaded links).".format(level.Name), title=TITLE)
            return
        scope = u"Entire view: {} room(s) / space(s) on {}".format(len(zones), level.Name)

    view3d = analysis_view()
    sight = Sight(view3d)
    issues = []
    z_low = min(z.floor_z for z in zones)
    z_high = max(z.floor_z for z in zones) + MAX_LENS_AFF + 1.0
    strobes, no_param = collect_strobes(sight, z_low, z_high, issues)
    if not strobes:
        forms.alert("No Fire Alarm Devices with a candela value were found near this level.\n\n"
                    "The candela is read from the first of these parameters found on the instance or type: "
                    "{}.".format(", ".join(CANDELA_PARAMS)), title=TITLE)
        if issues:
            report([], strobes, no_param, issues, scope, False)
        return

    results = []
    cancelled = False
    total = sum(estimate_points(z) for z in zones)
    with forms.ProgressBar(title="NAC coverage: checking sight lines...", cancellable=True) as pb:
        state = {"pb": pb, "done": 0, "total": max(total, 1)}
        for zone in zones:
            try:
                results.append(check_zone(zone, strobes, sight, state))
            except Cancelled:
                cancelled = True
                break
            except Exception as ex:
                issues.append((zone.el.Id if zone.tf is None else view.Id,
                               u"Room '{}' could not be checked: {}".format(zone.label, ex)))

    show_results(view, [(r.pts, r.vals) for r in results])
    tot = report(results, strobes, no_param, issues, scope, cancelled)
    forms.alert("{}\n\nCovered: {}   Blocked: {}   Out of range: {}\n\n"
                "Details are in the output window. Run again and choose 'Clear results' to remove the colors."
                .format(scope, pct(tot[1], tot[0]), pct(tot[3], tot[0]), pct(tot[2], tot[0])), title=TITLE)


main()
