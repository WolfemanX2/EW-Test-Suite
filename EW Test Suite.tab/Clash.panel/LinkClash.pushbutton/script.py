# -*- coding: utf-8 -*-
# Link Clash script - version v14
# v14 - code audit: messages without the warning sound; statuses and last results saved with the shared safe
#       write (lib/config_store.py), so a failed save never loses the file; ElementId numbers from ew_common
__title__ = "Link\nClash v14"
__doc__ = ("Tests the selected elements against MEP and structural elements in every loaded Revit link "
           "and lists each clash. Select elements first, or run with nothing selected to pick them. "
           "When it finishes, the selected elements that clash are left selected and a results window "
           "offers 'Show in 3D' (Selection Box on your element) and 'Auto Fix' (shift or jog a clashing "
           "conduit) for each clash, plus a status (New, Active, Reviewed, Cleared, Approved, Resolved) that is "
           "remembered between checks. Run with nothing selected to reopen the last results.")

import math
import os
import json
import tempfile
import hashlib
import datetime
from pyrevit import revit, forms, script
from Autodesk.Revit.DB import (
    XYZ, ElementId, FilteredElementCollector, BuiltInCategory, RevitLinkInstance,
    ElementMulticategoryFilter, BoundingBoxIntersectsFilter, ElementIntersectsSolidFilter,
    Outline, Options, ViewDetailLevel, Solid, GeometryInstance, SolidUtils,
    BooleanOperationsUtils, BooleanOperationsType,
    Transaction, SubTransaction, TransactionStatus, Line, Arc, CurveLoop,
    GeometryCreationUtilities, ElementTransformUtils, BuiltInParameter, Domain, ConnectorType,
    FamilyInstance, IndependentTag
)
from Autodesk.Revit.DB.Electrical import Conduit
from Autodesk.Revit.UI import RevitCommandId, PostableCommand
from Autodesk.Revit.UI.Selection import ObjectType
import System
from System.Windows import RoutedEventHandler
from System.Windows.Controls import Button, ComboBox, SelectionChangedEventHandler
from System.Windows.Controls.Primitives import Selector
from Autodesk.Revit.Exceptions import OperationCanceledException
from System.Collections.Generic import List
from System.Windows.Data import CollectionViewSource, PropertyGroupDescription
from ew_common import eid, element_id, tagged_hosts, alert     # shared helpers (lib/ew_common.py)
import config_store as cs    # the safe write for the status and results files (lib/config_store.py)

try:
    import clash_rules          # lib/clash_rules.py, edited with the Link Clash - Config tool
except Exception:
    clash_rules = None

doc = revit.doc
uidoc = revit.uidoc

# ---------------- Settings ----------------
MIN_CLASH_VOLUME = 0.0005   # cubic feet (about 1 cubic inch); smaller overlaps are treated as touching, not clashing
SELECT_CLASHING = True      # leave the clashing elements selected when the check finishes
MAX_ROWS = 500              # most clashes listed
PRINT_REPORT = False        # True = also print the clash table in pyRevit's output window
# --- Auto Fix (lengths in feet) ---
# These are only the fallback values. When lib/clash_rules.py is installed, the rules saved by the
# Link Clash - Config tool replace them every time a fix runs.
ALLOW_SHIFT = True          # try moving the conduit sideways first
ALLOW_H_JOG = True          # horizontal jogs (90 degree bends)
ALLOW_V_JOG = True          # vertical jogs (angled bends)
V_JOG_MIN_ANGLE = 15        # vertical jog (saddle) bend angles: multiples of 5 in this range,
V_JOG_MAX_ANGLE = 90        # smallest angle tried first
MAX_SADDLE_LENGTH = 4.0     # a small angle makes a long saddle; angles whose saddle would be longer than
                            # this are only used if nothing shorter fits
DEVICE_MODE = "ask"         # conduit joined straight to a device, when an elevation change is tried:
                            # "ask" each time, "keep" the device in place, or "move" it with the conduit
MAJORITY_ELEVATION = True   # conduit with several clashes: first try one elevation change that clears
                            # more than half of them, then saddle around whatever is left
ELEVATION_MODE = "never"    # raise/lower the whole conduit: "never", "before" jogs or "after" jogs
MAX_ELEV_CHANGE = 1.0       # furthest the whole conduit may be raised or lowered
ASK_BEFORE_FIX = True       # starting state of the "Ask before applying each fix" box in the results window
FIX_CLEARANCE = 1.0 / 12    # gap Auto Fix leaves between the conduit and anything in the links
MAX_SHIFT = 1.0             # furthest a conduit may be moved sideways before a jog is tried instead
SHIFT_STEP = 1.0 / 12       # sideways moves are tried in steps of this size, smallest first
MAX_SHIFT_TRIES = 8         # most sideways positions actually tried in the model per fix
JOG_LEAD = 0.5              # straight run kept between the obstacle and where the jog starts and ends
JOG_MIN_LEG = 0.75          # shortest piece Auto Fix will create (elbows need room)
RESULTS_WINDOW = True       # open the results window with "Show in 3D" and "Auto Fix" buttons for each clash
# --- clash status ---
STATUSES = ["New", "Active", "Reviewed", "Cleared", "Approved", "Resolved"]
OPEN_STATUSES = ("New", "Active", "Reviewed")
SIGNED_OFF = ("Reviewed", "Cleared", "Approved")   # a retest never overwrites these while the clash remains
STATUS_DIR = None           # folder for saved statuses. None = your own %APPDATA%\pyRevit\LinkClash.
                            # Set a shared path (e.g. r"\\server\share\LinkClash") so the team sees the same statuses.
LINK_CATS = [               # categories tested inside the links
    # structure
    BuiltInCategory.OST_StructuralFraming, BuiltInCategory.OST_StructuralColumns,
    BuiltInCategory.OST_StructuralFoundation,
    # mechanical
    BuiltInCategory.OST_DuctCurves, BuiltInCategory.OST_DuctFitting, BuiltInCategory.OST_DuctAccessory,
    BuiltInCategory.OST_DuctTerminal, BuiltInCategory.OST_FlexDuctCurves,
    BuiltInCategory.OST_MechanicalEquipment,
    # piping / plumbing / fire protection
    BuiltInCategory.OST_PipeCurves, BuiltInCategory.OST_PipeFitting, BuiltInCategory.OST_PipeAccessory,
    BuiltInCategory.OST_FlexPipeCurves, BuiltInCategory.OST_PlumbingFixtures, BuiltInCategory.OST_Sprinklers,
    # electrical
    BuiltInCategory.OST_CableTray, BuiltInCategory.OST_CableTrayFitting,
    BuiltInCategory.OST_Conduit, BuiltInCategory.OST_ConduitFitting,
    BuiltInCategory.OST_ElectricalEquipment, BuiltInCategory.OST_LightingFixtures,
    # add these if you also want architectural / slab clashes:
    # BuiltInCategory.OST_Walls, BuiltInCategory.OST_Floors, BuiltInCategory.OST_Ceilings,
    # BuiltInCategory.OST_Columns,
]
# ------------------------------------------


def describe(el):
    """(category, name) of an element for the report."""
    try:
        cat = el.Category.Name if el.Category else "?"
    except Exception:
        cat = "?"
    name = ""
    try:
        name = u"{} : {}".format(el.Symbol.Family.Name, el.Name)
    except Exception:
        try:
            name = el.Name
        except Exception:
            pass
    return cat, name


