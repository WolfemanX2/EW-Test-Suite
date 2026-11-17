# -*- coding: utf-8 -*-
# Address NAC / Voice script - version v2
__title__ = "Address\nNAC / Voice"
__doc__ = ("Fills NAC Address / NAC Circuit and Voice Address / Voice Circuit on each picked Fire Alarm Device "
           "(or a tag hosted to one), in order of selection.\n\n"
           "NAC Address = N#-#.#  (power supply - circuit . device order), NAC Circuit = N#-#\n"
           "Voice Address = V#-#.#, Voice Circuit = V#-#\n\n"
           "At the start, choose for NAC and for Voice whether to continue a circuit already in the project "
           "(resumes after its highest device number), continue from a selected device (resumes after that "
           "device's number), start a new one, or skip that kind for this run. "
           "NAC and Voice are counted separately.\n\n"
           "Each Family : Type is NAC Only, Voice Only, or NAC and Voice, from the lookup table "
           "(Address NAC / Voice - Config). A type that isn't in the table is asked about once per run.\n\n"
           "Shift+Click to define / remove table entries. Press Esc to finish picking.")

import os

from Autodesk.Revit.DB import Transaction, FilteredElementCollector, IndependentTag
from Autodesk.Revit.UI.Selection import ObjectType, ISelectionFilter
from Autodesk.Revit.Exceptions import OperationCanceledException
from pyrevit import revit, forms, script

import nac_voice_types as nv

doc = revit.doc
uidoc = revit.uidoc
output = script.get_output()

TITLE = "Address NAC / Voice"
BUTTON_LIMIT = 10   # more choices than this -> searchable list instead of buttons

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
    """Allows devices, or tags hosted to a device."""
    def AllowElement(self, elem):
        try:
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
            <TextBox x:Name="circuit_box" Width="90"/>
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
        self.circuit_box.Text = "1"
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
        circuit = self._read(self.circuit_box, "The circuit number", 0)
        if circuit is None:
            return
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
            parsed = pre
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
                    "from": nv.fmt_address(kind, source, circuit, num)}

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


# ---------- Main ----------
def next_text(state):
    return " | ".join(nv.fmt_address(k, state[k]["source"], state[k]["circuit"], state[k]["next"])
                      for k in nv.KINDS if k in state)


