# -*- coding: utf-8 -*-
# Line Nuke script - version v3
__title__ = "Line\nNuke v3"
__doc__ = ("Creates the standard line styles, then merges matching line styles into them.\n\n"
           "Step 1 creates 15 Solid line styles named Detail Line - <Color> - <Size> "
           "(Black, Blue, Red, Green, Magenta; Thin = weight 1, Medium = weight 3, Thick = weight 6). "
           "One that already exists is corrected to that color, weight and pattern.\n\n"
           "Step 2 finds every other line style with the same color, weight and pattern as a standard "
           "style, moves its lines onto the standard style and deletes it.\n\n"
           "The second mode also merges all remaining duplicate line styles and renames them "
           "Color - Weight - Pattern.\n\n"
           "Built-in styles (<Thin Lines>, Wide Lines ...) are never changed. You choose styles to leave "
           "alone and confirm a preview first; answering No at the preview undoes everything, and the "
           "whole run is a single Undo.")

from collections import defaultdict

from pyrevit import revit, DB, forms, script

doc = revit.doc
output = script.get_output()
GST = DB.GraphicsStyleType.Projection
TITLE = "Line Nuke"

# --- standard styles -------------------------------------------------------
STD_PREFIX = "Detail Line"
STD_COLORS = [                      # Title Case names, exact RGB
    ("Black", (0, 0, 0)),
    ("Blue", (0, 0, 255)),
    ("Red", (255, 0, 0)),
    ("Green", (0, 255, 0)),
    ("Magenta", (255, 0, 255)),
]
STD_WEIGHTS = [(1, "Thin"), (3, "Medium"), (6, "Thick")]

COLOR_NAMES = {
    (0, 0, 0): "Black", (255, 255, 255): "White", (255, 0, 0): "Red",
    (0, 255, 0): "Green", (0, 0, 255): "Blue", (255, 255, 0): "Yellow",
    (0, 255, 255): "Cyan", (255, 0, 255): "Magenta", (128, 128, 128): "Gray",
    (192, 192, 192): "Light Gray", (255, 165, 0): "Orange",
}
BAD_CHARS = '\\:{}[]|;<>?`~'       # not allowed in Revit names
SOLID_KEY = -1

OPT_STD = "Create standard styles + merge matching lines into them"
OPT_ALL = "Same as above, AND consolidate + rename all other line styles"


# --- helpers ---------------------------------------------------------------
def id_val(eid):
    try:
        return eid.Value          # Revit 2024+
    except AttributeError:
        return eid.IntegerValue   # older versions


def clean(s):
    return u"".join(c for c in s if c not in BAD_CHARS).strip()


def get_solid_id():
    try:
        return DB.LinePatternElement.GetSolidPatternId()
    except Exception:
        pass
    for lp in DB.FilteredElementCollector(doc).OfClass(DB.LinePatternElement):
        if lp.Name == "Solid":
            return lp.Id
    return DB.ElementId(-3000010)


SOLID = get_solid_id()


def is_solid(pid):
    return pid is None or pid == DB.ElementId.InvalidElementId or pid == SOLID


def color_rgb(cat):
    c = cat.LineColor
    if c is None or not c.IsValid:
        return (0, 0, 0)          # unset colors display as black
    return (int(c.Red), int(c.Green), int(c.Blue))


def color_name(rgb):
    return COLOR_NAMES.get(rgb, "RGB({},{},{})".format(*rgb))


def weight(cat):
    w = cat.GetLineWeight(GST)
    return int(w) if w is not None else 1


def pattern_id(cat):
    return cat.GetLinePatternId(GST)


def pattern_name(pid):
    if is_solid(pid):
        return "Solid"
    el = doc.GetElement(pid)
    return (clean(el.Name) or "Solid") if el is not None else "Solid"


def key_of(cat):
    pid = pattern_id(cat)
    return (color_rgb(cat), weight(cat), SOLID_KEY if is_solid(pid) else id_val(pid))


def generic_name(cat):
    return u"{} - {} - {}".format(color_name(color_rgb(cat)), weight(cat), pattern_name(pattern_id(cat)))


def is_builtin(cat):
    return id_val(cat.Id) < 0 or cat.Name.startswith("<")


def apply_look(cat, rgb, w, pid):
    cat.LineColor = DB.Color(rgb[0], rgb[1], rgb[2])
    cat.SetLineWeight(w, GST)
    cat.SetLinePatternId(SOLID if is_solid(pid) else pid, GST)


def try_rename(cat, name):
    """Rename in place. False when this Revit version doesn't allow it."""
    try:
        cat.Name = name
    except Exception:
        return False
    return cat.Name == name


def lines_category():
    return doc.Settings.Categories.get_Item(DB.BuiltInCategory.OST_Lines)


class Tx(object):
    """Transaction that commits on success and rolls back on an error."""
    def __init__(self, name):
        self.t = DB.Transaction(doc, name)

    def __enter__(self):
        self.t.Start()
        return self.t

    def __exit__(self, etype, evalue, tb):
        if etype is None:
            self.t.Commit()
        elif self.t.HasStarted() and not self.t.HasEnded():
            self.t.RollBack()
        return False