def element_solids(el):
    """Every solid with volume in an element's geometry, in its own document's coordinates."""
    opts = Options()
    opts.DetailLevel = ViewDetailLevel.Fine   # conduit, pipe and duct only have solids at Fine
    out = []

    def walk(geo):
        for obj in geo:
            if isinstance(obj, Solid):
                try:
                    if obj.Volume > 1e-9:
                        out.append(obj)
                except Exception:
                    pass
            elif isinstance(obj, GeometryInstance):
                try:
                    walk(obj.GetInstanceGeometry())
                except Exception:
                    pass

    try:
        geo = el.get_Geometry(opts)
        if geo is not None:
            walk(geo)
    except Exception:
        pass
    return out


def solids_outline(solids):
    """Outline around a list of solids, or None."""
    lo = [1e30, 1e30, 1e30]
    hi = [-1e30, -1e30, -1e30]
    found = False
    for s in solids:
        try:
            bb = s.GetBoundingBox()
            t = bb.Transform
            mn, mx = bb.Min, bb.Max
            for x in (mn.X, mx.X):
                for y in (mn.Y, mx.Y):
                    for z in (mn.Z, mx.Z):
                        p = t.OfPoint(XYZ(x, y, z))
                        for k, v in enumerate((p.X, p.Y, p.Z)):
                            if v < lo[k]:
                                lo[k] = v
                            if v > hi[k]:
                                hi[k] = v
            found = True
        except Exception:
            pass
    if not found:
        return None
    return Outline(XYZ(*lo), XYZ(*hi))


def overlap_volume(solids_a, solids_b):
    """Total intersection volume between two sets of solids, or None if Revit couldn't compute any of it."""
    total = 0.0
    computed = False
    for a in solids_a:
        for b in solids_b:
            try:
                inter = BooleanOperationsUtils.ExecuteBooleanOperation(a, b, BooleanOperationsType.Intersect)
                computed = True
                if inter is not None:
                    total += inter.Volume
            except Exception:
                pass
    return total if computed else None


def get_selection():
    """Current selection, or a picked set if nothing is selected. Returns a list of elements."""
    ids = list(uidoc.Selection.GetElementIds())
    if not ids:
        try:
            refs = uidoc.Selection.PickObjects(ObjectType.Element,
                                               "Select elements (or their tags) to clash-test against the links, then Finish")
        except OperationCanceledException:
            return []
        ids = [r.ElementId for r in refs]
    out, seen = [], set()
    for i in ids:
        el = doc.GetElement(i)
        # A tag stands for the element it is hosted to.
        for e in (tagged_hosts(el) if isinstance(el, IndependentTag) else [el]):
            if e is not None and not isinstance(e, RevitLinkInstance) and eid(e) not in seen:
                seen.add(eid(e))
                out.append(e)
    return out


def loaded_links():
    """(link instance, link document, transform to host) for each loaded link, plus names of unloaded ones."""
    links, unloaded = [], []
    for li in FilteredElementCollector(doc).OfClass(RevitLinkInstance):
        ldoc = None
        try:
            ldoc = li.GetLinkDocument()
        except Exception:
            pass
        if ldoc is None:
            unloaded.append(li.Name)
            continue
        links.append((li, ldoc, li.GetTotalTransform()))
    return links, unloaded


def host_box(le, tf):
    """Bounding box corners of a link element in host coordinates (8 xyz tuples), or None."""
    try:
        bb = le.get_BoundingBox(None)
        if bb is None:
            return None
        mn, mx = bb.Min, bb.Max
        pts = [tf.OfPoint(XYZ(x, y, z)) for x in (mn.X, mx.X) for y in (mn.Y, mx.Y) for z in (mn.Z, mx.Z)]
        return [(p.X, p.Y, p.Z) for p in pts]
    except Exception:
        return None


def check_element(el, solids, links, cat_filter, solid_cache):
    """Clashes for one selected element. Returns rows of
    (link title, link element, overlap volume or None, link element box corners in host coordinates)."""
    rows = []
    for li, ldoc, tf in links:
        inv = tf.Inverse
        try:
            local = [SolidUtils.CreateTransformed(s, inv) for s in solids]   # selection in link coordinates
        except Exception:
            continue
        outline = solids_outline(local)
        if outline is None:
            continue
        # quick pass: link elements whose bounding box overlaps the selected element's
        cand = list(FilteredElementCollector(ldoc)
                    .WherePasses(cat_filter)
                    .WhereElementIsNotElementType()
                    .WherePasses(BoundingBoxIntersectsFilter(outline))
                    .ToElementIds())
        if not cand:
            continue
        cand_list = List[ElementId](cand)
        # exact pass: real geometry intersection
        hits = {}
        filter_failed = False
        for s in local:
            try:
                for e in (FilteredElementCollector(ldoc, cand_list)
                          .WherePasses(ElementIntersectsSolidFilter(s))):
                    hits[eid(e)] = e
            except Exception:
                filter_failed = True
        if filter_failed:   # fall back to the candidates; the volume test below decides
            for i in cand:
                if eid(i) not in hits:
                    hits[eid(i)] = ldoc.GetElement(i)
        for k, le in hits.items():
            ck = (ldoc.PathName or ldoc.Title, k)
            if ck not in solid_cache:
                solid_cache[ck] = element_solids(le)
            vol = overlap_volume(local, solid_cache[ck]) if solid_cache[ck] else None
            if vol is None:
                if filter_failed:
                    continue   # nothing confirmed this one
            elif vol < MIN_CLASH_VOLUME:
                continue       # touching or negligible overlap
            rows.append((ldoc.Title, le, vol, host_box(le, tf)))
    return rows


# ---------------- results window + "Show in 3D" ----------------

RESULTS_XAML = """
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        xmlns:sys="clr-namespace:System;assembly=mscorlib"
        Title="Link Clash results" Width="1340" Height="560" ShowInTaskbar="False"
        WindowStartupLocation="CenterScreen">
    <DockPanel Margin="8">
        <TextBlock x:Name="status_text" DockPanel.Dock="Bottom" Margin="0,6,0,0" TextWrapping="Wrap" />
        <CheckBox x:Name="ask_check" DockPanel.Dock="Bottom" Margin="0,6,0,0"
                  Content="Ask before applying each Auto Fix" />
        <StackPanel DockPanel.Dock="Top" Orientation="Horizontal" Margin="0,0,0,6">
            <TextBlock Text="Show:" VerticalAlignment="Center" Margin="0,0,6,0" />
            <ComboBox x:Name="filter_combo" Width="190" Margin="0,0,20,0" />
            <TextBlock Text="Group by:" VerticalAlignment="Center" Margin="0,0,6,0" />
            <ComboBox x:Name="group_combo" Width="150" Margin="0,0,20,0" />
            <TextBlock Text="Set highlighted rows to:" VerticalAlignment="Center" Margin="0,0,6,0" />
            <ComboBox x:Name="bulk_combo" Width="110" Margin="0,0,6,0" />
            <Button x:Name="bulk_btn" Content="Apply" Padding="10,1" />
            <TextBlock x:Name="count_text" VerticalAlignment="Center" Margin="20,0,0,0" />
        </StackPanel>
        <ListView x:Name="clash_list" SelectionMode="Extended">
            <ListView.GroupStyle>
                <GroupStyle>
                    <GroupStyle.HeaderTemplate>
                        <DataTemplate>
                            <TextBlock FontWeight="Bold" Margin="2,8,0,2">
                                <Run Text="{Binding Name, Mode=OneWay}" />
                                <Run Text="  -  " />
                                <Run Text="{Binding ItemCount, Mode=OneWay}" />
                                <Run Text="clash(es)" />
                            </TextBlock>
                        </DataTemplate>
                    </GroupStyle.HeaderTemplate>
                </GroupStyle>
            </ListView.GroupStyle>
            <ListView.View>
                <GridView>
                    <GridViewColumn Header="Status" Width="105">
                        <GridViewColumn.CellTemplate>
                            <DataTemplate>
                                <ComboBox Width="92" SelectedItem="{Binding status, Mode=OneWay}">
                                    <sys:String>New</sys:String>
                                    <sys:String>Active</sys:String>
                                    <sys:String>Reviewed</sys:String>
                                    <sys:String>Cleared</sys:String>
                                    <sys:String>Approved</sys:String>
                                    <sys:String>Resolved</sys:String>
                                </ComboBox>
                            </DataTemplate>
                        </GridViewColumn.CellTemplate>
                    </GridViewColumn>
                    <GridViewColumn Header="3D" Width="90">
                        <GridViewColumn.CellTemplate>
                            <DataTemplate>
                                <Button Content="Show in 3D" Padding="6,1" />
                            </DataTemplate>
                        </GridViewColumn.CellTemplate>
                    </GridViewColumn>
                    <GridViewColumn Header="Fix" Width="80">
                        <GridViewColumn.CellTemplate>
                            <DataTemplate>
                                <Button Content="Auto Fix" Padding="6,1" />
                            </DataTemplate>
                        </GridViewColumn.CellTemplate>
                    </GridViewColumn>
                    <GridViewColumn Header="Element id" Width="80" DisplayMemberBinding="{Binding sel}" />
                    <GridViewColumn Header="Description" Width="220" DisplayMemberBinding="{Binding desc}" />
                    <GridViewColumn Header="Link" Width="150" DisplayMemberBinding="{Binding link}" />
                    <GridViewColumn Header="Clashes with" Width="120" DisplayMemberBinding="{Binding cat}" />
                    <GridViewColumn Header="Type" Width="170" DisplayMemberBinding="{Binding type}" />
                    <GridViewColumn Header="Link element id" Width="95" DisplayMemberBinding="{Binding lid}" />
                    <GridViewColumn Header="Overlap (cu in)" Width="90" DisplayMemberBinding="{Binding overlap}" />
                    <GridViewColumn Header="Status set by" Width="170" DisplayMemberBinding="{Binding status_by}" />
                </GridView>
            </ListView.View>
        </ListView>
    </DockPanel>
</Window>
"""