def main():
    if SHIFT_CLICKED:
        manage_table()
        return

    # ---- For NAC and for Voice: continue a circuit, start a new one, or skip ----
    preselected = preselected_device()
    existing = scan_existing()
    state = {}      # kind -> {"source", "circuit", "next", "resumed", "start"}
    for kind in nv.KINDS:
        picked = choose_circuit(kind, existing[kind], preselected)
        if picked is None:
            return      # cancelled
        if picked == "SKIP":
            continue
        picked["start"] = picked["next"]
        state[kind] = picked
    if not state:
        forms.alert("NAC and Voice were both skipped, so there is nothing to address.", title=TITLE)
        return

    flt = DeviceOrTagFilter()
    table = load_table()
    session_types = {}      # types not in the table: key -> device type chosen this run
    log = []                # (element id, type key, {kind: number})
    addressed = {}          # element id -> {kind: number} written this run
    problems = []
    not_this_run = []       # (element id, type key, device type): nothing to fill with the kinds being addressed

    while True:
        prompt = "Select device or its tag (next: %s) - Esc to finish" % next_text(state)
        try:
            ref = uidoc.Selection.PickObject(ObjectType.Element, flt, prompt)
        except OperationCanceledException:
            break

        el = resolve_device(doc.GetElement(ref.ElementId))
        if el is None:
            forms.toast("Selection is not a Fire Alarm Device or a tag hosted to one.")
            continue
        eid = nv.eid_int(el.Id)
        key = nv.family_key(doc, el)

        # ---- Device type: table, else asked once per run ----
        label = table.get(key) or session_types.get(key)
        if label is None:
            available = nv.kinds_on_element(el)
            options = [t for t in nv.TYPE_LABELS if all(k in available for k in nv.TYPE_KINDS[t])]
            if not options:
                problems.append("%s (element %d): no writable NAC Address or Voice Address parameter. Skipped."
                                % (key, eid))
                forms.toast("No writable NAC / Voice address parameters on that device.")
                continue
            if len(options) == 1:
                label = options[0]
            else:
                label = forms.CommandSwitchWindow.show(
                    options, message="%s is not in the lookup table. What is it? (Asked once per run; "
                                     "Shift+Click the tool button to define it permanently.)" % key)
                if not label:
                    forms.toast("Skipped - no addresses assigned.")
                    continue
            session_types[key] = label

        todo = [k for k in nv.TYPE_KINDS[label] if k in state]
        if not todo:
            not_this_run.append((eid, key, label))
            forms.toast("%s device - %s is not being addressed this run. Skipped."
                        % (label, " / ".join(nv.KIND_NAMES[k] for k in nv.TYPE_KINDS[label])))
            continue

        # ---- Parameters ----
        targets, missing = {}, []
        for kind in todo:
            names = nv.PARAM_NAMES[kind]
            addr_p = nv.get_param(el, names["address"])
            if addr_p is None or addr_p.IsReadOnly:
                missing.append(names["address"])
                continue
            circ_p = nv.get_param(el, names["circuit"])
            if circ_p is not None and circ_p.IsReadOnly:
                circ_p = None
            targets[kind] = (addr_p, circ_p)
        if missing:
            problems.append("%s (element %d): defined as %s but has no writable %s. Skipped."
                            % (key, eid, label, " / ".join(missing)))
            forms.toast("Device has no writable %s. Skipped." % " / ".join(missing))
            continue

        # Guard against picking the same device twice (directly or via its tag)
        before = addressed.get(eid, {})
        repeats = [k for k in todo if k in before]
        if repeats:
            again = forms.alert(
                "This device was already addressed this run (%s).\n\nRe-address it with new numbers?"
                % ", ".join(nv.fmt_address(k, state[k]["source"], state[k]["circuit"], before[k])
                            for k in repeats),
                title=TITLE, yes=True, no=True)
            if not again:
                continue

        # ---- Write ----
        t = Transaction(doc, "Address NAC / Voice device")
        t.Start()
        try:
            for kind in todo:
                s = state[kind]
                addr_p, circ_p = targets[kind]
                addr_p.Set(nv.fmt_address(kind, s["source"], s["circuit"], s["next"]))
                if circ_p is not None:
                    circ_p.Set(nv.fmt_circuit(kind, s["source"], s["circuit"]))
            t.Commit()
        except Exception as ex:
            t.RollBack()
            problems.append("Element %d: %s" % (eid, ex))
            continue

        written = {}
        for kind in todo:
            written[kind] = state[kind]["next"]
            state[kind]["next"] += 1
            if targets[kind][1] is None:
                problems.append("%s (element %d): no writable %s, so only the address was filled."
                                % (key, eid, nv.PARAM_NAMES[kind]["circuit"]))
        log.append((eid, key, written))
        addressed.setdefault(eid, {}).update(written)

    # ---- Report ----
    output.print_md("### Addressing complete")
    for kind in nv.KINDS:
        name = nv.KIND_NAMES[kind]
        if kind not in state:
            output.print_md("- %s: skipped this run" % name)
            continue
        s = state[kind]
        circuit = nv.fmt_circuit(kind, s["source"], s["circuit"])
        how = "continued" if s["resumed"] else "new"
        if s.get("from"):
            how = "continued from %s" % s["from"]
        if s["next"] > s["start"]:
            output.print_md("- %s circuit **%s** (%s): %s to **%s**"
                            % (name, circuit, how,
                               nv.fmt_address(kind, s["source"], s["circuit"], s["start"]),
                               nv.fmt_address(kind, s["source"], s["circuit"], s["next"] - 1)))
        else:
            output.print_md("- %s circuit **%s** (%s): nothing addressed" % (name, circuit, how))
    output.print_md("- Devices addressed: **%d**" % len(log))
    for eid, key, written in log:
        output.print_md("    - %d : %s - %s"
                        % (eid, key,
                           ", ".join(nv.fmt_address(k, state[k]["source"], state[k]["circuit"], written[k])
                                     for k in nv.KINDS if k in written)))
    if not_this_run:
        output.print_md("- Picked but skipped (their kind was not being addressed this run):")
        for eid, key, label in not_this_run:
            output.print_md("    - %d : %s (%s)" % (eid, key, label))
    if session_types:
        output.print_md("- Types not defined in the lookup table (used for this run only):")
        for k in sorted(session_types):
            output.print_md("    - %s -> %s" % (k, session_types[k]))
    output.print_md("- Lookup table: `%s`" % nv.table_path())
    for msg in problems:
        output.print_md("- Issue: %s" % msg)


main()
