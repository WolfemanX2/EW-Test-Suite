# -*- coding: utf-8 -*-
# Consolidate Text Styles script - version v5
__title__ = "Consolidate\nText Styles v5"
__doc__ = ("Merges text styles that have the same text size into one style.\n\n"
           "Text styles are grouped by size (within a tolerance you enter as a fraction or decimal of an "
           "inch). Each group is merged into its most-used style: text notes and schedules using the "
           "other styles are switched to it and the other styles are deleted. The kept style's size is "
           "rounded to the nearest 1/64\" and it is renamed <size> <font> <modifiers>, "
           "e.g. 1/8\" Arial Bold.\n\n"
           "Only the size is compared, so text in a merged style takes on the kept style's font and "
           "formatting. You choose styles to leave alone and confirm a preview first. "
           "The whole run is a single Undo.")

from collections import defaultdict

from pyrevit import revit, DB, forms, script
from ew_common import eid_int as id_val     # ElementId number helper (lib/ew_common.py)

doc = revit.doc
output = script.get_output()
TITLE = "Consolidate Text Styles"
DEFAULT_TOLERANCE = "1/128"  # inches, fraction or decimal
ROUND_DENOM = 64             # merged styles are rounded to the nearest 1/64"
BIP = DB.BuiltInParameter
SCHEDULE_TEXT_PROPS = ("BodyTextTypeId", "HeaderTextTypeId", "TitleTextTypeId")


# --- helpers ---------------------------------------------------------------


def type_name(t):
    return t.get_Parameter(BIP.SYMBOL_NAME_PARAM).AsString()


def set_type_name(t, name):
    """The type name parameter is read-only; the Name property is the one that can be set."""
    try:
        t.Name = name
    except Exception:
        DB.Element.Name.__set__(t, name)
    return type_name(t) == name


def height_in(t):
    return t.get_Parameter(BIP.TEXT_SIZE).AsDouble() * 12.0     # stored in feet


def round_height(h):
    """Nearest 1/64" (never rounds a real size down to zero)."""
    n = int(round(h * ROUND_DENOM))
    return n / float(ROUND_DENOM) if n else h


def parse_inches(s):
    """Accepts '1/64', '0 1/64', '1 1/2', '0.005', with optional inch marks."""
    s = s.replace('"', '').replace("in", "").strip()
    total = 0.0
    for part in s.split():
        if "/" in part:
            a, b = part.split("/")
            total += float(a) / float(b)
        else:
            total += float(part)
    return abs(total)


def frac_str(h):
    """Inches -> a fraction when it is a clean 64th, otherwise a decimal."""
    n, d = int(round(h * 64)), 64
    if abs(n / 64.0 - h) > 0.0005:
        return '{}"'.format(('%.4f' % h).rstrip("0").rstrip("."))
    while n != 0 and n % 2 == 0 and d > 1:
        n //= 2
        d //= 2
    whole, rem = n // d, n % d
    if rem == 0:
        return '{}"'.format(whole)
    if whole == 0:
        return '{}/{}"'.format(rem, d)
    return '{} {}/{}"'.format(whole, rem, d)


def is_on(t, bip):
    p = t.get_Parameter(bip)
    return p is not None and p.AsInteger() == 1


def target_name(t, h):
    """e.g.  1/8" Arial Bold Italic Underline"""
    parts = [frac_str(h), t.get_Parameter(BIP.TEXT_FONT).AsString()]
    if is_on(t, BIP.TEXT_STYLE_BOLD):
        parts.append("Bold")
    if is_on(t, BIP.TEXT_STYLE_ITALIC):
        parts.append("Italic")
    if is_on(t, BIP.TEXT_STYLE_UNDERLINE):
        parts.append("Underline")
    return u" ".join(parts)


