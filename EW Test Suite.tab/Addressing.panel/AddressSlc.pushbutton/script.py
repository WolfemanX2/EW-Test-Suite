# -*- coding: utf-8 -*-
# Address SLC script - version v2
__title__ = "Address\nSLC v2"
__doc__ = ("Fills the SLC Address parameters of each picked Fire Alarm Device (or a tag hosted to one), in order "
           "of selection. Addresses are N#L#M000 for modules and N#L#D000 for detectors; modules and detectors "
           "are counted separately. Address parameters on the device beyond the number filled are cleared.\n\n"
           "At the start, continue a loop already in the project (resumes after its highest M and D numbers), "
           "continue from a selected device (resumes after the addresses written on it), or start a new one.\n\n"
           "Each Family : Type is addressed by its rule in Address SLC - Config: a fixed number of addresses, "
           "named Address Options to choose from, or a prompt for the count. A type without a rule is asked "
           "for its kind and count.\n\n"
           "Follow the conduit: after a device is addressed (or after 'Continue From Selected'), pick a conduit "
           "leaving it. Every device connected downstream by that conduit type is found, listed for "
           "confirmation and addressed in order of connection. Conduit of any other type is not followed.\n\n"
           "Shift+Click opens Address SLC - Config. Press Esc to finish picking.")

from System.Collections.Generic import List
from Autodesk.Revit.DB import Transaction, TransactionStatus, IndependentTag, ElementId
from Autodesk.Revit.DB.Electrical import Conduit
from Autodesk.Revit.UI.Selection import ObjectType, ISelectionFilter
from Autodesk.Revit.Exceptions import OperationCanceledException
from pyrevit import revit, forms, script

import slc_addressing as slc
import slc_config_editor

doc = revit.doc
uidoc = revit.uidoc
output = script.get_output()

TITLE = "Address SLC"
PREVIEW_LIMIT = 25  # devices listed in the confirmation before a conduit run is addressed
BUTTON_LIMIT = 10   # more choices than this -> searchable list instead of buttons

try:
    SHIFT_CLICKED = bool(__shiftclick__)
except NameError:
    SHIFT_CLICKED = False


# ---------- Devices and tags ----------
def tagged_host_ids(tag):
    """ElementIds of local elements a tag is hosted to (version tolerant)."""
    try:
        return list(tag.GetTaggedLocalElementIds())     # Revit 2022+
    except Exception:
        pass
    try:
        return [tag.TaggedLocalElementId]               # older Revit
    except Exception:
        return []


def resolve_device(elem):
    """The device for a picked element (a device, or a tag hosted to one), or None."""
    if elem is None:
        return None
    if slc.is_device(elem):
        return elem
    if isinstance(elem, IndependentTag):
        for eid in tagged_host_ids(elem):
            try:
                host = doc.GetElement(eid)
            except Exception:
                continue
            if host is not None and slc.is_device(host):
                return host
    return None


class DeviceOrTagFilter(ISelectionFilter):
    """Allows devices, or tags hosted to a device; with conduit=True also conduit (to follow it)."""
    def __init__(self, conduit=False):
        self.conduit = conduit

    def AllowElement(self, elem):
        try:
            if self.conduit and isinstance(elem, Conduit):
                return True
            return resolve_device(elem) is not None
        except Exception:
            return False

    def AllowReference(self, ref, pt):
        return False


def preselected_device():
    """The one device selected (directly or by its tag) when the tool was started, or None."""
    try:
        ids = list(uidoc.Selection.GetElementIds())
        if len(ids) != 1:
            return None
        return resolve_device(doc.GetElement(ids[0]))
    except Exception:
        return None


# ---------- Dialogs ----------
def choose(options, message):
    """One of options, or None. Buttons for a short list, a searchable list for a long one."""
    if len(options) > BUTTON_LIMIT:
        return forms.SelectFromList.show(options, title=message, button_name="Select", multiselect=False)
    return forms.CommandSwitchWindow.show(options, message=message)


