# -*- coding: utf-8 -*-
# slc_session module - version v5
# Change log (last change first):
#   v5 - Auto Circuit - SLC v3: a run follows the side of a split holding the next device (prefer) and, to an
#        end device, the end device's side (conduit_trace.end_on_its_side), not the side the tee rule puts first.
#   v4 - Auto Circuit - SLC v1: hooks for the Auto Circuit tools: settings_line() (the settings named in the
#        report); main() sets TITLE (Auto Circuit - SLC changes it for its run).
#   v3 - Address SLC v12: follows conduit with conduit_trace.follow (it had its own copy of the same steps); the
#        count / kind questions come from addressing_ui.SlcCountRules and the device's addresses from
#        slc_addressing (shared with Auto-Circuit); saving through ew_common.commit; its messages are titled
#        'Address SLC'.
#   v2 - Address SLC v10: an Automatic (downstream) run is one Undo, 'Address SLC downstream', like Address
#        NAC / Voice; each device picked by hand is one Undo, 'Address SLC device'.
#   v1 - Code consolidation step 5 (Address SLC v9): Address SLC's addressing session, moved here from the Address SLC
#        v8 button script (unchanged, apart from its windows and menus now coming from addressing_ui).
"""Address SLC: the addressing session (moved from the button script, like Address NAC / Voice's
nac_voice_addressing). The Address SLC button runs main()."""
from System.Collections.Generic import List
from Autodesk.Revit.DB import Transaction, TransactionGroup, ElementId
from Autodesk.Revit.DB.Electrical import Conduit
from Autodesk.Revit.UI.Selection import ObjectType
from Autodesk.Revit.Exceptions import OperationCanceledException
from pyrevit import revit, forms, script

import slc_addressing as slc
import slc_config_editor
import conduit_trace as ct      # the shared conduit tracing (lib/conduit_trace.py)
import ew_common as ec        # shared helpers (lib/ew_common.py)
import addressing_ui as aui     # shared addressing windows and menus

doc = revit.doc
uidoc = revit.uidoc
output = script.get_output()

TITLE = "Address SLC"
FROM_SELECTED, NEW_CIRCUIT, FROM_EXISTING = aui.FROM_SELECTED, aui.NEW_CIRCUIT, aui.FROM_EXISTING
PREVIEW_LIMIT = 25  # devices listed in the confirmation before a conduit run is addressed


# ---------- Devices and tags ----------
resolve_device = ec.resolve_device          # from ew_common
DeviceOrTagFilter = ec.DeviceOrTagFilter    # from ew_common
ConduitFilter = ec.ConduitFilter            # from ew_common


MANUAL_LABEL = "Manual - pick each device"
AUTOMATIC_LABEL = "Automatic - address downstream"
FINISH_LABEL = "Finish"
CONTINUE_LABEL = "Continue adding to %s"
ENTIRE_LABEL = "Address the entire run (%d device(s))"
END_LABEL = "Select an end device"


# ---------- Menus and windows (addressing_ui) ----------
choose = aui.choose                      # from addressing_ui


def preselected_device():
    return aui.preselected_device(doc, uidoc)


def end_group(group, keep):
    """Close a transaction group: merge it into one Undo if anything was kept, otherwise roll it back."""
    try:
        if group.HasStarted() and not group.HasEnded():
            if keep:
                group.Assimilate()
            else:
                group.RollBack()
    except Exception:
        pass