# --- the tool --------------------------------------------------------------
def main():
    # tolerance
    tol_str = forms.ask_for_string(
        default=DEFAULT_TOLERANCE,
        prompt="Height tolerance in inches (fraction or decimal, e.g. 1/64, 1/128, 0.005).\n"
               "Styles whose heights are within this of each other count as the same height:",
        title=TITLE)
    if tol_str is None:
        return
    try:
        tol = parse_inches(tol_str)
    except Exception:
        tol = parse_inches(DEFAULT_TOLERANCE)
        forms.alert("Couldn't read that tolerance; using {}\".".format(DEFAULT_TOLERANCE), title=TITLE)

    # collect styles and the notes on each (one pass over the model)
    types = list(DB.FilteredElementCollector(doc).OfClass(DB.TextNoteType).ToElements())
    name_of = dict((id_val(t.Id), type_name(t)) for t in types)
    h_of = dict((id_val(t.Id), height_in(t)) for t in types)

    notes_on = defaultdict(list)    # type id value -> [TextNote]
    note_ids = set()
    for tn in DB.FilteredElementCollector(doc).OfClass(DB.TextNote):
        notes_on[id_val(tn.GetTypeId())].append(tn)
        note_ids.add(id_val(tn.Id))

    def usage(t):
        return len(notes_on.get(id_val(t.Id), ()))

    # exclusions
    label_to_type = {}
    for t in types:
        tid = id_val(t.Id)
        label = u"{}  |  {} ({:.4f}\")  |  {} notes".format(name_of[tid], frac_str(h_of[tid]), h_of[tid], usage(t))
        label_to_type[label] = t
    picked = forms.SelectFromList.show(
        sorted(label_to_type.keys()),
        title="Text styles to EXCLUDE (leave untouched) - cancel/none to include all",
        multiselect=True) or []
    excluded_ids = set(id_val(label_to_type[l].Id) for l in picked)

    def rank(g):                    # most-used first, ties alphabetical
        return sorted(g, key=lambda t: (-usage(t), name_of[id_val(t.Id)]))

    # group by height within the tolerance (compared to the smallest style in the group)
    candidates = sorted((t for t in types if id_val(t.Id) not in excluded_ids),
                        key=lambda t: h_of[id_val(t.Id)])
    by_tol = []
    for t in candidates:
        h = h_of[id_val(t.Id)]
        if by_tol and h - h_of[id_val(by_tol[-1][0].Id)] <= tol:
            by_tol[-1].append(t)
        else:
            by_tol.append([t])

    # groups whose kept style rounds to the same 1/64" size become one group,
    # so two kept styles never end up with the same size
    by_size = defaultdict(list)
    for g in by_tol:
        by_size[round_height(h_of[id_val(rank(g)[0].Id)])].extend(g)

    plan = []                       # (keeper, [styles merged into it], final height)
    for final_h, g in by_size.items():
        ranked = rank(g)
        if len(ranked) > 1:
            plan.append((ranked[0], ranked[1:], final_h))
    if not plan:
        forms.alert("Nothing to merge - no height group has more than one style.", title=TITLE)
        return

    # final names (unique, ignoring case)
    merging_ids = set(id_val(t.Id) for keep, merge, _ in plan for t in [keep] + merge)
    taken = set(n.lower() for tid, n in name_of.items() if tid not in merging_ids)
    new_name = {}                   # keeper id value -> name
    for keep, merge, final_h in sorted(plan, key=lambda p: p[2]):
        base = target_name(keep, final_h)
        name, i = base, 2
        while name.lower() in taken:
            name = u"{} {}".format(base, i)
            i += 1
        taken.add(name.lower())
        new_name[id_val(keep.Id)] = name

    # preview + confirm
    rows = []
    for keep, merge, final_h in sorted(plan, key=lambda p: p[2]):
        kid = id_val(keep.Id)
        old_h = h_of[kid]
        rows.append([name_of[kid], new_name[kid],
                     frac_str(final_h) if abs(final_h - old_h) < 1e-9
                     else u'{:.4f}" -> {}'.format(old_h, frac_str(final_h)),
                     u", ".join(name_of[id_val(t.Id)] for t in merge),
                     usage(keep) + sum(usage(t) for t in merge)])
    output.print_md("## Text style merge preview")
    output.print_table(table_data=rows,
                       columns=["Kept style (current name)", "New name", "Size", "Merged in (deleted)", "Total notes"])
    n_merge = sum(len(m) for _, m, _ in plan)
    if not forms.alert("Merge {} text style(s) into {} style(s)?\n(Full list is in the output window.)"
                       .format(n_merge, len(plan)), title=TITLE, yes=True, no=True):
        return

    # apply
    changed = deleted = resized = renamed = schedules = 0
    problems = []                   # (style, step, detail)
    remap = {}                      # merged type id value -> keeper ElementId
    for keep, merge, _ in plan:
        for t in merge:
            remap[id_val(t.Id)] = keep.Id

    with revit.Transaction(TITLE):
        # 1. move text notes onto the kept styles
        stuck_types = set()
        for old_id, keep_id in remap.items():
            stuck, first_error = 0, ""
            for tn in notes_on.get(old_id, ()):
                try:
                    tn.ChangeTypeId(keep_id)
                    changed += 1
                except Exception as e:
                    stuck += 1
                    first_error = first_error or str(e)
            if stuck:
                stuck_types.add(old_id)
                problems.append((name_of[old_id], "move notes",
                                 u"{} note(s) could not be moved, so the style was kept. {}".format(
                                     stuck, first_error)))

        # 2. schedules that use a merged style for their title, header or body text
        for vs in DB.FilteredElementCollector(doc).OfClass(DB.ViewSchedule):
            for prop in SCHEDULE_TEXT_PROPS:
                try:
                    keep_id = remap.get(id_val(getattr(vs, prop)))
                    if keep_id is not None:
                        setattr(vs, prop, keep_id)
                        schedules += 1
                except Exception:
                    pass

        # 3. delete the merged styles. Deleting a style that is still in use would delete its
        #    text notes with it, so a delete that takes any note along is undone.
        for keep, merge, _ in plan:
            for t in merge:
                tid = id_val(t.Id)
                if tid in stuck_types:
                    continue
                st = DB.SubTransaction(doc)
                st.Start()
                try:
                    gone = doc.Delete(t.Id)
                    if any(id_val(i) in note_ids for i in gone):
                        st.RollBack()
                        problems.append((name_of[tid], "delete", "Still used by text notes, so it was kept."))
                    else:
                        st.Commit()
                        deleted += 1
                except Exception as e:
                    if not st.HasEnded():
                        st.RollBack()
                    problems.append((name_of[tid], "delete", str(e)))

        # 4. round the kept styles to the nearest 1/64" and rename them
        to_rename = []
        for keep, merge, final_h in plan:
            kid = id_val(keep.Id)
            if abs(final_h - h_of[kid]) > 1e-9:
                try:
                    keep.get_Parameter(BIP.TEXT_SIZE).Set(final_h / 12.0)
                    resized += 1
                except Exception as e:
                    problems.append((name_of[kid], "round size", str(e)))
            if new_name[kid] != name_of[kid]:
                try:                # temporary names first, so swapped names never collide
                    set_type_name(keep, u"__tmp_{}".format(kid))
                    to_rename.append(keep)
                except Exception as e:
                    problems.append((name_of[kid], "rename", str(e)))
        for keep in to_rename:
            kid = id_val(keep.Id)
            try:
                if set_type_name(keep, new_name[kid]):
                    renamed += 1
                    continue
                detail = "Revit kept the old name."
            except Exception as e:
                detail = str(e)
            problems.append((name_of[kid], "rename", detail))
            try:
                set_type_name(keep, name_of[kid])
            except Exception:
                pass

    msg = ("Moved {} text notes.\nUpdated {} schedule text setting(s).\nDeleted {} styles.\n"
           "Rounded {} text sizes to the nearest 1/{}\".\nRenamed {} styles.\nExcluded styles: {}"
           .format(changed, schedules, deleted, resized, ROUND_DENOM, renamed, len(excluded_ids)))
    if problems:
        output.print_md("## Problems")
        output.print_table(table_data=[list(p) for p in problems], columns=["Style", "Step", "Detail"])
        msg += "\n{} problem(s) - see the output window.".format(len(problems))
    forms.alert(msg, title=TITLE)


main()