class ClashRow(object):
    """One clash, holding only plain data so it stays valid after the check has finished."""
    def __init__(self, host_id, desc, link, cat, type_name, lid, overlap, link_box):
        self.host_int = eid(host_id)   # plain integer, so rows can be saved and reopened
        self.sel = str(self.host_int)
        self.desc = desc
        self.link = link
        self.cat = cat
        self.type = type_name
        self.lid = str(lid)
        self.overlap = overlap
        self.link_box = link_box    # 8 corners of the link element in host coordinates, or None
        self.status = STATUSES[0]
        self.status_by = ""         # "user, date" of the last status change, for the window

    @property
    def group_host(self):
        return u"Element {} - {}".format(self.sel, self.desc)

    @property
    def group_link(self):
        return u"{} {} (id {}) in {}".format(self.cat, self.type, self.lid, self.link)

    @property
    def key(self):
        """Identifies the same clash between checks: our element, the link, the link element."""
        return u"{}|{}|{}".format(self.host_int, self.link, self.lid)

    @property
    def host_id(self):
        return element_id(self.host_int)

    def to_dict(self):
        return {"id": self.host_int, "desc": self.desc, "link": self.link, "cat": self.cat,
                "type": self.type, "lid": self.lid, "overlap": self.overlap, "box": self.link_box}

    @staticmethod
    def from_dict(d):
        box = [tuple(c) for c in d["box"]] if d.get("box") else None
        return ClashRow(d["id"], d["desc"], d["link"], d["cat"], d["type"], d["lid"], d["overlap"], box)


# ---- clash statuses, saved per model ----

def model_key():
    """The central model path for workshared models (so every user's local copy matches), else the file path."""
    try:
        if doc.IsWorkshared:
            from Autodesk.Revit.DB import ModelPathUtils
            return ModelPathUtils.ConvertModelPathToUserVisiblePath(doc.GetWorksharingCentralModelPath())
    except Exception:
        pass
    return doc.PathName or doc.Title


def status_file():
    folder = STATUS_DIR or os.path.join(os.getenv("APPDATA") or tempfile.gettempdir(), "pyRevit", "LinkClash")
    if not os.path.isdir(folder):
        os.makedirs(folder)
    key = model_key()
    base = os.path.splitext(os.path.basename(key))[0] or "model"
    base = "".join(ch if (ch.isalnum() or ch in "-_ ") else "_" for ch in base)
    tag = hashlib.md5(key.encode("utf-8")).hexdigest()[:8]
    return os.path.join(folder, u"{}_{}.json".format(base, tag))


def load_statuses():
    """{clash key: {"status", "by", "at"}} for this model, or {}."""
    try:
        with open(status_file(), "r") as f:
            return json.load(f).get("clashes", {})
    except Exception:
        return {}


def save_statuses(changed):
    """Merge changed {key: entry} into the saved file (re-read first, so other users' changes are kept)."""
    try:
        data = load_statuses()
        data.update(changed)
        cs.write_json(status_file(), {"model": model_key(), "clashes": data}, indent=1)
        return True
    except Exception:
        return False


def apply_statuses(rows):
    saved = load_statuses()
    for r in rows:
        e = saved.get(r.key)
        if e and e.get("status") in STATUSES:
            r.status = e["status"]
            r.status_by = u"{}, {}".format(e.get("by", ""), e.get("at", ""))
        else:
            r.status, r.status_by = STATUSES[0], ""


def set_status(rows, status):
    """Set the status of rows and save. Returns False if the file couldn't be written."""
    who = doc.Application.Username
    when = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    changed = {}
    for r in rows:
        r.status = status
        r.status_by = u"{}, {}".format(who, when)
        changed[r.key] = {"status": status, "by": who, "at": when}
    return save_statuses(changed)


def reactivate(rows):
    """After a fresh check: a clash saved as Resolved that has been found again is Active."""
    back = [r for r in rows if r.status == "Resolved"]
    if back:
        set_status(back, "Active")


def update_after_fix(rows, fixed_id, remaining):
    """Retest result for an element Auto Fix just changed. remaining = {(link, link element id): id of the
    piece of our conduit that still clashes with it}. Its clashes that are gone become Resolved; those
    still there become Active (unless already Reviewed, Cleared or Approved) and point at the piece
    that clashes, since a jog splits the conduit. Returns (resolved count, still clashing count)."""
    resolved, active, still = [], [], 0
    for r in rows:
        if r.host_int != fixed_id:
            continue
        try:
            piece = remaining.get((r.link, int(r.lid)))
        except Exception:
            piece = None
        if piece is None:
            resolved.append(r)
            continue
        still += 1
        if piece != r.host_int:
            r.host_int = piece
            r.sel = str(piece)
        if r.status not in SIGNED_OFF:
            active.append(r)
    if resolved:
        set_status(resolved, "Resolved")
    if active:
        set_status(active, "Active")
    return len(resolved), still


# ---- last results, saved so the window can be reopened after Show in 3D ends the tool ----

def doc_key():
    return doc.PathName or doc.Title


def results_file():
    return os.path.join(tempfile.gettempdir(), "pyrevit_link_clash_last.json")


def save_results(rows):
    try:
        cs.write_json(results_file(), {"doc": doc_key(), "rows": [r.to_dict() for r in rows]}, indent=None)
    except Exception:
        pass


def load_results():
    """Rows saved by the last check on this model, or []."""
    try:
        with open(results_file(), "r") as f:
            data = json.load(f)
        if data.get("doc") != doc_key():
            return []
        return [ClashRow.from_dict(d) for d in data.get("rows", [])]
    except Exception:
        return []


