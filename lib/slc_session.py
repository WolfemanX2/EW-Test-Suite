# -*- coding: utf-8 -*-
# slc_session module - version v1
# Change log (last change first):
#   v1 - Code consolidation step 5 (Address SLC v9): Address SLC's addressing session, moved here from the Address SLC
#        v8 button script (unchanged, apart from its windows and menus now coming from addressing_ui).
"""Address SLC: the addressing session (moved from the button script, like Address NAC / Voice's
nac_voice_addressing). The Address SLC button runs main()."""
from System.Collections.Generic import List
from Autodesk.Revit.DB import Transaction, TransactionStatus, ElementId
from Autodesk.Revit.DB.Electrical import Conduit
from Autodesk.Revit.UI.Selection import ObjectType
from Autodesk.Revit.Exceptions import OperationCanceledException
from pyrevit import revit, forms, script

import slc_addressing as slc
import slc_config_editor
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


# ---------- One run ----------
class Session(object):
    def __init__(self):
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
        self.last_choice = {}       # Family : Type -> (count, kind) chosen last, the dialog default
        self.undefined_seen = set()
        self.count_prompted = set()
        self.option_prompted = set()
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
                loop = labels[label]
                picked = (loop["n"], loop["l"],
                          (loop["last"][slc.MODULE] or 0) + 1, (loop["last"][slc.DETECTOR] or 0) + 1)
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
                    forms.toast("Selection is not a Fire Alarm Device or a tag hosted to one.")
                    continue

            found = self.device_addresses(device)
            if found:
                n, l, last = found
                for loop in loops:
                    if loop["n"] == n and loop["l"] == l:
                        for kind in slc.KINDS:
                            if last[kind] is None:
                                last[kind] = loop["last"][kind]
                start_m = (last[slc.MODULE] or 0) + 1
                start_d = (last[slc.DETECTOR] or 0) + 1
                self.resumed = ("Continuing N%dL%d after element %d: from M%s / D%s"
                                % (n, l, slc.eid_int(device.Id), slc.fmt_number(start_m), slc.fmt_number(start_d)))
                forms.toast(self.resumed)
                self.anchor = device
                return n, l, start_m, start_d

            forms.toast("That device has no N#L#M000 / N#L#D000 address to continue from. Pick another.")
            device = None

    def device_addresses(self, device):
        """(n, l, {kind: highest number or None}) from the device's first written address and the others on
        the same loop, or None if it has no address."""
        loop, last = None, {slc.MODULE: None, slc.DETECTOR: None}
        for _pos, p in self.reader.get(device):
            try:
                parsed = slc.parse_address(p.AsString())
            except Exception:
                parsed = None
            if not parsed:
                continue
            n, l, kind, number = parsed
            if loop is None:
                loop = (n, l)
            elif loop != (n, l):
                continue    # an address of another loop on the same device
            if last[kind] is None or number > last[kind]:
                last[kind] = number
        return (loop[0], loop[1], last) if loop else None

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
                forms.toast("Selection is not a Fire Alarm Device or a tag hosted to one.")
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

        type_id = slc.eid_int(conduit.GetTypeId())
        type_name = slc.element_type_name(doc, conduit) or "the picked"
        elements, port_cache = {}, {}

        def remember(el):
            i = slc.eid_int(el.Id)
            elements.setdefault(i, el)
            return i

        def ports(i):
            if i not in port_cache:
                port_cache[i] = [[remember(e) for e in group] for group in slc.connected_elements(elements[i])]
            return port_cache[i]

        def allowed(i):
            # Only conduit of the picked type is followed; fittings, boxes and devices are passed through.
            el = elements[i]
            return not isinstance(el, Conduit) or slc.eid_int(el.GetTypeId()) == type_id

        anchor_id = remember(self.anchor)
        order, problem = slc.trace_downstream(remember(conduit), anchor_id, ports, allowed,
                                              lambda i: slc.is_device(elements[i]))
        if problem:
            forms.alert("That conduit is not connected to the starting device (element %d) by '%s' conduit.\n\n"
                        "Pick a conduit on the run leaving the last device addressed, or pick a device."
                        % (anchor_id, type_name), title=TITLE)
            return True

        todo, no_params, done, head_end = [], [], 0, 0
        for i in order:
            if i in self.addressed:
                done += 1
            elif slc.is_head_end(self.table, slc.family_key(doc, elements[i])):
                self.head_end[i] = slc.family_key(doc, elements[i])
                head_end += 1
            elif any(not p.IsReadOnly for _pos, p in self.reader.get(elements[i])):
                todo.append(elements[i])
            else:
                no_params.append(i)
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
        readdress = len([el for el in todo if self.device_addresses(el)])
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
        try:
            for el in todo:
                if not self.address_device(el):
                    keep_going = False
                    break
        finally:
            self.following = False
        count = len(self.log) - before
        self.runs.append("Followed '%s' conduit from element %d %s: %d of %d device(s) addressed"
                         % (type_name, anchor_id, how_text, count, len(todo)))
        for i in no_params:
            self.problems.append("Element %d (%s): on the followed conduit but has no writable SLC Address "
                                 "parameter. Passed over." % (i, slc.family_key(doc, elements[i])))
        forms.toast("%d device(s) addressed along the conduit." % count)
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
                return todo[:n + 1]
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
            forms.toast("Head End device - never addressed. Skipped.")
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
            forms.toast("No writable address parameters on that device.")
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

        cleared, error = 0, None
        t = Transaction(doc, "Address device")
        try:
            t.Start()
            for i, p in enumerate(fill):
                p.Set(self.address(kind, first + i))
            # Clear unused address parameters that still hold a value.
            for p in leftovers:
                if p.AsString():
                    p.Set("")
                    cleared += 1
            # The counter below only moves on if Revit really kept the change (a warning the user cancels
            # rolls the transaction back without an exception).
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
            self.problems.append("Element %d: %s" % (eid, error))
            forms.toast("That device was not addressed: %s" % error)
            return True

        self.next[kind] = last + 1
        entry = {"id": eid, "key": key, "kind": kind, "count": len(fill), "first": first, "last": last,
                 "cleared": cleared, "option": option}
        self.log.append(entry)
        self.addressed[eid] = entry
        self.anchor = device
        if first > original:
            self.rounding_skips.append((eid, kind, original, first - 1))
        return True

    def resolve_count_and_kind(self, key, eid, rule, total):
        """How many addresses to fill and of which kind, prompting only when the table leaves it open.
        Returns (count, kind, option label or None), or None when the device is skipped."""
        if rule is None:
            # Not in the table: ask for count and kind (not saved).
            self.undefined_seen.add(key)
            return self.ask(key,
                            "%s\nThis type is not defined in the lookup table.\nIt has %d address parameter(s). "
                            "Choose the address kind and how many to fill.\n(Shift+Click the tool button to "
                            "define it permanently.)" % (key, total),
                            [(None, i) for i in range(1, total + 1)], total, slc.MODULE, False, None)

        kind = rule["kind"]
        name = slc.KIND_NAMES[kind]

        # Kind + count defined: never prompt.
        if rule["count"]:
            count = rule["count"]
            if count > total:
                self.problems.append("%s: table says %d but element %d has only %d writable address "
                                     "parameter(s); filled %d." % (key, count, eid, total, total))
                count = total
            return count, kind, None

        if rule["options"]:
            # Named options ("Dual Zone" = 12): offer the ones this device has room for.
            fitting = [(label, count) for label, count in rule["options"] if count <= total]
            if not fitting:
                self.problems.append("%s: element %d has only %d writable address parameter(s), fewer than "
                                     "every Address Option (%s). Skipped."
                                     % (key, eid, total, slc.format_options(rule["options"])))
                forms.toast("Device has fewer address parameters than its smallest Address Option. Skipped.")
                return None
            if len(fitting) == 1:
                return fitting[0][1], kind, fitting[0][0]
            self.option_prompted.add(key)
            return self.ask(key,
                            "%s\nDefined as a %s with Address Options.\nThis device has %d address parameters. "
                            "Choose which option to use." % (key, name, total),
                            fitting, fitting[0][1], kind, True, "Option (addresses):")

        if total == 1:
            return 1, kind, None

        # Kind defined, count not defined: prompt for the count only.
        self.count_prompted.add(key)
        return self.ask(key,
                        "%s\nDefined as a %s, but the number of addresses is not defined.\nThis device has %d "
                        "address parameters. How many do you want to fill?" % (key, name, total),
                        [(None, i) for i in range(1, total + 1)], total, kind, True, None)

    def ask(self, key, message, choices, default_count, default_kind, lock_kind, count_label):
        """Shows the count / kind dialog, defaulting to the last answer for this type."""
        if key in self.last_choice:
            default_count = self.last_choice[key][0]
            if not lock_kind:
                default_kind = self.last_choice[key][1]
        if self.following:
            self.show(self.current)     # the device was found by the tool, not picked: show which one it is
            message = "Element %d\n%s" % (slc.eid_int(self.current.Id), message)
        dlg = aui.CountDialog(message, choices, default_count, default_kind, lock_kind, count_label)
        dlg.ShowDialog()
        if dlg.result is None:
            forms.toast("Skipped - no addresses assigned.")
            return None
        count, kind, label = dlg.result
        if lock_kind:
            kind = default_kind
        self.last_choice[key] = (count, kind)
        return count, kind, label

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
        output.print_md("- Lookup table: `%s`" % slc.table_path())
        for msg in self.problems:
            output.print_md("- Issue: %s" % msg)

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
    global doc, uidoc, output
    doc, uidoc, output = revit.doc, revit.uidoc, script.get_output()
    if shift_clicked:
        slc_config_editor.show_editor(doc)
    else:
        Session().run()
