# -*- coding: utf-8 -*-
# Address NAC / Voice script - version v4
__title__ = "Address\nNAC / Voice v4"
__doc__ = ("Fills NAC Address / NAC Circuit and Voice Address / Voice Circuit on each picked Fire Alarm Device "
           "(or a tag hosted to one), in order of selection.\n\n"
           "NAC Address = N#-#.#  (power supply - circuit . device order), NAC Circuit = N#-#\n"
           "Voice Address = V#-#.#, Voice Circuit = V#-#\n\n"
           "At the start, choose for NAC and for Voice whether to continue a circuit already in the project "
           "(resumes after its highest device number), continue from a selected device (resumes after that "
           "device's number), start a new one, or skip that kind for this run. "
           "NAC and Voice are counted separately.\n\n"
           "Address downstream: after a device is addressed (or after 'Continue from selected'), pick a conduit "
           "leaving it. The devices connected downstream by that conduit type are found in order of connection, "
           "and you choose how far to go: to a device you pick, up to a max device count for the circuit, or "
           "up to a max current (amps, from each device's Current parameter; default 1.2 A). The conduit between "
           "the devices of a NAC run gets Notification Circuit = N12 (power supply 1, circuit 2).\n\n"
           "When you finish, the last device of each circuit addressed gets NAC EOL / Voice EOL = Yes and every "
           "other device on that circuit gets No.\n\n"
           "Each Family : Type is NAC Only, Voice Only, or NAC and Voice, from the lookup table "
           "(Address NAC / Voice - Config). A type that isn't in the table is asked about once per run.\n\n"
           "Shift+Click to define / remove table entries. Press Esc to finish picking.")

import os

from System.Collections.Generic import List
from Autodesk.Revit.DB import (Transaction, TransactionStatus, FilteredElementCollector, IndependentTag,
                               ElementId)
from Autodesk.Revit.DB.Electrical import Conduit
from Autodesk.Revit.UI.Selection import ObjectType, ISelectionFilter
from Autodesk.Revit.Exceptions import OperationCanceledException
from pyrevit import revit, forms, script

import nac_voice_types as nv
import conduit_trace as ct

doc = revit.doc
uidoc = revit.uidoc
output = script.get_output()

TITLE = "Address NAC / Voice"
BUTTON_LIMIT = 10   # more choices than this -> searchable list instead of buttons
PREVIEW_LIMIT = 25  # devices listed in the confirmation before a downstream run is addressed
AMP_TOLERANCE = 1e-6

try:
    SHIFT_CLICKED = bool(__shiftclick__)
except NameError:
    SHIFT_CLICKED = False


# ---------- Devices and tags ----------
def all_devices():
    found = []
    for cat in nv.DEVICE_CATEGORIES:
        found.extend(FilteredElementCollector(doc).OfCategory(cat)
                     .WhereElementIsNotElementType().ToElements())
    return found


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
    if nv.is_device(elem):
        return elem
    if isinstance(elem, IndependentTag):
        for eid in tagged_host_ids(elem):
            try:
                host = doc.GetElement(eid)
            except Exception:
                continue
            if host is not None and nv.is_device(host):
                return host
    return None


class DeviceOrTagFilter(ISelectionFilter):
    """Allows devices, or tags hosted to a device; with conduit=True also conduit (to address downstream)."""
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


# ---------- Lookup table ----------
def load_table():
    try:
        return nv.load_table()
    except Exception as ex:
        forms.alert("Could not read the lookup table:\n%s\n\nPath: %s" % (ex, nv.table_path()), title=TITLE)
        return {}


def save_table(table):
    try:
        nv.save_table(table)
        return True
    except Exception as ex:
        forms.alert("Could not save the lookup table:\n%s\n\nPath: %s" % (ex, nv.table_path()), title=TITLE)
        return False


# ---------- Existing address scan (resume) ----------
def scan_existing():
    """{"N": {(power supply, circuit): highest device number}, "V": {...}} from the addresses already written."""
    found = dict((kind, {}) for kind in nv.KINDS)
    for el in all_devices():
        for kind in nv.KINDS:
            p = nv.get_param(el, nv.PARAM_NAMES[kind]["address"])
            if p is None:
                continue
            try:
                parsed = nv.parse_address(kind, p.AsString())
            except Exception:
                parsed = None
            if not parsed:
                continue
            key = (parsed[0], parsed[1])
            if parsed[2] > found[kind].get(key, 0):
                found[kind][key] = parsed[2]
    return found