def show_in_3d(row):
    """Select the element and post Revit's own Selection Box command. Returns (posted, message).
    The posted command runs as soon as this tool finishes, so the results window must be closed first."""
    if doc.GetElement(row.host_id) is None:
        return False, "Element {} no longer exists in this model.".format(row.sel)
    uiapp = uidoc.Application
    uidoc.Selection.SetElementIds(List[ElementId]([row.host_id]))
    cmd = RevitCommandId.LookupPostableCommandId(PostableCommand.SelectionBox)
    if not uiapp.CanPostCommand(cmd):
        return False, ("Element {} is selected, but Revit can't run Selection Box right now. "
                       "Close this window and press BX.".format(row.sel))
    uiapp.PostCommand(cmd)
    return True, ""


# ---------------- Auto Fix ----------------

def load_fix_rules():
    """Replace the Auto Fix settings with the rules saved by the Link Clash - Config tool, if it is installed."""
    global ASK_BEFORE_FIX, FIX_CLEARANCE, MAX_SHIFT, SHIFT_STEP, JOG_LEAD, JOG_MIN_LEG
    global ALLOW_SHIFT, ALLOW_H_JOG, ALLOW_V_JOG, ELEVATION_MODE, MAX_ELEV_CHANGE
    global V_JOG_MIN_ANGLE, V_JOG_MAX_ANGLE, MAX_SADDLE_LENGTH, MAJORITY_ELEVATION, DEVICE_MODE
    if clash_rules is None:
        return
    try:
        r = clash_rules.load_rules()
        ASK_BEFORE_FIX = r["ask_before"]
        FIX_CLEARANCE = r["clearance"]
        ALLOW_SHIFT = r["allow_shift"]
        MAX_SHIFT = r["max_shift"]
        SHIFT_STEP = r["shift_step"]
        ALLOW_H_JOG = r["allow_h_jog"]
        ALLOW_V_JOG = r["allow_v_jog"]
        JOG_LEAD = r["jog_lead"]
        JOG_MIN_LEG = r["jog_min_leg"]
        MAX_ELEV_CHANGE = r["max_elev_change"]
        MAX_SADDLE_LENGTH = r.get("max_saddle_length", MAX_SADDLE_LENGTH)
        MAJORITY_ELEVATION = r.get("majority_elevation", MAJORITY_ELEVATION)
        DEVICE_MODE = {getattr(clash_rules, "DEVICE_KEEP", None): "keep",
                       getattr(clash_rules, "DEVICE_MOVE", None): "move"}.get(r.get("device_mode"), "ask")
        V_JOG_MIN_ANGLE = r.get("v_jog_min_angle", V_JOG_MIN_ANGLE)
        V_JOG_MAX_ANGLE = r.get("v_jog_max_angle", V_JOG_MAX_ANGLE)
        ELEVATION_MODE = {clash_rules.ELEV_BEFORE: "before",
                          clash_rules.ELEV_AFTER: "after"}.get(r["elevation_mode"], "never")
    except Exception:
        pass


class FixFailed(Exception):
    pass


def inches(v):
    return "{:.1f} in".format(abs(v) * 12.0)


def compass(v):
    """Rough plan direction of a vector, in project axes."""
    if abs(v.X) >= abs(v.Y):
        return "project east (+X)" if v.X >= 0 else "project west (-X)"
    return "project north (+Y)" if v.Y >= 0 else "project south (-Y)"


def cylinder(p, q, radius):
    """Solid cylinder around the line p-q."""
    axis = q - p
    length = axis.GetLength()
    z = axis.Normalize()
    x = z.CrossProduct(XYZ.BasisZ if abs(z.Z) < 0.9 else XYZ.BasisX).Normalize()
    y = z.CrossProduct(x)
    loop = CurveLoop()
    loop.Append(Arc.Create(p, radius, 0.0, math.pi, x, y))
    loop.Append(Arc.Create(p, radius, math.pi, 2.0 * math.pi, x, y))
    return GeometryCreationUtilities.CreateExtrusionGeometry(List[CurveLoop]([loop]), z, length)


def path_hits(pts, radius, ctx):
    """Set of (link, element id) hit by cylinders along consecutive points, or None if it couldn't be tested."""
    hits = set()
    try:
        for i in range(len(pts) - 1):
            if pts[i].DistanceTo(pts[i + 1]) < 1e-6:
                continue
            solid = cylinder(pts[i], pts[i + 1], radius)
            for li, ldoc, tf in ctx["links"]:
                local = SolidUtils.CreateTransformed(solid, tf.Inverse)
                outline = solids_outline([local])
                if outline is None:
                    return None
                cand = (FilteredElementCollector(ldoc)
                        .WherePasses(ctx["cats"])
                        .WhereElementIsNotElementType()
                        .WherePasses(BoundingBoxIntersectsFilter(outline))
                        .ToElementIds())
                if cand.Count == 0:
                    continue
                for i2 in (FilteredElementCollector(ldoc, cand)
                           .WherePasses(ElementIntersectsSolidFilter(local))
                           .ToElementIds()):
                    hits.add((ldoc.Title, eid(i2)))
        return hits
    except Exception:
        return None


def path_clear(pts, radius, ctx):
    """True if cylinders along consecutive points hit nothing in any link. Unknown counts as blocked."""
    hits = path_hits(pts, radius, ctx)
    return hits is not None and not hits


def clash_boxes(el, ctx):
    """{(link, element id): box corners of that link element in host coordinates} for an element's clashes."""
    solids = element_solids(el)
    if not solids:
        return {}
    return dict(((title, eid(le)), box) for title, le, _, box in
                check_element(el, solids, ctx["links"], ctx["cats"], ctx["cache"]))


def clash_keys(el, ctx):
    """Set of (link, element id) this element currently clashes with."""
    return set(clash_boxes(el, ctx))


def conduit_conns(el):
    return [c for c in el.ConnectorManager.Connectors
            if c.Domain == Domain.DomainCableTrayConduit and c.ConnectorType != ConnectorType.Logical]


def partners(conn):
    """Physical connectors on other elements joined to this connector."""
    out = []
    for r in conn.AllRefs:
        try:
            if (r.Owner.Id != conn.Owner.Id and r.ConnectorType != ConnectorType.Logical
                    and r.Domain == Domain.DomainCableTrayConduit):
                out.append(r)
        except Exception:
            pass
    return out


def connected_count(el):
    return len([c for c in conduit_conns(el) if c.IsConnected])


def neighbours(conduit):
    """Conduits joined to this one, directly or through one fitting."""
    out = {}
    for c in conduit_conns(conduit):
        for r in partners(c):
            owner = r.Owner
            if isinstance(owner, Conduit):
                out[eid(owner)] = owner
                continue
            try:
                for c2 in owner.MEPModel.ConnectorManager.Connectors:
                    for r2 in c2.AllRefs:
                        o2 = r2.Owner
                        if isinstance(o2, Conduit) and o2.Id != conduit.Id:
                            out[eid(o2)] = o2
            except Exception:
                pass
    return list(out.values())


def connected_devices(conduit):
    """Devices (family instances that aren't conduit fittings) joined straight to this conduit."""
    fitting = ElementId(BuiltInCategory.OST_ConduitFitting)
    out = {}
    for c in conduit_conns(conduit):
        for r in partners(c):
            owner = r.Owner
            try:
                if isinstance(owner, FamilyInstance) and owner.Category.Id != fitting:
                    out[eid(owner)] = owner
            except Exception:
                pass
    return list(out.values())


def device_conduits(device, skip_id):
    """Other conduits joined to a device, directly or through one fitting (they stretch if the device moves)."""
    out = {}
    try:
        conns = list(device.MEPModel.ConnectorManager.Connectors)
    except Exception:
        return []
    for c in conns:
        try:
            refs = list(c.AllRefs)
        except Exception:
            continue
        for r in refs:
            owner = r.Owner
            if isinstance(owner, Conduit):
                if owner.Id != skip_id:
                    out[eid(owner)] = owner
            elif isinstance(owner, FamilyInstance) and owner.Id != device.Id:
                try:
                    for c2 in owner.MEPModel.ConnectorManager.Connectors:
                        for r2 in c2.AllRefs:
                            o2 = r2.Owner
                            if isinstance(o2, Conduit) and o2.Id != skip_id:
                                out[eid(o2)] = o2
                except Exception:
                    pass
    return list(out.values())