# ---------- One run ----------
class Session(aui.SlcCountRules):
    """One Address SLC run. How many addresses each device gets (and the questions about it) comes from
    addressing_ui.SlcCountRules, shared with Auto-Circuit."""
    prefer = ()     # element ids of devices the user chose ahead of a run (Auto Circuit's next device)

    def __init__(self):
        self.init_count_rules()     # last_choice, undefined_seen, count_prompted, option_prompted
        self.reader = slc.AddressParamReader()
        self.table = {}
        self.prefix = None          # "N1L2"
        self.resumed = None         # summary line when continuing
        self.next = {}              # kind -> next number
        self.start = {}             # kind -> first number of this run
        self.log = []               # dicts: id, key, kind, count, first, last, cleared, option
        self.addressed = {}         # element id -> its log entry
        self.rounding_skips = []    # (element id, kind, first skipped, last skipped)
        self.problems = []
        self.anchor = None          # device a conduit run is followed from: the last one addressed
        self.following = False      # True while a conduit run is being addressed
        self.current = None         # device being addressed
        self.runs = []              # summary lines of the conduit runs followed
        self.manual = False         # True once the user chooses Manual: no more Manual / Automatic prompts
        self.finished = False       # the user chose Finish after an automatic run
        self.head_end = {}          # element id -> Family : Type of Head End devices picked or passed over

    def address(self, kind, number):
        return slc.fmt_address(self.prefix, kind, number)

    # ---- Rules table ----
    def load_table(self):
        try:
            self.table = slc.load_table()
            return True
        except Exception as ex:
            go_on = forms.alert("Could not read the lookup table:\n%s\n\nPath: %s\n\nContinue without it? Every "
                                "device will then prompt for its kind and count." % (ex, slc.table_path()),
                                title=TITLE, yes=True, no=True)
            self.table = {}
            return bool(go_on)

    # ---- Continue a loop, continue from a selected device, or start new ----
    def choose_loop(self):
        loops = slc.scan_loops(doc, self.reader)
        # Read before any dialog or pick can change it.
        preselected = preselected_device()

        labels = dict((slc.loop_label(loop), loop) for loop in loops)
        while True:
            picked = None       # (n, l, start module, start detector)
            choice = forms.CommandSwitchWindow.show([FROM_SELECTED, NEW_CIRCUIT, FROM_EXISTING],
                                                    message="SLC: which loop do you want to address?")
            if not choice:
                return False
            if choice == FROM_SELECTED:
                picked = self.continue_from_selected(loops, preselected)
                preselected = None
                if picked is None:
                    continue    # Esc: back to the list
            elif choice == FROM_EXISTING:
                if not loops:
                    forms.alert("There are no SLC loops in this project yet.", title=TITLE)
                    continue
                label = choose([slc.loop_label(loop) for loop in loops],
                               "SLC: which existing loop do you want to continue?")
                if not label:
                    continue    # back to the first list
                picked = slc.loop_next(labels[label])
                self.resumed = ("Continuing N%dL%d from M%s / D%s"
                                % (picked[0], picked[1], slc.fmt_number(picked[2]), slc.fmt_number(picked[3])))
            else:
                dlg = aui.NewLoopDialog()
                dlg.ShowDialog()
                if dlg.result is None:
                    continue    # back to the list
                picked = dlg.result

            self.prefix = "N%dL%d" % (picked[0], picked[1])
            self.next = {slc.MODULE: picked[2], slc.DETECTOR: picked[3]}
            self.start = dict(self.next)
            return True

    def continue_from_selected(self, loops, device):
        """Reads the addresses written on one device and resumes its loop right after them. The kind found on
        the device (M or D) continues after the device's own highest number; the other kind continues after
        the highest number used on that loop. Returns (n, l, start module, start detector), or None on Esc."""
        flt = DeviceOrTagFilter()
        while True:
            if device is None:
                try:
                    ref = uidoc.Selection.PickObject(
                        ObjectType.Element, flt,
                        "Select the addressed device (or its tag) to continue from - Esc to go back")
                except OperationCanceledException:
                    return None
                device = resolve_device(doc.GetElement(ref.ElementId))
                if device is None:
                    forms.toast("Selection is not a Fire Alarm Device or a tag hosted to one.", title=TITLE)
                    continue

            found = slc.resume_numbers(self.reader, device, loops)
            if found:
                n, l, start_m, start_d = found
                self.resumed = ("Continuing N%dL%d after element %d: from M%s / D%s"
                                % (n, l, slc.eid_int(device.Id), slc.fmt_number(start_m), slc.fmt_number(start_d)))
                forms.toast(self.resumed, title=TITLE)
                self.anchor = device
                return found

            forms.toast("That device has no N#L#M000 / N#L#D000 address to continue from. Pick another.",
                        title=TITLE)
            device = None

    # ---- Manual or automatic ----
    def ask_mode(self):
        """After the first device: Manual (keep picking devices) or Automatic (address downstream).
        Returns False when the run has to stop."""
        if self.manual or self.anchor is None:
            return True
        choice = forms.CommandSwitchWindow.show(
            [MANUAL_LABEL, AUTOMATIC_LABEL],
            message="Element %d is the first device. How do you want to address the rest of the loop?"
                    % slc.eid_int(self.anchor.Id))
        if choice == AUTOMATIC_LABEL:
            return self.start_automatic()
        self.manual = True      # Manual, or the prompt was closed
        return True

    def start_automatic(self):
        """Explains the conduit pick, then follows the conduit the user picks from the first device."""
        forms.alert("Automatic addressing\n\nNext, select the conduit leaving element %d in the direction you want "
                    "the addresser to check. Devices are found by following that conduit (and only that conduit "
                    "type) away from the device.\n\nPress Esc while selecting to pick devices manually instead."
                    % slc.eid_int(self.anchor.Id), title=TITLE)
        try:
            ref = uidoc.Selection.PickObject(
                ObjectType.Element, ConduitFilter(),
                "Select the conduit leaving the device in the direction to address - Esc to pick devices manually")
        except OperationCanceledException:
            self.manual = True
            return True
        return self.run_automatic(doc.GetElement(ref.ElementId))

    def run_automatic(self, conduit):
        """A downstream run; afterwards asks whether to finish or keep adding to the loop.
        Returns False when the run has to stop."""
        before = len(self.log)
        keep_going = self.follow_conduit(conduit)
        if not keep_going or len(self.log) == before:
            return keep_going
        choice = forms.CommandSwitchWindow.show(
            [FINISH_LABEL, CONTINUE_LABEL % self.prefix],
            message="Addressed up to %s | %s. Finish, or keep adding devices to %s?"
                    % (self.address(slc.MODULE, self.next[slc.MODULE] - 1),
                       self.address(slc.DETECTOR, self.next[slc.DETECTOR] - 1), self.prefix))
        if choice == FINISH_LABEL:
            self.finished = True
        return True

    # ---- Picking ----
    def pick_devices(self):
        flt = DeviceOrTagFilter(conduit=True)
        # First device chosen with 'Continue From Selected'
        if not self.ask_mode() or self.finished:
            return
        while True:
            prompt = ("Select device or its tag, or a conduit to address everything downstream "
                      "(next: %s | %s) - Esc to finish"
                      % (self.address(slc.MODULE, self.next[slc.MODULE]),
                         self.address(slc.DETECTOR, self.next[slc.DETECTOR])))
            try:
                ref = uidoc.Selection.PickObject(ObjectType.Element, flt, prompt)
            except OperationCanceledException:
                return
            picked = doc.GetElement(ref.ElementId)
            if isinstance(picked, Conduit):
                if not self.run_automatic(picked) or self.finished:
                    return
                continue
            device = resolve_device(picked)
            if device is None:
                forms.toast("Selection is not a Fire Alarm Device or a tag hosted to one.", title=TITLE)
                continue
            before = len(self.log)
            if not self.address_device(device):
                return
            if len(self.log) > before:
                if not self.ask_mode() or self.finished:
                    return

    # ---- Following conduit ----
    def follow_conduit(self, conduit):
        """Addresses every device downstream of the anchor device along the picked conduit's type.
        Returns False when the run has to stop."""
        if self.anchor is None:
            forms.alert("Pick the device to start from first, then the conduit leaving it.\n\nThe conduit is "
                        "followed away from the last device addressed (or the device chosen with "
                        "'Continue From Selected').", title=TITLE)
            return True

        type_name = slc.element_type_name(doc, conduit) or "the picked"
        anchor_id = slc.eid_int(self.anchor.Id)
        # Only conduit of the picked type is followed; fittings, boxes and devices are passed through.
        order, problem = ct.follow(doc, self.anchor, conduit, slc.is_device, prefer=self.prefer)
        self.run_conduit = conduit
        if problem:
            forms.alert("That conduit is not connected to the starting device (element %d) by '%s' conduit.\n\n"
                        "Pick a conduit on the run leaving the last device addressed, or pick a device."
                        % (anchor_id, type_name), title=TITLE)
            return True

        todo, no_params, done, head_end = [], [], 0, 0
        for el in order:
            i = slc.eid_int(el.Id)
            if i in self.addressed:
                done += 1
                continue
            key = slc.family_key(doc, el)
            if slc.is_head_end(self.table, key):
                self.head_end[i] = key
                head_end += 1
            elif any(not p.IsReadOnly for _pos, p in self.reader.get(el)):
                todo.append(el)
            else:
                no_params.append(el)
        if not todo:
            forms.alert("No devices with SLC Address parameters were found downstream of element %d on '%s' "
                        "conduit." % (anchor_id, type_name), title=TITLE)
            return True

        # How far: the entire run, or up to an end device the user selects.
        found_count = len(todo)
        while True:
            how = forms.CommandSwitchWindow.show(
                [ENTIRE_LABEL % found_count, END_LABEL],
                message="Found %d device(s) downstream of element %d on '%s' conduit. Address the entire run, or "
                        "select the last device to address?" % (found_count, anchor_id, type_name))
            if not how:
                return True
            if how == END_LABEL:
                chosen = self.pick_end(todo, type_name)
                if chosen is None:
                    continue    # Esc: back to the choice
                todo = chosen
            break
        how_text = "to element %d" % slc.eid_int(todo[-1].Id) if how == END_LABEL else "to the end of the run"

        lines = ["%d. %s" % (n, slc.family_key(doc, el)) for n, el in enumerate(todo[:PREVIEW_LIMIT], start=1)]
        if len(todo) > PREVIEW_LIMIT:
            lines.append("... and %d more" % (len(todo) - PREVIEW_LIMIT))
        readdress = len([el for el in todo if slc.device_addresses(self.reader, el)])
        notes = []
        if len(todo) < found_count:
            notes.append("Stops at element %d. %d more device(s) downstream are not addressed."
                         % (slc.eid_int(todo[-1].Id), found_count - len(todo)))
        if readdress:
            notes.append("%d of them already have an address, which will be replaced." % readdress)
        if no_params:
            notes.append("%d device(s) on the run have no SLC Address parameter and are passed over."
                         % len(no_params))
        if done:
            notes.append("%d device(s) already addressed this run are left as they are." % done)
        if head_end:
            notes.append("%d Head End device(s) on the run are ignored." % head_end)
        go_on = forms.alert(
            "Address %d device(s) downstream of element %d on '%s' conduit, in this order:\n\n%s\n\n%s"
            "Address them starting at %s | %s?"
            % (len(todo), anchor_id, type_name, "\n".join(lines),
               ("\n".join(notes) + "\n\n") if notes else "",
               self.address(slc.MODULE, self.next[slc.MODULE]),
               self.address(slc.DETECTOR, self.next[slc.DETECTOR])),
            title=TITLE, yes=True, no=True)
        if not go_on:
            return True

        before = len(self.log)
        keep_going = True
        self.following = True
        # The whole run is one Undo, like Address NAC / Voice: each device is still its own transaction (a
        # device can stop to ask for its count), and the group merges them when the run ends.
        group = TransactionGroup(doc, "%s downstream" % TITLE)
        group.Start()
        try:
            for el in todo:
                if not self.address_device(el):
                    keep_going = False
                    break
        finally:
            self.following = False
            end_group(group, len(self.log) > before)
        count = len(self.log) - before
        self.runs.append("Followed '%s' conduit from element %d %s: %d of %d device(s) addressed"
                         % (type_name, anchor_id, how_text, count, len(todo)))
        for el in no_params:
            self.problems.append("Element %d (%s): on the followed conduit but has no writable SLC Address "
                                 "parameter. Passed over." % (slc.eid_int(el.Id), slc.family_key(doc, el)))
        forms.toast("%d device(s) addressed along the conduit." % count, title=TITLE)
        return keep_going

    def pick_end(self, todo, type_name):
        """Asks for the last device. Returns the devices up to and including it, or None on Esc."""
        index = dict((slc.eid_int(el.Id), n) for n, el in enumerate(todo))
        while True:
            try:
                ref = uidoc.Selection.PickObject(
                    ObjectType.Element, DeviceOrTagFilter(),
                    "Select the LAST device to address (or its tag) - Esc to go back")
            except OperationCanceledException:
                return None
            el = resolve_device(doc.GetElement(ref.ElementId))
            n = index.get(slc.eid_int(el.Id)) if el is not None else None
            if n is not None:
                return ct.end_on_its_side(doc, todo, lambda d: slc.eid_int(d.Id), self.anchor, self.run_conduit,
                                          slc.is_device, self.prefer, slc.eid_int(el.Id))
            forms.alert("That device is not one of the %d device(s) downstream on '%s' conduit that will be "
                        "addressed. Pick another, or press Esc to go back." % (len(todo), type_name), title=TITLE)

    def show(self, device):
        """Select a device so the user can see which one a question is about."""
        try:
            uidoc.Selection.SetElementIds(List[ElementId]([device.Id]))
            uidoc.RefreshActiveView()
        except Exception:
            pass

    def address_device(self, device):
        """Addresses one device. Returns False when the run has to stop."""
        eid = slc.eid_int(device.Id)
        self.current = device

        key = slc.family_key(doc, device)
        if slc.is_head_end(self.table, key):
            self.head_end[eid] = key
            forms.toast("Head End device - never addressed. Skipped.", title=TITLE)
            return True

        # Guard against picking the same device twice (directly or via its tag).
        earlier = self.addressed.get(eid)
        if earlier:
            again = forms.alert("This device was already addressed this run (%s to %s).\n\nRe-address it with "
                                "new numbers?" % (self.address(earlier["kind"], earlier["first"]),
                                                  self.address(earlier["kind"], earlier["last"])),
                                title=TITLE, yes=True, no=True)
            if not again:
                return True

        writable = [p for _pos, p in self.reader.get(device) if not p.IsReadOnly]
        if not writable:
            self.problems.append("Element %d: no writable SLC Address parameters" % eid)
            forms.toast("No writable address parameters on that device.", title=TITLE)
            return True

        rule = self.table.get(key)
        resolved = self.resolve_count_and_kind(key, eid, rule, len(writable))
        if resolved is None:
            return True
        count, kind, option = resolved

        # Fill the first `count` address parameters; the rest get cleared.
        fill, leftovers = writable[:count], writable[count:]

        # Rounding rule: start this device on the next multiple of round_to.
        original = self.next[kind]
        first = slc.round_up(original, rule["round_to"]) if rule and rule["round_to"] else original
        last = first + len(fill) - 1
        if last > slc.MAX_NUMBER:
            forms.alert("Addressing %d parameter(s) from %s would exceed %s%d. Stopping."
                        % (len(fill), self.address(kind, first), kind, slc.MAX_NUMBER), title=TITLE)
            return False

        cleared = [0]

        def work():
            for i, p in enumerate(fill):
                p.Set(self.address(kind, first + i))
            # Clear unused address parameters that still hold a value.
            for p in leftovers:
                if p.AsString():
                    p.Set("")
                    cleared[0] += 1

        # The counter below only moves on if Revit really kept the change.
        error = ec.commit(Transaction(doc, "%s device" % TITLE), work)
        if error:
            self.problems.append("Element %d: %s" % (eid, error))
            forms.toast("That device was not addressed: %s" % error, title=TITLE)
            return True

        self.next[kind] = last + 1
        entry = {"id": eid, "key": key, "kind": kind, "count": len(fill), "first": first, "last": last,
                 "cleared": cleared[0], "option": option}
        self.log.append(entry)
        self.addressed[eid] = entry
        self.anchor = device
        if first > original:
            self.rounding_skips.append((eid, kind, original, first - 1))
        return True

    # ---- Hooks for the shared count / kind questions (addressing_ui.SlcCountRules) ----
    def before_ask(self, message):
        if self.following:
            self.show(self.current)     # the device was found by the tool, not picked: show which one it is
            return "Element %d\n%s" % (slc.eid_int(self.current.Id), message)
        return message

    def skipped(self, text):
        forms.toast(text, title=TITLE)

    # ---- Summary ----
    def report(self):
        output.print_md("### Addressing complete (%s)" % self.prefix)
        if self.resumed:
            output.print_md("- %s" % self.resumed)
        for line in self.runs:
            output.print_md("- %s" % line)
        output.print_md("- Devices addressed: **%d**" % len(self.log))
        for kind in slc.KINDS:
            if self.next[kind] > self.start[kind]:
                output.print_md("- Last %s address used: **%s**"
                                % (slc.KIND_NAMES[kind].lower(), self.address(kind, self.next[kind] - 1)))
        for e in self.log:
            line = ("    - %d : %d %s address(es), %s to %s"
                    % (e["id"], e["count"], slc.KIND_NAMES[e["kind"]].lower(),
                       self.address(e["kind"], e["first"]), self.address(e["kind"], e["last"])))
            if e["option"] and e["option"] != str(e["count"]):
                line += " [%s]" % e["option"]
            if e["cleared"]:
                line += " - cleared %d unused address(es)" % e["cleared"]
            output.print_md(line)
        if self.rounding_skips:
            output.print_md("- Numbers skipped by rounding rules:")
            for eid, kind, first, last in self.rounding_skips:
                span = self.address(kind, first)
                if last != first:
                    span += " to " + self.address(kind, last)
                output.print_md("    - %s (before element %d)" % (span, eid))
        for heading, items in (("Types with Address Options (option prompted):", self.option_prompted),
                               ("Types with a kind but no address count (count prompted):", self.count_prompted),
                               ("Types not defined in the lookup table (prompted):", self.undefined_seen)):
            if items:
                output.print_md("- %s" % heading)
                for item in sorted(items):
                    output.print_md("    - %s" % item)
        if self.head_end:
            output.print_md("- Head End devices ignored (never addressed):")
            for eid in sorted(self.head_end):
                output.print_md("    - %d : %s" % (eid, self.head_end[eid]))
        output.print_md("- %s" % self.settings_line())
        for msg in self.problems:
            output.print_md("- Issue: %s" % msg)

    def settings_line(self):
        """The settings this run used, for the report."""
        return "Lookup table: `%s`" % slc.table_path()

    def run(self):
        if not self.load_table() or not self.choose_loop():
            return
        try:
            self.pick_devices()
        except Exception as ex:
            self.problems.append("Stopped by an unexpected error: %s" % ex)
        if self.log or self.problems or self.head_end:
            self.report()


def main(shift_clicked=False):
    """Runs Address SLC. Shift+Click opens Address SLC - Config instead."""
    global doc, uidoc, output, TITLE
    doc, uidoc, output = revit.doc, revit.uidoc, script.get_output()
    TITLE = "Address SLC"
    if shift_clicked:
        slc_config_editor.show_editor(doc)
    else:
        Session().run()