# ---------- Prompts ----------
def choose(options, message):
    """One of options, or None. Buttons for a short list, a searchable list for a long one."""
    if len(options) > BUTTON_LIMIT:
        return forms.SelectFromList.show(options, title=message, button_name="Select", multiselect=False)
    return forms.CommandSwitchWindow.show(options, message=message)


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
    """One window for a new circuit: power supply, circuit and starting device number.
    self.result = (source, circuit, start), or None if the user went back."""
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


def address_on(el, kind):
    """(source, circuit, number) written on a device for that kind, or None."""
    p = nv.get_param(el, nv.PARAM_NAMES[kind]["address"])
    if p is None:
        return None
    try:
        return nv.parse_address(kind, p.AsString())
    except Exception:
        return None


def preselected_device():
    """The one device selected (directly or by its tag) when the tool was started, or None."""
    devices = {}
    try:
        for eid in uidoc.Selection.GetElementIds():
            el = resolve_device(doc.GetElement(eid))
            if el is not None:
                devices[nv.eid_int(el.Id)] = el
    except Exception:
        return None
    return list(devices.values())[0] if len(devices) == 1 else None


def choose_circuit(kind, existing, preselected):
    """Ask what to do with one kind (NAC or Voice) this run.
    Returns {"source", "circuit", "next", "resumed"}, "SKIP", or None if cancelled."""
    name = nv.KIND_NAMES[kind]
    labels, ordered = {}, []

    # Continue from one device: the device selected when the tool started, or one picked now.
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
    skip_label = "Skip - do not address %s this run" % name
    ordered.extend([new_label, skip_label])

    while True:
        choice = choose(ordered, "%s: which circuit do you want to address?" % name)
        if not choice:
            return None
        if choice == skip_label:
            return "SKIP"

        if choice == selected_label:
            parsed, el = pre, preselected
            if not parsed:
                try:
                    ref = uidoc.Selection.PickObject(
                        ObjectType.Element, DeviceOrTagFilter(),
                        "Select the device (or its tag) to continue %s from - Esc to go back" % name)
                except OperationCanceledException:
                    continue
                el = resolve_device(doc.GetElement(ref.ElementId))
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
                continue    # back to the list
            source, circuit, start = dlg.result
            return {"source": source, "circuit": circuit, "next": start, "resumed": False}

        source, circuit = labels[choice]
        return {"source": source, "circuit": circuit, "next": existing[(source, circuit)] + 1, "resumed": True}


# ---------- Table manager (Shift+Click) ----------
def project_type_info():
    """{"Family : Type": set of kinds found on a placed instance, or None if none is placed}."""
    info = {}
    for cat in nv.DEVICE_CATEGORIES:
        for t in FilteredElementCollector(doc).OfCategory(cat).WhereElementIsElementType().ToElements():
            try:
                info[t.FamilyName + " : " + t.Name] = None
            except Exception:
                pass
    counted = set()
    for el in all_devices():
        key = nv.family_key(doc, el)
        if key in counted:
            continue
        counted.add(key)
        info[key] = nv.kinds_on_element(el)
    return info


def describe_kinds(kinds):
    if kinds is None:
        return "no placed instances"
    if not kinds:
        return "no NAC / Voice parameters"
    return " + ".join(nv.KIND_NAMES[k] for k in nv.KINDS if k in kinds) + " parameters"


def manage_table():
    choice = forms.CommandSwitchWindow.show(
        ["Define / Update Types", "Remove Defined Types", "Open Table File"],
        message="NAC / Voice lookup table")
    if not choice:
        return
    table = load_table()

    if choice == "Define / Update Types":
        scope = forms.CommandSwitchWindow.show(
            ["Only types with NAC / Voice parameters", "All Fire Alarm Device types"],
            message="Which types do you want to list?")
        if not scope:
            return
        only_params = scope.startswith("Only")

        labels = {}
        for key, kinds in project_type_info().items():
            if only_params and not kinds:
                continue
            status = ("currently %s" % table[key]) if key in table else "not defined"
            labels["%s [%s | %s]" % (key, describe_kinds(kinds), status)] = key
        if not labels:
            forms.alert("No matching types found in this project.\n\nTypes only show under 'Only types with "
                        "NAC / Voice parameters' if at least one device of that type is placed.", title=TITLE)
            return

        picked = forms.SelectFromList.show(sorted(labels.keys()), title="Select types to define",
                                           button_name="Next", multiselect=True)
        if not picked:
            return
        label = forms.CommandSwitchWindow.show(
            nv.TYPE_LABELS, message="Device type for the selected %d type(s):" % len(picked))
        if not label:
            return
        for item in picked:
            table[labels[item]] = label
        if save_table(table):
            forms.toast("Saved %d type(s) as %s." % (len(picked), label))

    elif choice == "Remove Defined Types":
        if not table:
            forms.alert("No defined types yet.\n\n%s" % nv.table_path(), title=TITLE)
            return
        labels = dict(("%s -> %s" % (k, v), k) for k, v in table.items())
        picked = forms.SelectFromList.show(sorted(labels.keys()), title="Select types to remove",
                                           button_name="Remove Selected", multiselect=True)
        if not picked:
            return
        for item in picked:
            table.pop(labels[item], None)
        if save_table(table):
            forms.toast("Removed %d type(s)." % len(picked))

    elif choice == "Open Table File":
        if not os.path.isfile(nv.table_path()):
            save_table(table)   # create an empty file
        try:
            os.startfile(nv.table_path())
        except Exception as ex:
            forms.alert("Could not open the file:\n%s\n\nPath: %s" % (ex, nv.table_path()), title=TITLE)