def location_of(el):
    try:
        p = el.Location.Point
        return (p.X, p.Y, p.Z)
    except Exception:
        return None


def closest_conn(el, pt):
    best, bd = None, 1e9
    for c in conduit_conns(el):
        d = c.Origin.DistanceTo(pt)
        if d < bd:
            best, bd = c, d
    return best


def conduit_radius(conduit):
    for bip in (BuiltInParameter.RBS_CONDUIT_OUTER_DIAM_PARAM, BuiltInParameter.RBS_CONDUIT_DIAMETER_PARAM):
        try:
            p = conduit.get_Parameter(bip)
            if p is not None and p.AsDouble() > 0:
                return p.AsDouble() / 2.0
        except Exception:
            pass
    return conduit.Diameter / 2.0


def move_candidates(p0, p1, radius, ctx, normals, max_dist, describe_move):
    """Whole-conduit moves along the given directions that look clear, smallest first: (vector, description)."""
    out = []
    steps = int(math.floor(max_dist / SHIFT_STEP + 1e-6))
    for k in range(1, steps + 1):
        for n in normals:
            for sign in (1.0, -1.0):
                v = n * (sign * k * SHIFT_STEP)
                if path_clear([p0 + v, p1 + v], radius + FIX_CLEARANCE, ctx):
                    out.append((v, describe_move(v, k * SHIFT_STEP)))
                    if len(out) >= MAX_SHIFT_TRIES:
                        return out
    return out


def shift_candidates(p0, p1, radius, ctx):
    """Sideways moves."""
    if not ALLOW_SHIFT:
        return []
    d = (p1 - p0).Normalize()
    if abs(d.Z) > 0.99:     # vertical conduit: any plan direction is sideways
        normals = [XYZ.BasisX, XYZ.BasisY]
    else:
        normals = [XYZ(-d.Y, d.X, 0).Normalize()]
    return move_candidates(p0, p1, radius, ctx, normals, MAX_SHIFT,
                           lambda v, dist: "Move the conduit {} toward {}".format(inches(dist), compass(v)))


def elevation_candidates(p0, p1, radius, ctx):
    """Raising or lowering the whole conduit (not offered for vertical conduit)."""
    if ELEVATION_MODE == "never" or abs((p1 - p0).Normalize().Z) > 0.99:
        return []
    return move_candidates(p0, p1, radius, ctx, [XYZ.BasisZ], MAX_ELEV_CHANGE,
                           lambda v, dist: "{} the whole conduit {}".format(
                               "Raise" if v.Z > 0 else "Lower", inches(dist)))


def majority_lifts(p0, p1, radius, ctx, before_self):
    """Elevation changes that would clear more than half of the conduit's clashes without adding any,
    most clashes cleared first, then the smallest move: (vector, description)."""
    if abs((p1 - p0).Normalize().Z) > 0.99:
        return []
    found = []
    steps = int(math.floor(MAX_ELEV_CHANGE / SHIFT_STEP + 1e-6))
    for k in range(1, steps + 1):
        for sign in (1.0, -1.0):
            v = XYZ(0, 0, sign * k * SHIFT_STEP)
            hits = path_hits([p0 + v, p1 + v], radius + FIX_CLEARANCE, ctx)
            if hits is None or not hits <= before_self:
                continue
            cleared = len(before_self) - len(hits)
            if 2 * cleared > len(before_self):
                found.append((len(hits), k, v, "{} the whole conduit {} (clears {} of its {} clashes)".format(
                    "Raise" if sign > 0 else "Lower", inches(k * SHIFT_STEP), cleared, len(before_self))))
    found.sort(key=lambda f: (f[0], f[1]))
    return [(v, desc) for _, _, v, desc in found[:MAX_SHIFT_TRIES]]


def jog_angles():
    """Vertical jog angles allowed (degrees, multiples of 5), smallest first."""
    def five(a):
        return max(5, min(90, int(round(float(a) / 5.0)) * 5))
    lo, hi = five(V_JOG_MIN_ANGLE), five(V_JOG_MAX_ANGLE)
    if lo > hi:
        lo, hi = hi, lo
    return list(range(lo, hi + 1, 5))


def jog_candidates(p0, p1, radius, box, ctx):
    """Jogs around the clashing element that look clear, smallest bend angle first, then shortest:
    (points, description).
    Vertical jogs (saddles) use the smallest allowed angle whose saddle is no longer than
    MAX_SADDLE_LENGTH; if none fits within that length, the shortest saddle that fits is used.
    The offset is only as large as the clearance needs. Horizontal jogs use 90 degree bends."""
    axis = p1 - p0
    length = axis.GetLength()
    d = axis.Normalize()
    if abs(d.Z) > 0.01 or not box:
        return []
    n = XYZ(-d.Y, d.X, 0).Normalize()
    ts, ss, zs = [], [], []
    for c in box:
        v = XYZ(c[0], c[1], c[2]) - p0
        ts.append(v.DotProduct(d))
        ss.append(v.DotProduct(n))
        zs.append(v.Z)
    gap = radius + FIX_CLEARANCE
    ta = min(ts) - gap - JOG_LEAD      # where the conduit must already be fully offset
    tb = max(ts) + gap + JOG_LEAD
    if tb - ta < JOG_MIN_LEG:          # the offset piece itself must not be too short
        grow_by = (JOG_MIN_LEG - (tb - ta)) / 2.0
        ta, tb = ta - grow_by, tb + grow_by

    def at(t):
        return p0 + d * t

    def at_least(off, smallest):
        return off if abs(off) >= smallest else (smallest if off >= 0 else -smallest)

    found = []   # (angle, saddle length, points, description)
    # horizontal jog, 90 degree bends: out sideways, along, back
    for need in (max(ss) + gap, min(ss) - gap):
        if not ALLOW_H_JOG or ta < JOG_MIN_LEG or tb > length - JOG_MIN_LEG:
            break
        off = at_least(need, JOG_MIN_LEG)
        side = n * off
        pts = [p0, at(ta), at(ta) + side, at(tb) + side, at(tb), p1]
        if path_clear(pts[1:5], radius + FIX_CLEARANCE * 0.5, ctx):
            found.append((90, tb - ta, pts,
                          "Add a horizontal jog (90 degree bends) {} toward {}".format(inches(off), compass(side))))
    # vertical saddle at angle a: each sloped piece covers |off| / tan(a) along the run
    angles = jog_angles() if ALLOW_V_JOG else []
    for need in (max(zs) + gap, min(zs) - gap):
        options = []
        for ang in angles:
            rad = math.radians(ang)
            # the sloped piece must be at least JOG_MIN_LEG long, so very small offsets are raised just enough
            off = at_least(need, JOG_MIN_LEG * math.sin(rad))
            run = 0.0 if ang >= 90 else abs(off) / math.tan(rad)
            t_in, t_out = ta - run, tb + run
            if t_in < JOG_MIN_LEG or t_out > length - JOG_MIN_LEG:
                continue   # needs more straight conduit than this piece has; a steeper angle may fit
            rise = XYZ(0, 0, off)
            options.append((ang, t_out - t_in, off,
                            [p0, at(t_in), at(ta) + rise, at(tb) + rise, at(t_out), p1]))
        short = [o for o in options if o[1] <= MAX_SADDLE_LENGTH]           # smallest angle first
        longer = sorted([o for o in options if o[1] > MAX_SADDLE_LENGTH], key=lambda o: o[1])
        for ang, saddle, off, pts in short + longer:
            if path_clear(pts[1:5], radius + FIX_CLEARANCE * 0.5, ctx):
                found.append((ang, saddle, pts,
                              "Add a vertical saddle ({} degree bends, {} long) {} {} the clashing element".format(
                                  ang, inches(saddle), inches(off), "over" if off > 0 else "under")))
                break      # best option for this direction
    found.sort(key=lambda f: (f[0], f[1]))
    return [(pts, desc) for _, _, pts, desc in found]