NEW_LOOP_XAML = """
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Address SLC - New Loop"
        SizeToContent="WidthAndHeight"
        WindowStartupLocation="CenterScreen"
        ResizeMode="NoResize"
        Topmost="True">
    <StackPanel Margin="16">
        <TextBlock TextWrapping="Wrap" MaxWidth="340" Margin="0,0,0,12"
                   Text="Addresses are written as N#L#M000 for modules and N#L#D000 for detectors. Modules and detectors are counted separately."/>
        <StackPanel Orientation="Horizontal" Margin="0,0,0,8">
            <TextBlock Text="N# (number only):" Width="250" VerticalAlignment="Center"/>
            <TextBox x:Name="n_box" Width="90"/>
        </StackPanel>
        <StackPanel Orientation="Horizontal" Margin="0,0,0,8">
            <TextBlock Text="L# (number only):" Width="250" VerticalAlignment="Center"/>
            <TextBox x:Name="l_box" Width="90"/>
        </StackPanel>
        <StackPanel Orientation="Horizontal" Margin="0,0,0,8">
            <TextBlock Text="Starting MODULE number (M):" Width="250" VerticalAlignment="Center"/>
            <TextBox x:Name="module_box" Width="90"/>
        </StackPanel>
        <StackPanel Orientation="Horizontal" Margin="0,0,0,8">
            <TextBlock Text="Starting DETECTOR number (D):" Width="250" VerticalAlignment="Center"/>
            <TextBox x:Name="detector_box" Width="90"/>
        </StackPanel>
        <TextBlock x:Name="error_text" Foreground="Firebrick" TextWrapping="Wrap" MaxWidth="340"
                   Margin="0,0,0,10"/>
        <StackPanel Orientation="Horizontal" HorizontalAlignment="Right">
            <Button Content="OK" Width="80" Margin="0,0,8,0" IsDefault="True" Click="ok_click"/>
            <Button Content="Cancel" Width="80" IsCancel="True" Click="cancel_click"/>
        </StackPanel>
    </StackPanel>
</Window>
"""


class NewLoopDialog(forms.WPFWindow):
    """N#, L# and the two starting numbers for a new loop, asked in one window.
    self.result = (n, l, start module, start detector), or None if cancelled."""
    def __init__(self):
        forms.WPFWindow.__init__(self, NEW_LOOP_XAML, literal_string=True)
        self.result = None
        for box in (self.n_box, self.l_box, self.module_box, self.detector_box):
            box.Text = "1"
        self.n_box.Focus()
        self.n_box.SelectAll()

    def _read(self, box, what, max_val):
        text = (box.Text or "").strip()
        if text.isdigit() and (max_val is None or int(text) <= max_val):
            return int(text)
        if max_val is None:
            self.error_text.Text = "%s must be a whole number." % what
        else:
            self.error_text.Text = "%s must be a whole number from 0 to %d." % (what, max_val)
        box.Focus()
        box.SelectAll()
        return None

    def ok_click(self, sender, args):
        values = []
        for box, what, max_val in ((self.n_box, "N#", None), (self.l_box, "L#", None),
                                   (self.module_box, "The starting module number", slc.MAX_NUMBER),
                                   (self.detector_box, "The starting detector number", slc.MAX_NUMBER)):
            value = self._read(box, what, max_val)
            if value is None:
                return
            values.append(value)
        self.result = tuple(values)
        self.Close()

    def cancel_click(self, sender, args):
        self.result = None
        self.Close()


COUNT_XAML = """
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Address SLC"
        SizeToContent="WidthAndHeight"
        WindowStartupLocation="CenterScreen"
        ResizeMode="NoResize"
        Topmost="True">
    <StackPanel Margin="16">
        <TextBlock x:Name="msg_text" TextWrapping="Wrap" MaxWidth="400" Margin="0,0,0,10"/>
        <StackPanel Orientation="Horizontal" Margin="0,0,0,8">
            <TextBlock Text="Address kind:" Width="170" VerticalAlignment="Center"/>
            <ComboBox x:Name="kind_box" MinWidth="110"/>
        </StackPanel>
        <StackPanel Orientation="Horizontal" Margin="0,0,0,14">
            <TextBlock x:Name="count_label" Text="Addresses to fill:" Width="170" VerticalAlignment="Center"/>
            <ComboBox x:Name="count_box" MinWidth="110"/>
        </StackPanel>
        <StackPanel Orientation="Horizontal" HorizontalAlignment="Right">
            <Button Content="OK" Width="84" Margin="0,0,8,0" IsDefault="True" Click="ok_click"/>
            <Button Content="Skip Device" Width="90" IsCancel="True" Click="skip_click"/>
        </StackPanel>
    </StackPanel>
</Window>
"""