# ---------- Address downstream: how far to go ----------
DOWNSTREAM_XAML = """
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Address downstream"
        SizeToContent="WidthAndHeight"
        WindowStartupLocation="CenterScreen"
        ResizeMode="NoResize"
        Topmost="True">
    <StackPanel Margin="16">
        <TextBlock x:Name="msg_text" TextWrapping="Wrap" MaxWidth="440" Margin="0,0,0,14"/>
        <RadioButton x:Name="end_radio" GroupName="mode" Margin="0,0,0,12"
                     Content="To a selected device - pick the last device to address next"/>
        <StackPanel Orientation="Horizontal" Margin="0,0,0,2">
            <RadioButton x:Name="count_radio" GroupName="mode" Width="260" VerticalAlignment="Center"
                         Content="Max device count for the circuit:"/>
            <TextBox x:Name="count_box" Width="70" GotFocus="count_focus"/>
        </StackPanel>
        <TextBlock x:Name="count_note" Foreground="Gray" TextWrapping="Wrap" MaxWidth="420"
                   Margin="20,0,0,12"/>
        <StackPanel Orientation="Horizontal" Margin="0,0,0,2">
            <RadioButton x:Name="current_radio" GroupName="mode" Width="260" VerticalAlignment="Center"
                         Content="Address to max current (amps):"/>
            <TextBox x:Name="current_box" Width="70" GotFocus="current_focus"/>
        </StackPanel>
        <CheckBox x:Name="existing_check" Margin="20,4,0,12"/>
        <TextBlock x:Name="error_text" Foreground="Firebrick" TextWrapping="Wrap" MaxWidth="440"
                   Margin="0,0,0,10"/>
        <StackPanel Orientation="Horizontal" HorizontalAlignment="Right">
            <Button Content="OK" Width="80" Margin="0,0,8,0" IsDefault="True" Click="ok_click"/>
            <Button Content="Cancel" Width="80" IsCancel="True" Click="cancel_click"/>
        </StackPanel>
    </StackPanel>
</Window>
"""


class DownstreamDialog(forms.WPFWindow):
    """Asks how far down the conduit to address.
    self.result = ("end",) | ("count", max devices on the circuit) | ("current", max amps, include existing),
    or None if cancelled."""
    def __init__(self, message, circuit_text, next_number, existing_amps, existing_count, defaults):
        forms.WPFWindow.__init__(self, DOWNSTREAM_XAML, literal_string=True)
        self.result = None
        self.next_number = next_number
        self.msg_text.Text = message
        self.count_box.Text = defaults["count"]
        self.count_note.Text = ("The next device on %s is .%d, so the count includes the %d device(s) already "
                                "numbered before it." % (circuit_text, next_number, next_number - 1))
        self.current_box.Text = defaults["current"]
        self.existing_check.Content = ("Include the %d device(s) already on %s (%s)"
                                       % (existing_count, circuit_text, nv.fmt_amps(existing_amps)))
        self.existing_check.IsChecked = defaults["include_existing"]
        {"end": self.end_radio, "count": self.count_radio,
         "current": self.current_radio}[defaults["mode"]].IsChecked = True

    def count_focus(self, sender, args):
        self.count_radio.IsChecked = True

    def current_focus(self, sender, args):
        self.current_radio.IsChecked = True

    def _fail(self, box, text):
        self.error_text.Text = text
        box.Focus()
        box.SelectAll()

    def ok_click(self, sender, args):
        if self.end_radio.IsChecked:
            self.result = ("end",)
        elif self.count_radio.IsChecked:
            text = (self.count_box.Text or "").strip()
            if not text.isdigit() or int(text) < 1:
                return self._fail(self.count_box, "The max device count must be a whole number, 1 or higher.")
            if int(text) < self.next_number:
                return self._fail(self.count_box, "The circuit already has %d device(s) numbered, so the max "
                                                  "count has to be at least %d to address any more."
                                  % (self.next_number - 1, self.next_number))
            self.result = ("count", int(text))
        elif self.current_radio.IsChecked:
            text = (self.current_box.Text or "").strip().rstrip("aA").strip()
            try:
                amps = float(text)
            except ValueError:
                amps = 0.0
            if amps <= 0:
                return self._fail(self.current_box, "The max current must be a number of amps above 0, "
                                                    "e.g. 1.2")
            self.result = ("current", amps, bool(self.existing_check.IsChecked))
        else:
            self.error_text.Text = "Choose how far to address."
            return
        self.Close()

    def cancel_click(self, sender, args):
        self.result = None
        self.Close()