def remaining_clashes(elements, ctx, target, before_self):
    """Clashes left on the changed pieces as {(link, link element id): our piece id}. Raises FixFailed
    if the targeted clash is still there or a clash appeared that the conduit didn't have before."""
    left = {}
    for el in elements:
        if el is None:
            continue
        for k in clash_keys(el, ctx):
            left.setdefault(k, eid(el))
    if target in left:
        raise FixFailed("still clashing with the same element")
    if not set(left) <= before_self:
        raise FixFailed("the fix created a new clash")
    return left


def apply_shift(d, conduit, vec, ctx, before_near, target, before_self, carry=None):
    """Move the conduit and check the result. Returns the clashes that remain on it.
    carry = {"move": devices that travel with the conduit, "stay": devices that must not move,
             "watch": other elements whose clashes must not get worse}.
    Raises FixFailed if the result isn't acceptable."""
    carry = carry or {}
    moving = carry.get("move", [])
    staying = carry.get("stay", [])
    joined = connected_count(conduit)
    near = neighbours(conduit) + moving + carry.get("watch", [])
    stay_at = [(dev, location_of(dev)) for dev in staying]
    if moving:
        ElementTransformUtils.MoveElements(d, List[ElementId]([conduit.Id] + [dev.Id for dev in moving]), vec)
    else:
        ElementTransformUtils.MoveElement(d, conduit.Id, vec)
    d.Regenerate()
    if connected_count(conduit) != joined:
        raise FixFailed("the move disconnected the conduit")
    for dev, was in stay_at:
        now = location_of(dev)
        if was is not None and now is not None and max(abs(was[k] - now[k]) for k in range(3)) > 1e-6:
            raise FixFailed("the move dragged a device that has to stay in place")
    left = remaining_clashes([conduit], ctx, target, before_self)
    for nb in near:
        if not clash_keys(nb, ctx) <= before_near.get(eid(nb), set()):
            raise FixFailed("the move pushed a connected element into a clash")
    return left


def apply_jog(d, conduit, pts, ctx, target, before_self):
    """Rebuild the conduit as five pieces through pts with elbows between them. Returns the clashes that
    remain on any piece (other clashes further along the run are left for their own fix). Raises on any problem."""
    p_end = pts[-1]
    far = closest_conn(conduit, p_end)
    old = partners(far)
    for r in old:
        far.DisconnectFrom(r)
    conduit.Location.Curve = Line.CreateBound(pts[0], pts[1])
    try:
        level_id = conduit.ReferenceLevel.Id
    except Exception:
        level_id = conduit.LevelId
    dia = conduit.get_Parameter(BuiltInParameter.RBS_CONDUIT_DIAMETER_PARAM).AsDouble()
    chain = [conduit]
    for i in range(1, len(pts) - 1):
        c = Conduit.Create(d, conduit.GetTypeId(), pts[i], pts[i + 1], level_id)
        p = c.get_Parameter(BuiltInParameter.RBS_CONDUIT_DIAMETER_PARAM)
        if p is not None and not p.IsReadOnly:
            p.Set(dia)
        chain.append(c)
    d.Regenerate()
    made = chain[1:]
    for i in range(len(chain) - 1):
        corner = pts[i + 1]
        made.append(d.Create.NewElbowFitting(closest_conn(chain[i], corner),
                                             closest_conn(chain[i + 1], corner)))
    new_far = closest_conn(chain[-1], p_end)
    for r in old:
        new_far.ConnectTo(r)
    d.Regenerate()
    return remaining_clashes([conduit] + made, ctx, target, before_self)


def attempt(d, fn, args):
    """Run one fix step inside a sub-transaction. Returns its result, or None (rolled back) if it failed."""
    st = SubTransaction(d)
    st.Start()
    try:
        res = fn(*args)
        st.Commit()
        return res
    except Exception:
        try:
            st.RollBack()
        except Exception:
            pass
        return None


def apply_majority_lift(d, conduit, vec, ctx, before_near, before_self, carry):
    """Elevation change that must leave fewer than half of the original clashes."""
    left = apply_shift(d, conduit, vec, ctx, before_near, None, before_self, carry)
    if 2 * (len(before_self) - len(left)) <= len(before_self):
        raise FixFailed("the elevation change did not clear most of the clashes")
    return left


def with_device(desc, carry):
    return desc + " (connected device moved with it)" if carry.get("move") else desc


def fix_single(d, conduit, row, ctx, target, before_self, before_near, side_carry, lift_carry):
    """One clash on the conduit: sideways move, then jogs, with whole-conduit elevation changes before or
    after the jogs as the rules say. Returns (steps, remaining) - steps is empty if nothing worked."""
    curve = conduit.Location.Curve
    p0, p1 = curve.GetEndPoint(0), curve.GetEndPoint(1)
    radius = conduit_radius(conduit)
    move_tries = [(desc, apply_shift, (d, conduit, vec, ctx, before_near, target, before_self, side_carry))
                  for vec, desc in shift_candidates(p0, p1, radius, ctx)]
    lift_tries = [(with_device(desc, lift_carry), apply_shift,
                   (d, conduit, vec, ctx, before_near, target, before_self, lift_carry))
                  for vec, desc in elevation_candidates(p0, p1, radius, ctx)]
    jog_tries = [(desc, apply_jog, (d, conduit, pts, ctx, target, before_self))
                 for pts, desc in jog_candidates(p0, p1, radius, row.link_box, ctx)]
    if ELEVATION_MODE == "before":
        attempts = move_tries + lift_tries + jog_tries
    else:
        attempts = move_tries + jog_tries + lift_tries
    for desc, fn, args in attempts:
        left = attempt(d, fn, args)
        if left is not None:
            return [desc], left
    return [], {}


def fix_multi(d, conduit, row, ctx, before_self, before_near, boxes, side_carry, lift_carry):
    """Several clashes on the conduit:
    1. a sideways move that clears everything (if sideways moves are allowed);
    2. otherwise one elevation change that clears more than half of the clashes;
    3. then a saddle around each clash that is left.
    Returns (steps, remaining) - steps is empty if nothing worked."""
    curve = conduit.Location.Curve
    p0, p1 = curve.GetEndPoint(0), curve.GetEndPoint(1)
    radius = conduit_radius(conduit)
    steps = []
    left = None
    for vec, desc in shift_candidates(p0, p1, radius, ctx):
        left = attempt(d, apply_shift, (d, conduit, vec, ctx, before_near, None, before_self, side_carry))
        if left is not None:
            steps.append(desc)
            break
    if left is None:
        for vec, desc in majority_lifts(p0, p1, radius, ctx, before_self):
            left = attempt(d, apply_majority_lift, (d, conduit, vec, ctx, before_near, before_self, lift_carry))
            if left is not None:
                steps.append(with_device(desc, lift_carry))
                break
    if left is None:
        left = dict((k, row.host_int) for k in before_self)   # nothing moved; every clash is still there

    for key in sorted(left.keys()):
        if key not in left:
            continue   # an earlier saddle already cleared it
        piece = d.GetElement(element_id(left[key]))
        if not isinstance(piece, Conduit):
            continue   # the clash sits on a fitting
        pc = piece.Location.Curve
        for pts, desc in jog_candidates(pc.GetEndPoint(0), pc.GetEndPoint(1), radius, boxes.get(key), ctx):
            res = attempt(d, apply_jog, (d, piece, pts, ctx, key, before_self))
            if res is not None:
                pid = eid(piece)
                for k in [k for k, v in left.items() if v == pid]:
                    del left[k]          # this piece was rebuilt; res says what is left on its parts
                left.update(res)
                steps.append(desc)
                break
    return steps, left