STD_SPECS = []   # (name, (rgb, weight, SOLID_KEY))
for _cname, _rgb in STD_COLORS:
    for _w, _wname in STD_WEIGHTS:
        STD_SPECS.append((u"{} - {} - {}".format(STD_PREFIX, _cname, _wname), (_rgb, _w, SOLID_KEY)))


# --- the tool --------------------------------------------------------------
def run(also_others):
    """Returns True to keep the changes, False to undo them all."""
    # STEP 1: create / correct the standard styles
    created = corrected = 0
    std_by_key = {}                 # look key -> standard style id value
    with Tx("Create standard line styles"):
        lines_cat = lines_category()
        by_lower = dict((c.Name.lower(), c) for c in lines_cat.SubCategories)
        for name, key in STD_SPECS:
            cat = by_lower.get(name.lower())
            if cat is None:
                cat = doc.Settings.Categories.NewSubcategory(lines_cat, name)
                created += 1
            else:
                if key_of(cat) != key:
                    corrected += 1
                if cat.Name != name:
                    try_rename(cat, name)       # fix capitalisation where Revit allows
            apply_look(cat, key[0], key[1], SOLID)
            std_by_key[key] = id_val(cat.Id)
        doc.Regenerate()
    std_ids = set(std_by_key.values())
    std_summary = "Standard styles: {} created, {} corrected.".format(created, corrected)

    # collect line styles and the lines on each (one pass over the model)
    lines_cat = lines_category()
    subcats = [c for c in lines_cat.SubCategories]
    gs_of = {}                      # style id value -> GraphicsStyle
    for c in subcats:
        gs = c.GetGraphicsStyle(GST)
        if gs is not None:
            gs_of[id_val(c.Id)] = gs

    lines_on = defaultdict(list)    # graphics style id value -> [CurveElement]
    for ce in DB.FilteredElementCollector(doc).OfClass(DB.CurveElement):
        try:
            ls = ce.LineStyle
        except Exception:
            continue
        if ls is not None:
            lines_on[id_val(ls.Id)].append(ce)

    def gs_key(cat):
        gs = gs_of.get(id_val(cat.Id))
        return id_val(gs.Id) if gs is not None else None

    def usage(cat):
        return len(lines_on.get(gs_key(cat), ()))

    # exclusions (the standard styles can't be excluded)
    editable = [c for c in subcats if not is_builtin(c)]
    excludable = [c for c in editable if id_val(c.Id) not in std_ids]
    excluded_ids = set()
    if excludable:
        label_to_cat = {}
        for c in excludable:
            label_to_cat[u"{}  |  {}  |  {} lines".format(c.Name, generic_name(c), usage(c))] = c
        picked = forms.SelectFromList.show(
            sorted(label_to_cat.keys()),
            title="Line styles to EXCLUDE (leave untouched) - cancel/none to include all",
            multiselect=True) or []
        excluded_ids = set(id_val(label_to_cat[l].Id) for l in picked)

    # group by identical color + weight + pattern
    groups = defaultdict(list)
    for c in editable:
        if id_val(c.Id) not in excluded_ids:
            groups[key_of(c)].append(c)

    plan = []                       # (keeper, [duplicates], keeper_is_standard)
    for k, g in groups.items():
        std = [c for c in g if id_val(c.Id) == std_by_key.get(k)]
        if std:
            plan.append((std[0], [c for c in g if c.Id != std[0].Id], True))
        elif also_others:
            ranked = sorted(g, key=lambda c: (-usage(c), c.Name))
            plan.append((ranked[0], ranked[1:], False))

    # final names for the non-standard keepers (unique, ignoring case)
    taken = set(c.Name.lower() for c in subcats
                if is_builtin(c) or id_val(c.Id) in excluded_ids or id_val(c.Id) in std_ids)
    taken.update(n.lower() for n, _ in STD_SPECS)
    rename_plan = []                # (cat, old, new)
    for keep, dups, is_std in sorted(plan, key=lambda p: p[0].Name):
        if is_std:
            continue
        base = generic_name(keep)
        name, i = base, 2
        while name.lower() in taken:
            name = u"{} {}".format(base, i)
            i += 1
        taken.add(name.lower())
        rename_plan.append((keep, keep.Name, name))
    todo = [(c, old, new) for c, old, new in rename_plan if old != new]

    n_merge = sum(len(d) for _, d, _ in plan)
    if n_merge == 0 and not todo:
        forms.alert(std_summary + "\nNo existing line styles needed merging or renaming.", title=TITLE)
        return True

    # preview + confirm
    new_name_of = dict((id_val(c.Id), n) for c, o, n in rename_plan)
    rows = []
    for keep, dups, is_std in plan:
        final = new_name_of.get(id_val(keep.Id), keep.Name)
        if not dups and final == keep.Name:
            continue
        rows.append([keep.Name, final, u", ".join(d.Name for d in dups) if dups else u"-",
                     usage(keep) + sum(usage(d) for d in dups)])
    output.print_md("## Line style merge preview\n" + std_summary)
    output.print_table(table_data=sorted(rows, key=lambda r: r[1]),
                       columns=["Kept style (current name)", "Final name", "Merged in (deleted)", "Total lines"])
    if not forms.alert(
            "{}\n\nMerge {} duplicate style(s) and rename {} style(s)?\n(Full list is in the output window.)\n\n"
            "No undoes everything, including the standard styles just created."
            .format(std_summary, n_merge, len(todo)),
            title=TITLE, yes=True, no=True):
        return False

    # apply
    changed = deleted = renamed = 0
    problems = []                   # (item, step, detail)

    def move_lines(cat, to_gs):
        """Moves every line on cat's style to to_gs. Returns (moved, all_moved)."""
        src = gs_key(cat)
        dst = id_val(to_gs.Id)
        moved, stuck, first_error = 0, [], ""
        for ce in lines_on.pop(src, []):
            try:
                ce.LineStyle = to_gs
                lines_on[dst].append(ce)
                moved += 1
            except Exception as e:
                stuck.append(ce)
                first_error = first_error or str(e)
        if stuck:
            lines_on[src] = stuck
            problems.append((cat.Name, "move lines",
                             u"{} line(s) could not be moved, so the style was kept. {}".format(
                                 len(stuck), first_error)))
        return moved, not stuck

    with Tx("Merge line styles"):
        # 1. move lines off the duplicates, then delete the duplicates that emptied
        for keep, dups, is_std in plan:
            keep_gs = gs_of.get(id_val(keep.Id))
            if keep_gs is None:
                continue
            for d in dups:
                d_name = d.Name
                moved, all_moved = move_lines(d, keep_gs)
                changed += moved
                if not all_moved:
                    continue        # deleting it would reset the lines still on it
                try:
                    doc.Delete(d.Id)
                    deleted += 1
                except Exception as e:
                    problems.append((d_name, "delete", str(e)))

        # 2. rename the other kept styles
        if todo:
            in_place = True
            for c, old, new in todo:        # temporary names first, so swapped names never collide
                if not try_rename(c, u"__tmp_{}".format(id_val(c.Id))):
                    in_place = False
                    break
            if in_place:
                for c, old, new in todo:
                    if try_rename(c, new):
                        renamed += 1
                    else:
                        try_rename(c, old)
                        problems.append((old, "rename", u"Revit refused the name '{}'.".format(new)))
            else:
                # This Revit can't rename a line style in place: make a new style with the new
                # name and the same look, move the lines over, delete the old one.
                for c, old, new in todo:
                    if c.Name != old:
                        try_rename(c, old)
                cats = doc.Settings.Categories
                lines_cat = lines_category()
                names_now = set(c.Name.lower() for c in lines_cat.SubCategories)
                pending = list(todo)
                progress = True
                while pending and progress:
                    progress = False
                    for item in list(pending):
                        c, old, new = item
                        if new.lower() in names_now:
                            continue        # held by a style still waiting for its own new name
                        pending.remove(item)
                        progress = True
                        try:
                            new_cat = cats.NewSubcategory(lines_cat, new)
                            apply_look(new_cat, color_rgb(c), weight(c), pattern_id(c))
                            doc.Regenerate()
                            names_now.add(new.lower())
                            moved, all_moved = move_lines(c, new_cat.GetGraphicsStyle(GST))
                            if all_moved:
                                doc.Delete(c.Id)
                                names_now.discard(old.lower())
                            renamed += 1
                        except Exception as e:
                            problems.append((old, "rename", str(e)))
                for c, old, new in pending:
                    problems.append((old, "rename", u"The name '{}' is already in use.".format(new)))

    msg = ("{}\nMoved {} lines.\nDeleted {} line styles.\nRenamed {} line styles.\nExcluded styles: {}"
           .format(std_summary, changed, deleted, renamed, len(excluded_ids)))
    if problems:
        output.print_md("## Problems")
        output.print_table(table_data=[list(p) for p in problems], columns=["Style", "Step", "Detail"])
        msg += "\n{} problem(s) - see the output window.".format(len(problems))
    forms.alert(msg, title=TITLE)
    return True


def main():
    mode = forms.CommandSwitchWindow.show(
        [OPT_STD, OPT_ALL],
        message="Creates 15 'Detail Line - Color - Size' styles (Black/Blue/Red/Green/Magenta x "
                "Thin/Medium/Thick), then merges matching existing styles into them.")
    if not mode:
        return
    tg = DB.TransactionGroup(doc, "Line Nuke")
    tg.Start()
    try:
        keep = run(mode == OPT_ALL)
    except Exception:
        if tg.HasStarted() and not tg.HasEnded():
            tg.RollBack()
        raise
    if keep:
        tg.Assimilate()
    else:
        tg.RollBack()
        forms.alert("Cancelled. Nothing was changed.", title=TITLE)


main()