# ---------- One run ----------
def next_text(state):
    return " | ".join(nv.fmt_address(k, state[k]["source"], state[k]["circuit"], state[k]["next"])
                      for k in nv.KINDS if k in state)


class Session(object):
    def __init__(self):
        self.state = {}             # kind -> {"source", "circuit", "next", "resumed", "start", "from"}
        self.table = {}
        self.session_types = {}     # types not in the table: key -> device type chosen this run
        self.log = []               # (element id, type key, {kind: number})
        self.addressed = {}         # element id -> {kind: number} written this run
        self.problems = []
        self.not_this_run = []      # (element id, type key, device type): no kind being addressed this run
        self.anchor = None          # device a downstream run starts from: the last one addressed or continued
        self.run_kinds = {}         # conduit type id -> kind chosen for it this run
        self.runs = []              # summary lines of the downstream runs
        self.touched = set()        # (kind, source, circuit) given or losing a device this run: EOL is redone
        self.conduits_set = 0       # conduit segments given a circuit this run
        self.eol_lines = []         # summary lines of the EOL devices
        self.downstream = {"mode": "end", "count": "", "current": str(nv.DEFAULT_MAX_CURRENT),
                           "include_existing": True}    # last answers in the downstream dialog

    def address(self, kind, number):
        s = self.state[kind]
        return nv.fmt_address(kind, s["source"], s["circuit"], number)

    def circuit(self, kind):
        s = self.state[kind]
        return nv.fmt_circuit(kind, s["source"], s["circuit"])

    # ---- Start: for NAC and for Voice, continue a circuit, start a new one, or skip ----
    def choose_circuits(self):
        preselected = preselected_device()
        existing = scan_existing()
        for kind in nv.KINDS:
            picked = choose_circuit(kind, existing[kind], preselected)
            if picked is None:
                return False    # cancelled
            if picked == "SKIP":
                continue
            picked["start"] = picked["next"]
            if picked.get("anchor") is not None:
                self.anchor = picked["anchor"]
            self.state[kind] = picked
        if not self.state:
            forms.alert("NAC and Voice were both skipped, so there is nothing to address.", title=TITLE)
            return False
        self.table = load_table()
        return True

    # ---- Per device ----
    def show(self, device):
        """Select a device so the user can see which one a question is about."""
        try:
            uidoc.Selection.SetElementIds(List[ElementId]([device.Id]))
            uidoc.RefreshActiveView()
        except Exception:
            pass

    def device_label(self, el, key, show=False):
        """NAC Only / Voice Only / NAC and Voice for a device: from the table, else asked once per run.
        Returns None if the device has no NAC / Voice parameters or the user skips it."""
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
            message = ("%s is not in the lookup table. What is it? (Asked once per run; Shift+Click the tool "
                       "button to define it permanently.)" % key)
            if show:
                self.show(el)   # found by the tool, not picked: show which one it is
                message = "Element %d\n%s" % (nv.eid_int(el.Id), message)
            label = forms.CommandSwitchWindow.show(options, message=message)
            if not label:
                return None
        self.session_types[key] = label
        return label

    def targets_for(self, el, kinds):
        """({kind: (address param, circuit param or None)}, [missing address parameter names])."""
        targets, missing = {}, []
        for kind in kinds:
            names = nv.PARAM_NAMES[kind]
            addr_p = nv.get_param(el, names["address"])
            if addr_p is None or addr_p.IsReadOnly:
                missing.append(names["address"])
                continue
            circ_p = nv.get_param(el, names["circuit"])
            if circ_p is not None and circ_p.IsReadOnly:
                circ_p = None
            targets[kind] = (addr_p, circ_p)
        return targets, missing

    def write(self, items, name, conduits=()):
        """Writes addresses in one transaction, numbering in order from the counters.
        items = [(element, type key, {kind: (address param, circuit param or None)})].
        conduits = [(conduit parameter, text)] written in the same transaction.
        Returns None, or the reason nothing was written."""
        nexts = dict((k, self.state[k]["next"]) for k in self.state)
        numbers = []
        for _el, _key, targets in items:
            assigned = {}
            for kind in nv.KINDS:
                if kind in targets:
                    assigned[kind] = nexts[kind]
                    nexts[kind] += 1
            numbers.append(assigned)

        touched = set()
        for (el, _key, _targets), assigned in zip(items, numbers):
            for kind in assigned:
                s = self.state[kind]
                touched.add((kind, s["source"], s["circuit"]))
                old = address_on(el, kind)      # the circuit the device leaves needs its EOL redone too
                if old:
                    touched.add((kind, old[0], old[1]))

        error = None
        t = Transaction(doc, name)
        try:
            t.Start()
            for p, text in conduits:
                p.Set(text)
            for (_el, _key, targets), assigned in zip(items, numbers):
                for kind, number in assigned.items():
                    addr_p, circ_p = targets[kind]
                    addr_p.Set(self.address(kind, number))
                    if circ_p is not None:
                        circ_p.Set(self.circuit(kind))
            # The counters only move on if Revit really kept the change (a warning the user cancels rolls the
            # transaction back without an exception).
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
            return error

        for kind in nexts:
            self.state[kind]["next"] = nexts[kind]
        self.touched.update(touched)
        self.conduits_set += len(conduits)
        for (el, key, targets), assigned in zip(items, numbers):
            eid = nv.eid_int(el.Id)
            self.log.append((eid, key, assigned))
            self.addressed.setdefault(eid, {}).update(assigned)
            for kind in assigned:
                if targets[kind][1] is None:
                    self.problems.append("%s (element %d): no writable %s, so only the address was filled."
                                         % (key, eid, nv.PARAM_NAMES[kind]["circuit"]))
        self.anchor = items[-1][0]
        return None

    def address_device(self, el):
        eid = nv.eid_int(el.Id)
        key = nv.family_key(doc, el)
        label = self.device_label(el, key)
        if label is None:
            if not nv.kinds_on_element(el):
                self.problems.append("%s (element %d): no writable NAC Address or Voice Address parameter. "
                                     "Skipped." % (key, eid))
                forms.toast("No writable NAC / Voice address parameters on that device.")
            else:
                forms.toast("Skipped - no addresses assigned.")
            return

        todo = [k for k in nv.TYPE_KINDS[label] if k in self.state]
        if not todo:
            self.not_this_run.append((eid, key, label))
            forms.toast("%s device - %s is not being addressed this run. Skipped."
                        % (label, " / ".join(nv.KIND_NAMES[k] for k in nv.TYPE_KINDS[label])))
            return

        targets, missing = self.targets_for(el, todo)
        if missing:
            self.problems.append("%s (element %d): defined as %s but has no writable %s. Skipped."
                                 % (key, eid, label, " / ".join(missing)))
            forms.toast("Device has no writable %s. Skipped." % " / ".join(missing))
            return

        # Guard against picking the same device twice (directly or via its tag)
        before = self.addressed.get(eid, {})
        repeats = [k for k in todo if k in before]
        if repeats:
            again = forms.alert("This device was already addressed this run (%s).\n\nRe-address it with new "
                                "numbers?" % ", ".join(self.address(k, before[k]) for k in repeats),
                                title=TITLE, yes=True, no=True)
            if not again:
                return

        error = self.write([(el, key, targets)], "Address NAC / Voice device")
        if error:
            self.problems.append("Element %d: %s" % (eid, error))
            forms.toast("That device was not addressed: %s" % error)

    # ---- Address downstream ----
    def run_kind(self, conduit, type_name):
        """Which circuit (NAC or Voice) a conduit carries, asked once per conduit type when both are addressed."""
        kinds = [k for k in nv.KINDS if k in self.state]
        if len(kinds) == 1:
            return kinds[0]
        tid = ct.eid_int(conduit.GetTypeId())
        if tid in self.run_kinds:
            return self.run_kinds[tid]
        labels = dict(("%s circuit (%s)" % (nv.KIND_NAMES[k], self.circuit(k)), k) for k in kinds)
        choice = forms.CommandSwitchWindow.show(
            sorted(labels.keys()),
            message="Which circuit does '%s' conduit carry? (Asked once per conduit type this run.)" % type_name)
        if not choice:
            return None
        self.run_kinds[tid] = labels[choice]
        return labels[choice]

    def circuit_load(self, kind, leave_out):
        """(amps, device count) of the devices already addressed on the circuit, leaving out element ids in
        leave_out (the ones about to be addressed)."""
        s = self.state[kind]
        amps, count = 0.0, 0
        for el in all_devices():
            if nv.eid_int(el.Id) in leave_out:
                continue
            parsed = address_on(el, kind)
            if parsed and parsed[0] == s["source"] and parsed[1] == s["circuit"]:
                amps += nv.get_current(doc, el) or 0.0
                count += 1
        return amps, count

    def pick_end(self, candidates, type_name, kind):
        """Asks for the last device. Returns the candidates up to and including it, or None on Esc."""
        index = dict((c["id"], n) for n, c in enumerate(candidates))
        while True:
            try:
                ref = uidoc.Selection.PickObject(
                    ObjectType.Element, DeviceOrTagFilter(),
                    "Select the LAST device to address (or its tag) - Esc to go back")
            except OperationCanceledException:
                return None
            el = resolve_device(doc.GetElement(ref.ElementId))
            n = index.get(nv.eid_int(el.Id)) if el is not None else None
            if n is not None:
                return candidates[:n + 1]
            forms.alert("That device is not one of the %d device(s) downstream on '%s' conduit that take a %s "
                        "address. Pick another, or press Esc to go back."
                        % (len(candidates), type_name, nv.KIND_NAMES[kind]), title=TITLE)

    def run_conduits(self, kind, conduit, devices):
        """([(conduit parameter, text)], conduits without the parameter) for the conduit between the anchor and
        the devices of a downstream run."""
        name = nv.CONDUIT_PARAM_NAMES.get(kind)
        if not name:
            return [], 0
        s = self.state[kind]
        text = nv.fmt_conduit(kind, s["source"], s["circuit"])
        sets, missing = [], 0
        try:
            found = ct.conduits_between(self.anchor, conduit, devices)
        except Exception as ex:
            self.problems.append("Could not find the conduit of the run to fill %s: %s" % (name, ex))
            return [], 0
        for c in found:
            p = nv.get_param(c, name)
            if p is None or p.IsReadOnly:
                missing += 1
            else:
                sets.append((p, text))
        return sets, missing

    def follow_conduit(self, conduit):
        """Addresses devices downstream of the anchor device along the picked conduit's type."""
        if self.anchor is None:
            forms.alert("Pick the device to start from first, then the conduit leaving it.\n\nThe conduit is "
                        "followed away from the last device addressed (or the device chosen with "
                        "'Continue from selected').", title=TITLE)
            return
        anchor_id = nv.eid_int(self.anchor.Id)
        type_name = ct.element_type_name(doc, conduit) or "the picked"
        kind = self.run_kind(conduit, type_name)
        if kind is None:
            return
        name = nv.KIND_NAMES[kind]

        found, problem = ct.follow(doc, self.anchor, conduit, nv.is_device)
        if problem:
            forms.alert("That conduit is not connected to the starting device (element %d) by '%s' conduit.\n\n"
                        "Pick a conduit on the run leaving the last device addressed, or pick a device."
                        % (anchor_id, type_name), title=TITLE)
            return

        # Which of the devices found take an address of this kind
        candidates, passed, done, declined = [], [], 0, set()
        for el in found:
            eid = nv.eid_int(el.Id)
            if kind in self.addressed.get(eid, {}):
                done += 1
                continue
            key = nv.family_key(doc, el)
            label = None if key in declined else self.device_label(el, key, show=True)
            if label is None:
                declined.add(key)
                passed.append((eid, key, "not a NAC / Voice device, or skipped"))
                continue
            if kind not in nv.TYPE_KINDS[label]:
                passed.append((eid, key, label))
                continue
            targets, missing = self.targets_for(el, [kind])
            if missing:
                passed.append((eid, key, "no writable %s" % missing[0]))
                continue
            candidates.append({"el": el, "id": eid, "key": key, "targets": targets,
                               "amps": nv.get_current(doc, el), "had": address_on(el, kind)})
        if not candidates:
            forms.alert("No devices that take a %s address were found downstream of element %d on '%s' conduit."
                        "%s" % (name, anchor_id, type_name,
                                ("\n\n%d device(s) on the run were passed over." % len(passed)) if passed else ""),
                        title=TITLE)
            return

        circuit_text = self.circuit(kind)
        next_number = self.state[kind]["next"]
        existing_amps, existing_count = self.circuit_load(kind, set(c["id"] for c in candidates))
        message = ("Following '%s' conduit from element %d on %s circuit %s.\n%d device(s) downstream take a "
                   "%s address. The next address is %s.\n\nHow far do you want to address?"
                   % (type_name, anchor_id, name, circuit_text, len(candidates), name,
                      self.address(kind, next_number)))

        while True:
            dlg = DownstreamDialog(message, circuit_text, next_number, existing_amps, existing_count,
                                   self.downstream)
            dlg.ShowDialog()
            if dlg.result is None:
                return
            mode = dlg.result[0]
            self.downstream["mode"] = mode
            stop_note, total = None, None

            if mode == "end":
                chosen = self.pick_end(candidates, type_name, kind)
                if chosen is None:
                    continue    # Esc: back to the dialog
                how = "to element %d" % chosen[-1]["id"]

            elif mode == "count":
                max_count = dlg.result[1]
                self.downstream["count"] = str(max_count)
                chosen = candidates[:max_count - next_number + 1]
                how = "to max device count %d" % max_count
                if len(chosen) < len(candidates):
                    stop_note = ("Stops at %s, the max device count. %d more device(s) downstream are not "
                                 "addressed." % (self.address(kind, max_count), len(candidates) - len(chosen)))

            else:
                max_amps, include = dlg.result[1], dlg.result[2]
                self.downstream["current"] = "%g" % max_amps
                self.downstream["include_existing"] = include
                total = existing_amps if include else 0.0
                chosen = []
                for c in candidates:
                    amps = c["amps"] or 0.0
                    if total + amps > max_amps + AMP_TOLERANCE:
                        stop_note = ("Stops before element %d (%s, %s): it would bring the total to %s, over "
                                     "the max %s. %d device(s) downstream are not addressed."
                                     % (c["id"], c["key"], nv.fmt_amps(amps), nv.fmt_amps(total + amps),
                                        nv.fmt_amps(max_amps), len(candidates) - len(chosen)))
                        break
                    total += amps
                    chosen.append(c)
                how = "to max current %s" % nv.fmt_amps(max_amps)
                if not chosen:
                    forms.alert("Nothing can be added: %s" % stop_note, title=TITLE)
                    continue
            break

        # Confirm
        lines = []
        for n, c in enumerate(chosen[:PREVIEW_LIMIT]):
            line = "%s  %s" % (self.address(kind, next_number + n), c["key"])
            if mode == "current":
                line += "  (%s)" % (nv.fmt_amps(c["amps"]) if c["amps"] is not None else "no Current - 0 A")
            lines.append(line)
        if len(chosen) > PREVIEW_LIMIT:
            lines.append("... and %d more" % (len(chosen) - PREVIEW_LIMIT))
        notes = []
        if stop_note:
            notes.append(stop_note)
        if mode == "current":
            notes.append("Circuit total: %s%s." % (nv.fmt_amps(total),
                                                  (" (including %s already on %s)"
                                                   % (nv.fmt_amps(existing_amps), circuit_text))
                                                  if self.downstream["include_existing"] else ""))
            no_current = len([c for c in chosen if c["amps"] is None])
            if no_current:
                notes.append("%d device(s) have no Current value and are counted as 0 A." % no_current)
        readdress = len([c for c in chosen if c["had"]])
        if readdress:
            notes.append("%d of them already have a %s, which will be replaced."
                         % (readdress, nv.PARAM_NAMES[kind]["address"]))
        if passed:
            notes.append("%d device(s) on the run don't take a %s address and are passed over." % (len(passed), name))
        if done:
            notes.append("%d device(s) already addressed this run are left as they are." % done)
        go_on = forms.alert("Address %d device(s) downstream of element %d on '%s' conduit?\n\n%s\n\n%s"
                            % (len(chosen), anchor_id, type_name, "\n".join(lines), "\n".join(notes)),
                            title=TITLE, yes=True, no=True)
        if not go_on:
            return

        conduits, no_param = self.run_conduits(kind, conduit, [c["el"] for c in chosen])
        first = next_number
        error = self.write([(c["el"], c["key"], c["targets"]) for c in chosen], "Address NAC / Voice downstream",
                           conduits)
        if error:
            self.problems.append("Downstream of element %d: nothing was addressed (%s)" % (anchor_id, error))
            forms.toast("Nothing was addressed: %s" % error)
            return
        line = ("Followed '%s' conduit from element %d %s: %s to %s (%d device(s))"
                % (type_name, anchor_id, how, self.address(kind, first), self.address(kind, first + len(chosen) - 1),
                   len(chosen)))
        if total is not None:
            line += ", circuit total %s" % nv.fmt_amps(total)
        if conduits:
            line += "; %d conduit(s) set to %s" % (len(conduits), conduits[0][1])
        if no_param:
            self.problems.append("%d conduit(s) on the run from element %d have no writable %s parameter."
                                 % (no_param, anchor_id, nv.CONDUIT_PARAM_NAMES[kind]))
        self.runs.append(line)
        for eid, key, reason in passed:
            self.problems.append("Element %d (%s): on the followed conduit but passed over (%s)." % (eid, key, reason))
        forms.toast("%d device(s) addressed downstream." % len(chosen))

    # ---- Picking ----
    def pick_devices(self):
        flt = DeviceOrTagFilter(conduit=True)
        while True:
            prompt = ("Select device or its tag, or a conduit to address downstream (next: %s) - Esc to finish"
                      % next_text(self.state))
            try:
                ref = uidoc.Selection.PickObject(ObjectType.Element, flt, prompt)
            except OperationCanceledException:
                return
            picked = doc.GetElement(ref.ElementId)
            if isinstance(picked, Conduit):
                self.follow_conduit(picked)
                continue
            el = resolve_device(picked)
            if el is None:
                forms.toast("Selection is not a Fire Alarm Device or a tag hosted to one.")
                continue
            self.address_device(el)

    # ---- Summary ----
    def report(self):
        output.print_md("### Addressing complete")
        for kind in nv.KINDS:
            name = nv.KIND_NAMES[kind]
            if kind not in self.state:
                output.print_md("- %s: skipped this run" % name)
                continue
            s = self.state[kind]
            how = "continued" if s["resumed"] else "new"
            if s.get("from"):
                how = "continued from %s" % s["from"]
            if s["next"] > s["start"]:
                output.print_md("- %s circuit **%s** (%s): %s to **%s**"
                                % (name, self.circuit(kind), how, self.address(kind, s["start"]),
                                   self.address(kind, s["next"] - 1)))
            else:
                output.print_md("- %s circuit **%s** (%s): nothing addressed" % (name, self.circuit(kind), how))
        for line in self.runs:
            output.print_md("- %s" % line)
        for line in self.eol_lines:
            output.print_md("- EOL %s" % line)
        output.print_md("- Devices addressed: **%d**" % len(self.log))
        for eid, key, written in self.log:
            output.print_md("    - %d : %s - %s"
                            % (eid, key, ", ".join(self.address(k, written[k]) for k in nv.KINDS if k in written)))
        if self.not_this_run:
            output.print_md("- Picked but skipped (their kind was not being addressed this run):")
            for eid, key, label in self.not_this_run:
                output.print_md("    - %d : %s (%s)" % (eid, key, label))
        if self.session_types:
            output.print_md("- Types not defined in the lookup table (used for this run only):")
            for k in sorted(self.session_types):
                output.print_md("    - %s -> %s" % (k, self.session_types[k]))
        output.print_md("- Lookup table: `%s`" % nv.table_path())
        for msg in self.problems:
            output.print_md("- Issue: %s" % msg)

    # ---- End of line ----
    def set_eol(self):
        """Last device of each circuit touched this run: EOL = Yes; every other device on it: No."""
        if not self.touched:
            return
        circuits = {}       # (kind, source, circuit) -> [(number, element)]
        for el in all_devices():
            for kind in nv.KINDS:
                parsed = address_on(el, kind)
                if parsed and (kind, parsed[0], parsed[1]) in self.touched:
                    circuits.setdefault((kind, parsed[0], parsed[1]), []).append((parsed[2], el))

        changes = []        # (parameter, value)
        for key in sorted(self.touched):
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
                                             % (nv.fmt_address(kind, source, circuit, n), nv.eid_int(el.Id), name))
                    continue
                value = 1 if n == last else 0
                if n == last:
                    ends.append(nv.eid_int(el.Id))
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
        t = Transaction(doc, "Set NAC / Voice EOL")
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

    def run(self):
        if not self.choose_circuits():
            return
        try:
            self.pick_devices()
        except Exception as ex:
            self.problems.append("Stopped by an unexpected error: %s" % ex)
        try:
            self.set_eol()
        except Exception as ex:
            self.problems.append("EOL parameters were not set: %s" % ex)
        if self.log or self.problems or self.not_this_run:
            self.report()


if SHIFT_CLICKED:
    manage_table()
else:
    Session().run()