def auto_fix(row, ask):
    """Fix a clashing conduit following the Link Clash - Config rules. Everything happens in one transaction
    (one undo step). Returns a message, or (message, remaining clashes) when the element was retested
    and the statuses of its clashes should be updated."""
    d = doc
    load_fix_rules()
    conduit = d.GetElement(row.host_id)
    if conduit is None:
        return "Element {} no longer exists in this model.".format(row.sel)
    if not isinstance(conduit, Conduit):
        return "Auto Fix only works on straight conduit; element {} is {}.".format(row.sel, row.desc)

    links, _ = loaded_links()   # fresh each time, in case links were reloaded since the check
    ctx = {"links": links, "cats": ElementMulticategoryFilter(List[BuiltInCategory](LINK_CATS)), "cache": {}}
    boxes = clash_boxes(conduit, ctx)
    before_self = set(boxes)
    try:
        target = (row.link, int(row.lid))
    except Exception:
        target = None
    if not before_self:
        return ("Conduit {} no longer clashes with anything in the links.".format(row.sel), {})
    if target not in before_self:
        left = dict((k, row.host_int) for k in before_self)
        return ("Conduit {} no longer clashes with this element.".format(row.sel), left)

    before_near = dict((eid(nb), clash_keys(nb, ctx)) for nb in neighbours(conduit))
    level = abs((conduit.Location.Curve.GetEndPoint(1) - conduit.Location.Curve.GetEndPoint(0)).Normalize().Z) < 0.01
    multi = MAJORITY_ELEVATION and level and len(before_self) >= 2

    # ---- devices joined straight to this conduit ----
    # Sideways moves never take a device along. Elevation changes do only if the user (or the rule) says so.
    devices = connected_devices(conduit)
    side_carry = {"stay": devices}
    lift_carry = {"stay": devices}
    lifts_possible = level and (multi or ELEVATION_MODE != "never")
    if devices and lifts_possible:
        mode = DEVICE_MODE
        if mode == "ask":
            names = "\n".join(u"  {} : {} (id {})".format(*(describe(dev) + (eid(dev),))) for dev in devices)
            choice = alert(
                u"Conduit {} is connected to:\n\n{}\n\nIf Auto Fix raises or lowers this conduit, should the "
                u"device's elevation change with it, or does the device need to remain in place?".format(
                    row.sel, names),
                title="Link Clash - Auto Fix",
                options=["Adjust the device's elevation too", "Device remains in place"])
            if choice is None:
                return "Auto Fix for conduit {} was cancelled.".format(row.sel)
            mode = "move" if choice.startswith("Adjust") else "keep"
        if mode == "move":
            watch = []
            for dev in devices:
                watch += device_conduits(dev, conduit.Id)
            lift_carry = {"move": devices, "watch": watch}
            for el in devices + watch:
                if eid(el) not in before_near:
                    before_near[eid(el)] = clash_keys(el, ctx)

    t = Transaction(d, "Link Clash: Auto Fix")
    t.Start()
    try:
        if multi:
            steps, remaining = fix_multi(d, conduit, row, ctx, before_self, before_near, boxes,
                                         side_carry, lift_carry)
        else:
            steps, remaining = fix_single(d, conduit, row, ctx, target, before_self, before_near,
                                          side_carry, lift_carry)
        if not steps:
            t.RollBack()
            return ("No fix worked for conduit {} within the Link Clash - Config rules: each allowed move or jog either "
                    "still clashed, disconnected the run, did not fit, or could not be built by Revit "
                    "(jogs need a level conduit with room either side of the clashing element).".format(row.sel))
        if ask:
            plan = "\n".join("{}. {}".format(i + 1, st) for i, st in enumerate(steps))
            note = ""
            if remaining:
                note = "\n\n{} of its {} clash(es) would remain.".format(len(remaining), len(before_self))
            ok = alert("Proposed fix for conduit {}:\n\n{}{}\n\nApply it?".format(row.sel, plan, note),
                             title="Link Clash - Auto Fix", yes=True, no=True)
            if not ok:
                t.RollBack()
                return "Auto Fix for conduit {} was not applied.".format(row.sel)
        if t.Commit() != TransactionStatus.Committed:
            return "Revit did not accept the fix for conduit {}; nothing was changed.".format(row.sel)
    except Exception:
        try:
            if t.HasStarted() and not t.HasEnded():
                t.RollBack()
        except Exception:
            pass
        raise
    done = "; then ".join(st[0].lower() + st[1:] for st in steps)
    return ("Fixed conduit {}: {}. Ctrl+Z undoes it (after closing this window).".format(row.sel, done),
            remaining)


GROUP_NONE = "No grouping"
GROUP_HOST = "Our element id"
GROUP_LINK = "Link element id"
FILTER_ALL = "All"
FILTER_OPEN = "Open (New, Active, Reviewed)"