class CountDialog(forms.WPFWindow):
    """Asks how many addresses to fill on the picked device and, when allowed, which kind.
    choices = [(label or None, count)]; a label makes it a named Address Option.
    self.result = (count, kind, label or None), or None if the device is skipped."""
    def __init__(self, message, choices, default_count, default_kind, lock_kind, count_label):
        forms.WPFWindow.__init__(self, COUNT_XAML, literal_string=True)
        self.result = None
        self.choices = choices
        self.msg_text.Text = message
        if count_label:
            self.count_label.Text = count_label

        for kind in slc.KINDS:
            self.kind_box.Items.Add(slc.KIND_LABELS[kind])
        self.kind_box.SelectedIndex = slc.KINDS.index(default_kind)
        self.kind_box.IsEnabled = not lock_kind

        # Preselect the default count, or else the largest plain number below it.
        index, fallback = -1, 0
        for i, (label, count) in enumerate(choices):
            if label is None:
                self.count_box.Items.Add(str(count))
                if count <= default_count:
                    fallback = i
            else:
                self.count_box.Items.Add(slc.option_display(label, count))
            if index < 0 and count == default_count:
                index = i
        self.count_box.SelectedIndex = index if index >= 0 else fallback
        self.count_box.Focus()

    def ok_click(self, sender, args):
        i = self.count_box.SelectedIndex
        if i < 0:
            return
        label, count = self.choices[i]
        self.result = (count, slc.KINDS[max(self.kind_box.SelectedIndex, 0)], label)
        self.Close()

    def skip_click(self, sender, args):
        self.result = None
        self.Close()


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

        while True:
            picked = None       # (n, l, start module, start detector)
            if loops:
                labels = dict((slc.loop_label(loop), loop) for loop in loops)
                from_selected, new_label = "Continue From Selected", "New"
                choice = choose([slc.loop_label(loop) for loop in loops] + [from_selected, new_label],
                                "Existing addresses were found in this project. What do you want to do?")
                if not choice:
                    return False
                if choice == from_selected:
                    picked = self.continue_from_selected(loops, preselected)
                    preselected = None
                    if picked is None:
                        continue    # Esc: back to the list
                elif choice != new_label:
                    loop = labels[choice]
                    picked = (loop["n"], loop["l"],
                              (loop["last"][slc.MODULE] or 0) + 1, (loop["last"][slc.DETECTOR] or 0) + 1)
                    self.resumed = ("Continuing N%dL%d from M%s / D%s"
                                    % (picked[0], picked[1], slc.fmt_number(picked[2]), slc.fmt_number(picked[3])))

            if picked is None:
                dlg = NewLoopDialog()
                dlg.ShowDialog()
                if dlg.result is None:
                    return False
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

    # ---- Picking ----
    def pick_devices(self):
        flt = DeviceOrTagFilter(conduit=True)
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
                if not self.follow_conduit(picked):
                    return
                continue
            device = resolve_device(picked)
            if device is None:
                forms.toast("Selection is not a Fire Alarm Device or a tag hosted to one.")
                continue
            if not self.address_device(device):
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

        todo, no_params, done = [], [], 0
        for i in order:
            if i in self.addressed:
                done += 1
            elif any(not p.IsReadOnly for _pos, p in self.reader.get(elements[i])):
                todo.append(elements[i])
            else:
                no_params.append(i)
        if not todo:
            forms.alert("No devices with SLC Address parameters were found downstream of element %d on '%s' "
                        "conduit." % (anchor_id, type_name), title=TITLE)
            return True

        lines = ["%d. %s" % (n, slc.family_key(doc, el)) for n, el in enumerate(todo[:PREVIEW_LIMIT], start=1)]
        if len(todo) > PREVIEW_LIMIT:
            lines.append("... and %d more" % (len(todo) - PREVIEW_LIMIT))
        readdress = len([el for el in todo if self.device_addresses(el)])
        notes = []
        if readdress:
            notes.append("%d of them already have an address, which will be replaced." % readdress)
        if no_params:
            notes.append("%d device(s) on the run have no SLC Address parameter and are passed over."
                         % len(no_params))
        if done:
            notes.append("%d device(s) already addressed this run are left as they are." % done)
        go_on = forms.alert(
            "Found %d device(s) downstream of element %d on '%s' conduit, in this order:\n\n%s\n\n%s"
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
        self.runs.append("Followed '%s' conduit from element %d: %d of %d device(s) addressed"
                         % (type_name, anchor_id, count, len(todo)))
        for i in no_params:
            self.problems.append("Element %d (%s): on the followed conduit but has no writable SLC Address "
                                 "parameter. Passed over." % (i, slc.family_key(doc, elements[i])))
        forms.toast("%d device(s) addressed along the conduit." % count)
        return keep_going

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

        key = slc.family_key(doc, device)
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
        dlg = CountDialog(message, choices, default_count, default_kind, lock_kind, count_label)
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
        if self.log or self.problems:
            self.report()


if SHIFT_CLICKED:
    slc_config_editor.show_editor(doc)
else:
    Session().run()