class ResultsWindow(forms.WPFWindow):
    """Modal results window. A Show in 3D or Auto Fix click records the choice and closes the window; the
    script then does the work in Revit's normal context and reopens the window. Status changes need no
    Revit access, so they are saved straight away while the window stays open."""
    def __init__(self, rows, status, ask, selected, show_filter, group):
        forms.WPFWindow.__init__(self, RESULTS_XAML, literal_string=True)
        self.rows = rows
        self.choice = None
        self.ask = ask
        self.show_filter = show_filter
        self.group = group
        self._loading = False

        for g in (GROUP_NONE, GROUP_HOST, GROUP_LINK):
            self.group_combo.Items.Add(g)
        self.group_combo.SelectedItem = group

        for f in [FILTER_ALL, FILTER_OPEN] + STATUSES:
            self.filter_combo.Items.Add(f)
        self.filter_combo.SelectedItem = show_filter
        for st in STATUSES:
            self.bulk_combo.Items.Add(st)
        self.bulk_combo.SelectedItem = "Reviewed"

        self.refresh(selected)
        self.ask_check.IsChecked = ask
        self.clash_list.AddHandler(Button.ClickEvent, RoutedEventHandler(self.on_button))
        self.clash_list.AddHandler(Selector.SelectionChangedEvent,
                                   SelectionChangedEventHandler(self.on_row_status))
        self.filter_combo.SelectionChanged += self.on_filter
        self.group_combo.SelectionChanged += self.on_group
        self.bulk_btn.Click += self.on_bulk
        self.status_text.Text = status

    # ---- list ----
    def visible_rows(self):
        f = self.show_filter
        if f == FILTER_ALL:
            return list(self.rows)
        if f == FILTER_OPEN:
            return [r for r in self.rows if r.status in OPEN_STATUSES]
        return [r for r in self.rows if r.status == f]

    def refresh(self, selected=None):
        """Rebuild the list (new rows, so every status box shows the saved value)."""
        self._loading = True
        try:
            shown = self.visible_rows()
            if self.group == GROUP_LINK:
                shown.sort(key=lambda r: (r.link, r.lid, r.host_int))
            else:
                shown.sort(key=lambda r: (r.host_int, r.link, r.lid))
            self.clash_list.ItemsSource = List[object](shown)
            try:
                view = CollectionViewSource.GetDefaultView(self.clash_list.ItemsSource)
                view.GroupDescriptions.Clear()
                prop = {GROUP_HOST: "group_host", GROUP_LINK: "group_link"}.get(self.group)
                if prop:
                    view.GroupDescriptions.Add(PropertyGroupDescription(prop))
            except Exception:
                pass   # grouping unavailable: the list is still sorted so groups sit together
            if selected is not None and selected in shown:
                self.clash_list.SelectedItem = selected
                try:
                    self.clash_list.ScrollIntoView(selected)
                except Exception:
                    pass
            counts = dict((st, 0) for st in STATUSES)
            for r in self.rows:
                counts[r.status] = counts.get(r.status, 0) + 1
            self.count_text.Text = "Showing {} of {}   |   {}".format(
                len(shown), len(self.rows), "   ".join("{}: {}".format(st, counts[st]) for st in STATUSES))
        finally:
            self._loading = False

    def on_filter(self, sender, args):
        self.show_filter = self.filter_combo.SelectedItem or FILTER_ALL
        self.refresh()

    def on_group(self, sender, args):
        self.group = self.group_combo.SelectedItem or GROUP_NONE
        self.refresh()

    # ---- status ----
    def on_row_status(self, sender, args):
        combo = args.OriginalSource
        if self._loading or not isinstance(combo, ComboBox):
            return
        row = getattr(combo, "DataContext", None)
        new = combo.SelectedItem
        if not isinstance(row, ClashRow) or new not in STATUSES or new == row.status:
            return
        args.Handled = True
        self.apply_status([row], new)

    def on_bulk(self, sender, args):
        picked = [r for r in self.clash_list.SelectedItems if isinstance(r, ClashRow)]
        if not picked:
            self.status_text.Text = "Highlight one or more rows first (Ctrl or Shift click to pick several)."
            return
        self.apply_status(picked, self.bulk_combo.SelectedItem)

    def apply_status(self, rows, new):
        ok = set_status(rows, new)
        self.status_text.Text = ("{} clash(es) set to {}.".format(len(rows), new) if ok else
                                 "Status changed for this session, but the status file could not be saved. "
                                 "Check that the STATUS_DIR folder exists and you can write to it.")
        # rebuild after the current event finishes, so the combo that raised it isn't replaced mid-event
        keep = rows[0] if len(rows) == 1 else None
        self.Dispatcher.BeginInvoke(System.Action(lambda: self.refresh(keep)))

    # ---- buttons ----
    def on_button(self, sender, args):
        btn = args.OriginalSource
        if not isinstance(btn, Button) or btn.Content not in ("Show in 3D", "Auto Fix"):
            return   # e.g. the drop-down arrow inside a status box
        row = getattr(btn, "DataContext", None)
        if not isinstance(row, ClashRow):
            return
        self.ask = bool(self.ask_check.IsChecked)
        self.choice = ("fix" if btn.Content == "Auto Fix" else "show", row)
        self.Close()


def results_loop(rows, summary=""):
    """Show the results window until it is closed or Show in 3D ends the tool."""
    status = summary + ("{} clash(es). 'Show in 3D' closes this window and boxes the element "
              "(run Link Clash with nothing selected to reopen these results). "
              "'Auto Fix' shifts or jogs a clashing conduit.".format(len(rows)))
    apply_statuses(rows)
    load_fix_rules()
    ask = ASK_BEFORE_FIX
    group = GROUP_NONE
    selected = None
    show_filter = FILTER_ALL
    while True:
        w = ResultsWindow(rows, status, ask, selected, show_filter, group)
        w.ShowDialog()
        group = w.group
        ask = w.ask
        show_filter = w.show_filter
        if w.choice is None:
            return
        action, row = w.choice
        selected = row
        if action == "show":
            posted, status = show_in_3d(row)
            if posted:
                return
            continue
        fixed_id = row.host_int
        try:
            res = auto_fix(row, ask)
        except Exception as ex:
            res = "Could not fix this clash: {}".format(ex)
        if isinstance(res, tuple):
            status, remaining = res
            n_resolved, n_still = update_after_fix(rows, fixed_id, remaining)
            save_results(rows)
            status += " Retest: {} clash(es) on this element resolved, {} still clashing.".format(
                n_resolved, n_still)
        else:
            status = res


def print_report(rows, notes):
    """The clash table in pyRevit's output window (only when PRINT_REPORT is on, or the window is off)."""
    output = script.get_output()
    output.print_md("# Link Clash")
    for n in notes:
        output.print_md(n)
    table = [[r.status, output.linkify(r.host_id), r.desc, r.link, r.cat, r.type, r.lid, r.overlap]
             for r in rows]
    output.print_table(
        table_data=table,
        columns=["Status", "Selected element", "Description", "Link", "Clashes with", "Type",
                 "Link element id", "Overlap (cu in)"])


def main():
    if RESULTS_WINDOW and not list(uidoc.Selection.GetElementIds()):
        last = load_results()
        if last:
            choice = alert("Reopen the last clash results for this model ({} clash(es)), "
                                 "or pick elements for a new check?".format(len(last)),
                                 title="Link Clash",
                                 options=["Reopen last results", "New check"])
            if choice is None:
                return
            if choice == "Reopen last results":
                results_loop(last)
                return

    elems = get_selection()
    if not elems:
        alert("Nothing selected to test.")
        return

    links, unloaded = loaded_links()
    if not links:
        alert("No loaded Revit links found in this model.")
        return

    cat_filter = ElementMulticategoryFilter(List[BuiltInCategory](LINK_CATS))
    solid_cache = {}
    results = []       # (selected element, link title, link element, volume)
    no_geometry = 0
    cancelled = False

    with forms.ProgressBar(title="Clash check: {value} of {max_value} elements", cancellable=True) as pb:
        for n, el in enumerate(elems):
            if pb.cancelled:
                cancelled = True
                break
            solids = element_solids(el)
            if not solids:
                no_geometry += 1
            else:
                for title, le, vol, box in check_element(el, solids, links, cat_filter, solid_cache):
                    results.append((el, title, le, vol, box))
            pb.update_progress(n + 1, len(elems))

    # ---- report ----
    clashing_ids = []
    seen = set()
    for el, _, _, _, _ in results:
        if eid(el) not in seen:
            seen.add(eid(el))
            clashing_ids.append(el.Id)

    notes = ["{} clash(es) on {} of {} selected element(s), tested against {} link(s).".format(
        len(results), len(clashing_ids), len(elems), len(links))]
    if cancelled:
        notes.append("Check cancelled before finishing.")
    if no_geometry:
        notes.append("{} selected element(s) had no solid geometry and were skipped.".format(no_geometry))
    if unloaded:
        notes.append("Links not loaded (not tested): {}.".format(", ".join(sorted(set(unloaded)))))
    if len(results) > MAX_ROWS:
        notes.append("Showing the first {} of {} clashes.".format(MAX_ROWS, len(results)))

    if not results:
        alert("No clashes found.\n\n" + "\n".join(notes), title="Link Clash")
        return

    results.sort(key=lambda r: (eid(r[0]), r[1], eid(r[2])))
    rows = []
    for el, title, le, vol, box in results[:MAX_ROWS]:
        scat, sname = describe(el)
        lcat, lname = describe(le)
        overlap = "{:.1f}".format(vol * 1728.0) if vol is not None else "n/a"
        rows.append(ClashRow(el.Id, u"{} - {}".format(scat, sname), title, lcat, lname, eid(le),
                             overlap, box))
    apply_statuses(rows)
    reactivate(rows)   # a clash marked Resolved that was found again becomes Active
    save_results(rows)
    if SELECT_CLASHING:
        uidoc.Selection.SetElementIds(List[ElementId](clashing_ids))

    # pyRevit's output window only opens when something is printed, so it stays closed unless asked for
    if PRINT_REPORT or not RESULTS_WINDOW:
        print_report(rows, notes)
    if RESULTS_WINDOW:
        results_loop(rows, " ".join(notes) + " ")

main()
