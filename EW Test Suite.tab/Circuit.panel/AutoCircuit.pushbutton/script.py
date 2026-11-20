# -*- coding: utf-8 -*-
# Auto-Circuit script - version v9
__title__ = "Auto-\nCircuit v9"
__doc__ = ("Runs conduit between devices and addresses them as one circuit.\n\n"
           "1. Choose the circuit type: NAC, Voice or SLC.\n"
           "2. NAC / Voice: continue a circuit already in the project, continue from a selected device, or start "
           "a new one (N#-#.# / V#-#.#, as Address NAC / Voice), then set the circuit limits (max current, default "
           "1.2 A, and max device count). SLC: continue a loop, continue from a selected device, or start a new "
           "one (N#L#M000 / N#L#D000, as Address SLC).\n"
           "3. Pick the new devices or their tags in order (Esc when finished). Elements that don't take an "
           "address of this kind, such as the power supply or panel, and types set to Head End in Address SLC - "
           "Config or Address NAC / Voice - Config, are connected but not addressed.\n"
           "   Continuing a circuit: choose to continue from its last device, or select a device on it. If devices "
           "come after the one you select (followed along the conduit), the new devices are inserted: the conduit "
           "to the next device is removed, new conduit runs through the new devices back to it, and every device "
           "after them on the conduit is renumbered.\n"
           "4. Conduit is planned and created as in Auto Conduit, using Auto Conduit - Config. After a "
           "confirmation the connected devices are addressed in order:\n"
           "   NAC / Voice: Address and Circuit parameters, Notification Circuit on the new conduit (N12 / V12), "
           "and EOL on the last device of the circuit. Types from Address NAC / Voice - Config.\n"
           "   SLC: each Family : Type by its rule in Address SLC - Config (count, Address Options, rounding); "
           "modules and detectors counted separately; unused address parameters cleared.\n\n"
           "Everything is one Undo; cancelling at any step after picking puts everything back.")

# Conduit routing and creation come from lib/conduit_routing.py, shared with Auto Conduit.
# Addressing follows Address NAC / Voice v5 and Address SLC v2, using their shared modules (read only).

from pyrevit import revit, forms, script
from Autodesk.Revit.DB import (
    BuiltInCategory, ElementId,
    Transaction, TransactionGroup, TransactionStatus, FamilyInstance, OverrideGraphicSettings
)
from Autodesk.Revit.DB.Electrical import Conduit
from Autodesk.Revit.UI.Selection import ObjectType
from Autodesk.Revit.Exceptions import OperationCanceledException
from System.Collections.Generic import List
from System.Windows import Visibility

import mounting_rules            # Auto Conduit - Config (read only here)
import nac_voice_types as nv     # Address NAC / Voice - Config and address format (read only here)
import slc_addressing as slc     # Address SLC - Config and address format (read only here)
import conduit_trace as ct       # follows conduit from a device (shared with Address NAC / Voice)
import conduit_routing as cr     # routing and settings shared with Auto Conduit (lib/conduit_routing.py)
import addressing_ui as aui      # windows and menus shared with the addressing tools (lib/addressing_ui.py)
from conduit_routing import (
    AVOID_EXISTING_CONDUIT, AVOID_MODEL_OBSTACLES, DEFAULT_ELEVATION_TEXT, DeviceOrTagFilter,
    HIGHLIGHT_PICKED, MARGIN, OPT_ADD_AGAIN, OPT_ADJUST, OPT_CANCEL, OPT_CANCEL_CHAIN, OPT_CLOSEST,
    OPT_CONTINUE, OPT_FINISH, OPT_IGNORE, OPT_REMOVE, OPT_SKIP, OPT_SKIP_DEV, OPT_UNDO, adjust_device,
    alignment_moves, choose_default_type, collect_obstacles, conduit_connectors, create_link, eid,
    element_label, free_top_count, highlight, make_highlight, parse_length, print_debug, resolve_element,
    resolve_link_types, shift_down, solve_chain,
)

doc = revit.doc
uidoc = revit.uidoc
cr.bind(doc, uidoc, "Auto-Circuit")
output = script.get_output()

# ======================================================================================
# Auto-Circuit: circuit type, addressing and the run
#   NAC / Voice follow Address NAC / Voice v5 (lookup table, N#-#.# / V#-#.#, Notification Circuit, EOL).
#   SLC follows Address SLC v2 (Address SLC - Config rules, N#L#M000 / N#L#D000, unused addresses cleared).
# ======================================================================================

TITLE = "Auto-Circuit"
FROM_SELECTED, NEW_CIRCUIT, FROM_EXISTING = aui.FROM_SELECTED, aui.NEW_CIRCUIT, aui.FROM_EXISTING
PREVIEW_LIMIT = 25    # devices listed in the confirmation before anything is created
AMP_TOLERANCE = 1e-6
CIRCUIT_TYPES = ["NAC", "Voice", "SLC"]
OPT_ADD_ANYWAY = "Add it anyway"
OPT_FINISH_HERE = "Finished - create conduit without it"


# ---------------- shared helpers ----------------


def all_devices():
    return nv.all_devices(doc)


def preselected_device():
    return aui.preselected_device(doc, uidoc)


def pick_addressed_device(prompt):
    """A device (or its tag) picked by the user, or None on Esc."""
    while True:
        try:
            ref = uidoc.Selection.PickObject(ObjectType.Element, DeviceOrTagFilter(), prompt)
        except OperationCanceledException:
            return None
        el = resolve_element(doc.GetElement(ref.ElementId))
        if el is not None and nv.is_device(el):
            return el
        forms.toast("Selection is not a Fire Alarm Device or a tag hosted to one.", title=TITLE)


choose = aui.choose                      # from addressing_ui


def element_key(el):
    return nv.family_key(doc, el) if isinstance(el, FamilyInstance) else element_label(el)


def commit(t, work):
    """Runs work() inside transaction t. Returns None, or the reason nothing was kept."""
    try:
        t.Start()
        work()
        # A warning the user cancels rolls the transaction back without an exception.
        if t.Commit() != TransactionStatus.Committed:
            return "the change was rolled back"
        return None
    except Exception as ex:
        try:
            if t.GetStatus() == TransactionStatus.Started:
                t.RollBack()
        except Exception:
            pass
        return str(ex)


# ======================================================================================
# NAC / Voice
# ======================================================================================


nv_address_on = nv.address_on           # from nac_voice_types


def nv_scan_existing(kind):
    """{(power supply, circuit): highest device number} from the addresses already written."""
    return nv.scan_existing(doc)[kind]


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


class NotificationRun(object):
    """A NAC (kind "N") or Voice (kind "V") circuit, addressed as Address NAC / Voice does."""
    def __init__(self, kind):
        self.kind = kind
        self.name = nv.KIND_NAMES[kind]
        self.state = None           # {"source", "circuit", "next", "start", "resumed", "from", "anchor"}
        self.limits = {"amps": None, "count": None, "include": True}
        self.table = {}
        self.session_types = {}     # types not in the lookup table: key -> label chosen this run
        self.info = {}              # element id -> what the device takes (see classify)
        self.members = {}           # element id -> amps of the devices already on the circuit
        self.problems = []
        self.eol_lines = []
        self.touched = set()
        self.conduits_set = 0
        self.no_param = 0

    # ---- text ----
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

    # ---- set up: which circuit, then the limits ----
    def setup(self):
        try:
            self.table = nv.load_table()
        except Exception as ex:
            forms.alert("Could not read the NAC / Voice lookup table:\n%s\n\nPath: %s\n\nTypes will be asked "
                        "about as they are picked." % (ex, nv.table_path()), title=TITLE)
            self.table = {}
        picked = self.choose_circuit(nv_scan_existing(self.kind), preselected_device())
        if picked is None:
            return False
        picked["start"] = picked["next"]
        self.state = picked
        for el in all_devices():
            parsed = nv_address_on(el, self.kind)
            if parsed and parsed[0] == picked["source"] and parsed[1] == picked["circuit"]:
                self.members[eid(el)] = nv.get_current(doc, el) or 0.0
        dlg = LimitsDialog(self.circuit_text(), picked["next"], sum(self.members.values()), len(self.members))
        dlg.ShowDialog()
        if dlg.result is None:
            return False
        self.limits = dlg.result
        return True

    def choose_circuit(self, existing, preselected):
        """Continue a circuit already in the project, continue from a selected device, or start a new one.
        anchor = the device the conduit starts from when continuing (the circuit's last device), or None."""
        kind, name = self.kind, self.name
        pre = nv_address_on(preselected, kind) if preselected is not None else None
        labels, circuits = {}, []
        for key in sorted(existing):
            label = "%s (last %s)" % (nv.fmt_circuit(kind, key[0], key[1]),
                                      nv.fmt_address(kind, key[0], key[1], existing[key]))
            labels[label] = key
            circuits.append(label)

        while True:
            choice = forms.CommandSwitchWindow.show([FROM_SELECTED, NEW_CIRCUIT, FROM_EXISTING],
                                                    message="%s: which circuit do you want to run and address?" % name)
            if not choice:
                return None
            if choice == FROM_EXISTING:
                if not circuits:
                    forms.alert("There are no %s circuits in this project yet." % name, title=TITLE)
                    continue
                picked = choose(circuits, "%s: which existing circuit do you want to continue?" % name)
                if not picked:
                    continue    # back to the first list
                source, circuit = labels[picked]
                last = existing[(source, circuit)]
                holders = [d for d in all_devices() if nv_address_on(d, kind) == (source, circuit, last)]
                return {"source": source, "circuit": circuit, "next": last + 1, "resumed": True,
                        "from": nv.fmt_address(kind, source, circuit, last), "anchor": None,
                        "last_device": holders[0] if len(holders) == 1 else None}
            if choice == FROM_SELECTED:
                parsed, el = pre, preselected
                if not parsed:
                    el = pick_addressed_device("Select the device (or its tag) to continue %s from - Esc to go back"
                                               % name)
                    if el is None:
                        continue
                    parsed = nv_address_on(el, kind)
                    if not parsed:
                        forms.alert("That device has no %s in the %s#-#.# format to continue from."
                                    % (nv.PARAM_NAMES[kind]["address"], kind), title=TITLE)
                        continue
                source, circuit, num = parsed
                return {"source": source, "circuit": circuit, "next": num + 1, "resumed": True,
                        "from": nv.fmt_address(kind, source, circuit, num), "anchor": el}
            dlg = aui.NewCircuitDialog(kind, existing, TITLE)     # New Circuit
            dlg.ShowDialog()
            if dlg.result is None:
                continue
            source, circuit, start = dlg.result
            return {"source": source, "circuit": circuit, "next": start, "resumed": False,
                    "from": None, "anchor": None}

    # ---- continuing / inserting: where the new conduit starts, and the devices after it ----
    def last_device_options(self):
        dev = self.state.get("last_device")
        if dev is None:
            return []
        return [("Continue from the last device (%s)" % self.state["from"], dev)]

    def position(self, el):
        """The device's number on this circuit, or None if it is not on it."""
        parsed = nv_address_on(el, self.kind)
        s = self.state
        if parsed and parsed[0] == s["source"] and parsed[1] == s["circuit"]:
            return parsed[2]
        return None

    def on_circuit(self, el):
        return self.position(el) is not None

    def compare(self, anchor, el):
        """1 if el comes after the anchor on the circuit, -1 if before, 0 if it can't be told."""
        a, b = self.position(anchor), self.position(el)
        if a is None or b is None or a == b:
            return 0
        return 1 if b > a else -1

    def set_anchor(self, anchor):
        self.state["anchor"] = anchor
        self.state["from"] = self.address(self.position(anchor)) if self.position(anchor) else element_label(anchor)
        self.info.pop(eid(anchor), None)

    def downstream_info(self, el):
        return self.classify(el)

    def prepare_insert(self, anchor, members):
        """New devices go right after the anchor; the devices after it are renumbered from there."""
        self.state["next"] = self.position(anchor) + 1
        self.state["start"] = self.state["next"]

    # ---- what a device takes ----
    def device_label(self, el, key):
        label = self.table.get(key) or self.session_types.get(key)
        if label:
            return label
        available = nv.kinds_on_element(el)
        options = nv.type_options(available)
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
        """{"key", "addr", "why", "targets", "amps", "had"} for an element, worked out once per run."""
        k = eid(el)
        if k in self.info:
            return self.info[k]
        key = element_key(el)
        out = {"key": key, "addr": False, "why": None, "targets": None, "amps": None, "had": None}
        if k == self.anchor_id():
            out["why"] = "the device the circuit continues from"
        elif not nv.is_device(el):
            out["why"] = "not a Fire Alarm Device - conduit only"
        else:
            label = self.device_label(el, key)
            if label is None:
                out["why"] = "no %s parameters, or skipped" % self.name
            elif label == nv.HEAD_END:
                out["why"] = "Head End - connected, never addressed"
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
                    had = nv_address_on(el, self.kind)
                    out.update({"addr": True, "targets": (addr_p, circ_p), "amps": nv.get_current(doc, el),
                                "had": had, "old": nv.fmt_address(self.kind, *had) if had else None})
        self.info[k] = out
        return out

    # ---- limits while picking ----
    def _new_ids(self, ids):
        out = []
        for i in ids:
            if i not in out and self.info.get(i, {}).get("addr"):
                out.append(i)
        return out

    def totals(self, ids):
        """(device count incl. those already numbered, amps) if the addressable devices in ids were added."""
        new_ids = self._new_ids(ids)
        count = self.state["next"] - 1 + len(new_ids)
        amps = sum(self.info[i]["amps"] or 0.0 for i in new_ids)
        if self.limits["include"]:
            amps += sum(a for i, a in self.members.items() if i not in new_ids)
        return count, amps

    def _totals_text(self, ids):
        count, amps = self.totals(ids)
        text = "%d device(s)" % count
        if self.limits["count"]:
            text += " of %d" % self.limits["count"]
        text += ", " + nv.fmt_amps(amps)
        if self.limits["amps"]:
            text += " of %s" % nv.fmt_amps(self.limits["amps"])
        return text

    def status_text(self, ids):
        return "next %s, %s" % (self.address(self.totals(ids)[0] + 1), self._totals_text(ids))

    def over_limit(self, ids, new_id):
        """Why adding new_id would go over a limit, or None."""
        count, amps = self.totals(ids + [new_id])
        if self.limits["count"] and count > self.limits["count"]:
            return ("It would be device .%d on %s, over the max device count of %d."
                    % (count, self.circuit_text(), self.limits["count"]))
        if self.limits["amps"] and amps > self.limits["amps"] + AMP_TOLERANCE:
            return ("Its current (%s) would bring %s to %s, over the max %s."
                    % (nv.fmt_amps(self.info[new_id]["amps"] or 0.0), self.circuit_text(), nv.fmt_amps(amps),
                       nv.fmt_amps(self.limits["amps"])))
        return None

    # ---- planning and writing ----
    def plan(self, items):
        """[(element, info, address text)] in order, or (None, reason)."""
        first = self.state["next"]
        return [(el, info, self.address(first + n)) for n, (el, info) in enumerate(items)], None

    def preview_line(self, el, info, text):
        line = "%s  %s" % (text, info["key"])
        if info["amps"] is not None:
            line += "  (%s)" % nv.fmt_amps(info["amps"])
        if info.get("old") and info["old"] != text:
            line += "  (was %s)" % info["old"]
        return line

    def confirm_notes(self, planned):
        notes = ["Circuit total: %s." % self._totals_text([eid(el) for el, _i, _t in planned])]
        readdress = len([1 for _el, info, _t in planned if info["had"]])
        if readdress:
            notes.append("%d of them already have a %s, which will be replaced."
                         % (readdress, nv.PARAM_NAMES[self.kind]["address"]))
        return notes

    def write(self, planned, conduits):
        """Addresses + circuit on the devices and Notification Circuit on the conduits, one transaction.
        Returns None, or the reason nothing was written."""
        kind, s = self.kind, self.state
        touched = set([(kind, s["source"], s["circuit"])])
        for _el, info, _t in planned:
            if info["had"]:
                touched.add((kind, info["had"][0], info["had"][1]))   # the circuit it leaves needs its EOL redone
        pname = nv.CONDUIT_PARAM_NAMES.get(kind)
        conduit_params, no_param = [], 0
        if pname:
            for c in conduits:
                p = nv.get_param(c, pname)
                if p is None or p.IsReadOnly:
                    no_param += 1
                else:
                    conduit_params.append(p)

        def work():
            for p in conduit_params:
                p.Set(nv.merge_conduit_value(p.AsString(), kind, self.conduit_text()))
            for _el, info, text in planned:
                addr_p, circ_p = info["targets"]
                addr_p.Set(text)
                if circ_p is not None:
                    circ_p.Set(self.circuit_text())

        error = commit(Transaction(doc, "Auto-Circuit: address devices"), work)
        if error:
            return error
        s["next"] += len(planned)
        self.touched = touched
        self.conduits_set, self.no_param = len(conduit_params), no_param
        for _el, info, _t in planned:
            if info["targets"][1] is None:
                self.problems.append("%s: no writable %s, so only the address was filled."
                                     % (info["key"], nv.PARAM_NAMES[kind]["circuit"]))
        return None

    def finish(self):
        """Last device of each circuit touched: EOL = Yes; every other device on it: No."""
        if not self.touched:
            return
        circuits = {}
        for el in all_devices():
            parsed = nv_address_on(el, self.kind)
            if parsed and (self.kind, parsed[0], parsed[1]) in self.touched:
                circuits.setdefault((self.kind, parsed[0], parsed[1]), []).append((parsed[2], el))
        changes = []
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

        def work():
            for p, value in changes:
                p.Set(value)

        error = commit(Transaction(doc, "Auto-Circuit: set %s EOL" % self.name), work)
        if error:
            self.problems.append("EOL parameters were not set: %s" % error)
            self.eol_lines = []

    # ---- report ----
    def report_lines(self, addressed):
        lines = []
        if self.conduits_set:
            lines.append("%d conduit segment(s) given %s = %s"
                         % (self.conduits_set, nv.CONDUIT_PARAM_NAMES[self.kind], self.conduit_text()))
        if self.no_param:
            self.problems.append("%d conduit segment(s) have no writable %s parameter."
                                 % (self.no_param, nv.CONDUIT_PARAM_NAMES[self.kind]))
        lines.append("Circuit total: %s%s" % (self._totals_text([eid(el) for el, _i, _t in addressed]),
                                              "" if self.limits["include"] else " (devices added this run only)"))
        for line in self.eol_lines:
            lines.append("EOL %s" % line)
        if self.session_types:
            lines.append("Types not in the NAC / Voice lookup table (used for this run only): %s"
                         % "; ".join("%s -> %s" % (k, self.session_types[k]) for k in sorted(self.session_types)))
        lines.append("NAC / Voice lookup table: `%s`" % nv.table_path())
        return lines


# ======================================================================================
# SLC
# ======================================================================================


class SlcRun(object):
    """An SLC loop, addressed as Address SLC does: each Family : Type by its rule in Address SLC - Config,
    modules and detectors counted separately, unused address parameters on a device cleared."""
    name = "SLC"

    def __init__(self):
        self.reader = slc.AddressParamReader()
        self.table = {}
        self.prefix = None
        self.state = None           # {"next": {kind: n}, "start": {kind: n}, "resumed", "from", "anchor"}
        self.info = {}
        self.last_choice = {}       # Family : Type -> (count, kind) chosen last, the dialog default
        self.undefined_seen = set()
        self.count_prompted = set()
        self.option_prompted = set()
        self.rounding_skips = []    # (element id, kind, first skipped, last skipped)
        self.problems = []
        self.cleared = 0
        self._pending = None        # (numbered, next numbers, rounding skips) from the last plan()
        self.loop_last = {slc.MODULE: None, slc.DETECTOR: None}   # highest numbers on the loop at the start

    def address(self, kind, number):
        return slc.fmt_address(self.prefix, kind, number)

    def circuit_text(self):
        return self.prefix

    def anchor_id(self):
        a = self.state.get("anchor") if self.state else None
        return eid(a) if a is not None else None

    # ---- set up: which loop ----
    def setup(self):
        try:
            self.table = slc.load_table()
        except Exception as ex:
            go_on = forms.alert("Could not read the Address SLC - Config table:\n%s\n\nPath: %s\n\nContinue without "
                                "it? Every device will then ask for its kind and count."
                                % (ex, slc.table_path()), title=TITLE, yes=True, no=True)
            if not go_on:
                return False
            self.table = {}
        loops = slc.scan_loops(doc, self.reader)
        preselected = preselected_device()
        while True:
            picked, resumed, anchor = None, None, None
            labels = dict((slc.loop_label(loop), loop) for loop in loops)
            choice = forms.CommandSwitchWindow.show([FROM_SELECTED, NEW_CIRCUIT, FROM_EXISTING],
                                                    message="SLC: which loop do you want to run and address?")
            if not choice:
                return False
            if choice == FROM_EXISTING:
                if not loops:
                    forms.alert("There are no SLC loops in this project yet.", title=TITLE)
                    continue
                label = choose([slc.loop_label(loop) for loop in loops],
                               "SLC: which existing loop do you want to continue?")
                if not label:
                    continue    # back to the first list
                choice = label
            if choice == FROM_SELECTED:
                found = self.continue_from_selected(loops, preselected)
                preselected = None
                if found is None:
                    continue
                picked, anchor = found
                resumed = "element %d (M%s / D%s next)" % (eid(anchor), slc.fmt_number(picked[2]),
                                                           slc.fmt_number(picked[3]))
            elif choice == NEW_CIRCUIT:
                dlg = aui.NewLoopDialog("Auto-Circuit - New SLC Loop", "Back")
                dlg.ShowDialog()
                if dlg.result is None:
                    continue
                picked = dlg.result
            else:
                loop = labels[choice]
                picked = (loop["n"], loop["l"],
                          (loop["last"][slc.MODULE] or 0) + 1, (loop["last"][slc.DETECTOR] or 0) + 1)
                resumed = "N%dL%d (M%s / D%s next)" % (loop["n"], loop["l"], slc.fmt_number(picked[2]),
                                                       slc.fmt_number(picked[3]))
            self.prefix = "N%dL%d" % (picked[0], picked[1])
            for loop in loops:
                if loop["n"] == picked[0] and loop["l"] == picked[1]:
                    self.loop_last = dict(loop["last"])
            nxt = {slc.MODULE: picked[2], slc.DETECTOR: picked[3]}
            last_devices = {}
            if resumed and anchor is None:
                for kind in slc.KINDS:
                    if self.loop_last[kind] is None:
                        continue
                    text = self.address(kind, self.loop_last[kind])
                    holders = [d for d in all_devices()
                               if any(p.AsString() == text for _pos, p in self.reader.get(d))]
                    if len(holders) == 1:
                        last_devices[kind] = (text, holders[0])
            self.state = {"next": nxt, "start": dict(nxt), "resumed": bool(resumed), "from": resumed,
                          "anchor": anchor, "last_devices": last_devices}
            return True

    # ---- continuing / inserting: where the new conduit starts, and the devices after it ----
    def last_device_options(self):
        out = []
        for kind in slc.KINDS:
            found = self.state.get("last_devices", {}).get(kind)
            if found:
                out.append(("Continue from the last %s (%s)" % (slc.KIND_NAMES[kind].lower(), found[0]), found[1]))
        return out

    def positions(self, el):
        """{kind: (lowest, highest)} of the device's addresses on this loop."""
        out = {}
        for _pos, p in self.reader.get(el):
            try:
                parsed = slc.parse_address(p.AsString())
            except Exception:
                parsed = None
            if not parsed or "N%dL%d" % (parsed[0], parsed[1]) != self.prefix:
                continue
            kind, number = parsed[2], parsed[3]
            lo, hi = out.get(kind, (number, number))
            out[kind] = (min(lo, number), max(hi, number))
        return out

    def on_circuit(self, el):
        return bool(self.positions(el))

    def compare(self, anchor, el):
        """1 if el comes after the anchor on the loop, -1 if before, 0 if it can't be told (no shared kind)."""
        pa, pe = self.positions(anchor), self.positions(el)
        for kind in pa:
            if kind in pe:
                if pe[kind][0] > pa[kind][1]:
                    return 1
                if pe[kind][1] < pa[kind][0]:
                    return -1
        return 0

    def set_anchor(self, anchor):
        self.state["anchor"] = anchor
        pa = self.positions(anchor)
        self.state["from"] = "element %d (%s)" % (eid(anchor), ", ".join(
            self._range_text(k, pa[k][0], pa[k][1]) for k in slc.KINDS if k in pa) or "no address")
        self.info.pop(eid(anchor), None)

    def downstream_info(self, el):
        """A device already on the loop, renumbered with its rule: the rule's count and rounding if it has one,
        otherwise as many addresses as it has now (no prompts for devices already addressed)."""
        k = eid(el)
        if k in self.info:
            return self.info[k]
        key = element_key(el)
        pos = self.positions(el)
        writable = [p for _pos, p in self.reader.get(el) if not p.IsReadOnly]
        out = {"key": key, "addr": False, "why": None, "amps": None}
        if not pos or not writable:
            out["why"] = "no writable SLC Address parameters"
        else:
            kind = slc.MODULE if slc.MODULE in pos else slc.DETECTOR
            current = 0
            for _pos, p in self.reader.get(el):
                parsed = slc.parse_address(p.AsString() or "")
                if parsed and "N%dL%d" % (parsed[0], parsed[1]) == self.prefix and parsed[2] == kind:
                    current += 1
            rule = self.table.get(key)
            count = rule["count"] if rule and rule["count"] and rule["kind"] == kind else current
            count = max(1, min(count, len(writable)))
            out.update({"addr": True, "kind": kind, "fill": writable[:count], "leftovers": writable[count:],
                        "option": None, "round_to": rule["round_to"] if rule else None, "had": True,
                        "old": self._range_text(kind, pos[kind][0], pos[kind][1])})
        self.info[k] = out
        return out

    def prepare_insert(self, anchor, members):
        """Numbers carry on right after the anchor's own addresses; the other kind carries on from the first
        device after the anchor that has it (or after the loop's highest, if none does)."""
        pa = self.positions(anchor)
        nxt = {}
        for kind in slc.KINDS:
            if kind in pa:
                nxt[kind] = pa[kind][1] + 1
                continue
            lows = [self.positions(m)[kind][0] for m in members if kind in self.positions(m)]
            nxt[kind] = min(lows) if lows else (self.loop_last[kind] or 0) + 1
        self.state["next"] = nxt
        self.state["start"] = dict(nxt)

    def continue_from_selected(self, loops, device):
        """((n, l, start module, start detector), device) resumed right after the device's addresses, or None.
        The kind found on the device continues after the device's own highest number; the other kind continues
        after the highest number used on that loop."""
        while True:
            if device is None:
                device = pick_addressed_device("Select the addressed device (or its tag) to continue the SLC loop "
                                               "from - Esc to go back")
                if device is None:
                    return None
            found = self.device_addresses(device)
            if found:
                n, l, last = found
                for loop in loops:
                    if loop["n"] == n and loop["l"] == l:
                        for kind in slc.KINDS:
                            if last[kind] is None:
                                last[kind] = loop["last"][kind]
                return (n, l, (last[slc.MODULE] or 0) + 1, (last[slc.DETECTOR] or 0) + 1), device
            forms.toast("That device has no N#L#M000 / N#L#D000 address to continue from. Pick another.",
                        title=TITLE)
            device = None

    def device_addresses(self, device):
        """(n, l, {kind: highest number or None}) of the device's first written loop, or None."""
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
                continue
            if last[kind] is None or number > last[kind]:
                last[kind] = number
        return (loop[0], loop[1], last) if loop else None

    # ---- what a device takes (rules table, as in Address SLC) ----
    def classify(self, el):
        k = eid(el)
        if k in self.info:
            return self.info[k]
        key = element_key(el)
        out = {"key": key, "addr": False, "why": None, "amps": None}
        if k == self.anchor_id():
            out["why"] = "the device the loop continues from"
        elif not nv.is_device(el):
            out["why"] = "not a Fire Alarm Device - conduit only"
        else:
            writable = [p for _pos, p in self.reader.get(el) if not p.IsReadOnly]
            if slc.is_head_end(self.table, key):
                out["why"] = "Head End - connected, never addressed"
            elif not writable:
                out["why"] = "no writable SLC Address parameters"
            else:
                rule = self.table.get(key)
                resolved = self.resolve_count_and_kind(key, k, rule, len(writable))
                if resolved is None:
                    out["why"] = "not addressed (chosen when picked)"
                else:
                    count, kind, option = resolved
                    pos = self.positions(el)
                    old = ", ".join(self._range_text(kk, pos[kk][0], pos[kk][1]) for kk in slc.KINDS if kk in pos)
                    out.update({"addr": True, "kind": kind, "fill": writable[:count], "leftovers": writable[count:],
                                "option": option, "round_to": rule["round_to"] if rule else None,
                                "had": self.device_addresses(el) is not None, "old": old or None})
        self.info[k] = out
        return out

    def resolve_count_and_kind(self, key, element_id, rule, total):
        """(count, kind, option label or None), prompting only when the table leaves it open; None = skip."""
        if rule is None:
            self.undefined_seen.add(key)
            return self.ask(key, "%s\nThis type is not defined in Address SLC - Config.\nIt has %d address "
                                 "parameter(s). Choose the address kind and how many to fill." % (key, total),
                            [(None, i) for i in range(1, total + 1)], total, slc.MODULE, False, None)
        kind = rule["kind"]
        name = slc.KIND_NAMES[kind]
        if rule["count"]:
            count = rule["count"]
            if count > total:
                self.problems.append("%s: table says %d but element %d has only %d writable address "
                                     "parameter(s); filled %d." % (key, count, element_id, total, total))
                count = total
            return count, kind, None
        if rule["options"]:
            fitting = [(label, count) for label, count in rule["options"] if count <= total]
            if not fitting:
                self.problems.append("%s: element %d has only %d writable address parameter(s), fewer than every "
                                     "Address Option (%s). Not addressed."
                                     % (key, element_id, total, slc.format_options(rule["options"])))
                return None
            if len(fitting) == 1:
                return fitting[0][1], kind, fitting[0][0]
            self.option_prompted.add(key)
            return self.ask(key, "%s\nDefined as a %s with Address Options.\nThis device has %d address parameters. "
                                 "Choose which option to use." % (key, name, total),
                            fitting, fitting[0][1], kind, True, "Option (addresses):")
        if total == 1:
            return 1, kind, None
        self.count_prompted.add(key)
        return self.ask(key, "%s\nDefined as a %s, but the number of addresses is not defined.\nThis device has %d "
                             "address parameters. How many do you want to fill?" % (key, name, total),
                        [(None, i) for i in range(1, total + 1)], total, kind, True, None)

    def ask(self, key, message, choices, default_count, default_kind, lock_kind, count_label):
        if key in self.last_choice:
            default_count = self.last_choice[key][0]
            if not lock_kind:
                default_kind = self.last_choice[key][1]
        dlg = aui.CountDialog(message, choices, default_count, default_kind, lock_kind, count_label,
                              title="Auto-Circuit - SLC addresses", skip_text="Don't Address", skip_width=100)
        dlg.ShowDialog()
        if dlg.result is None:
            return None
        count, kind, label = dlg.result
        if lock_kind:
            kind = default_kind
        self.last_choice[key] = (count, kind)
        return count, kind, label

    # ---- numbering ----
    def _number(self, items):
        """[(element, info, first, last)], next numbers after them, rounding skips, and the reason it can't be
        done (an address over the max) or None."""
        nxt = dict(self.state["next"])
        out, skips = [], []
        for el, info in items:
            kind = info["kind"]
            original = nxt[kind]
            first = slc.round_up(original, info["round_to"]) if info["round_to"] else original
            last = first + len(info["fill"]) - 1
            if last > slc.MAX_NUMBER:
                return out, nxt, skips, ("%s needs %s to %s, past %s%d."
                                         % (info["key"], self.address(kind, first), self.address(kind, last),
                                            kind, slc.MAX_NUMBER))
            if first > original:
                skips.append((eid(el), kind, original, first - 1))
            out.append((el, info, first, last))
            nxt[kind] = last + 1
        return out, nxt, skips, None

    def _range_text(self, kind, first, last):
        if first == last:
            return self.address(kind, first)
        return "%s to %s%s" % (self.address(kind, first), kind, slc.fmt_number(last))

    def status_text(self, ids):
        seen, items = set(), []
        for i in ids:
            info = self.info.get(i, {})
            if i not in seen and info.get("addr"):
                seen.add(i)
                items.append((None, info))
        _out, nxt, _skips, _err = self._number(items)
        return "next %s | %s, %d device(s)" % (self.address(slc.MODULE, nxt[slc.MODULE]),
                                               self.address(slc.DETECTOR, nxt[slc.DETECTOR]), len(items))

    def over_limit(self, ids, new_id):
        return None     # SLC loops have no current or count limit here; numbers past 999 are caught when planning

    # ---- planning and writing ----
    def plan(self, items):
        numbered, nxt, skips, error = self._number(items)
        if error:
            return None, error
        self._pending = (numbered, nxt, skips)
        return [(el, info, self._range_text(info["kind"], first, last)) for el, info, first, last in numbered], None

    def preview_line(self, el, info, text):
        line = "%s  %s" % (text, info["key"])
        if info["option"] and info["option"] != str(len(info["fill"])):
            line += "  [%s]" % info["option"]
        if info.get("old") and info["old"] != text:
            line += "  (was %s)" % info["old"]
        return line

    def confirm_notes(self, planned):
        numbered, nxt, skips = self._pending
        notes = []
        for kind in slc.KINDS:
            used = [(f, l) for _el, info, f, l in numbered if info["kind"] == kind]
            if used:
                notes.append("Last %s address: %s." % (slc.KIND_NAMES[kind].lower(),
                                                       self.address(kind, nxt[kind] - 1)))
        if skips:
            notes.append("%d number range(s) are skipped by rounding rules." % len(skips))
        clear = len([1 for _el, info, _t in planned if any(p.AsString() for p in info["leftovers"])])
        if clear:
            notes.append("%d device(s) have unused address parameters with values, which will be cleared." % clear)
        readdress = len([1 for _el, info, _t in planned if info["had"]])
        if readdress:
            notes.append("%d of them already have an address, which will be replaced." % readdress)
        return notes

    def write(self, planned, conduits):
        numbered, nxt, skips = self._pending
        counter = [0]

        def work():
            for el, info, first, last in numbered:
                for i, p in enumerate(info["fill"]):
                    p.Set(self.address(info["kind"], first + i))
                for p in info["leftovers"]:
                    if p.AsString():
                        p.Set("")
                        counter[0] += 1

        error = commit(Transaction(doc, "Auto-Circuit: address SLC devices"), work)
        if error:
            return error
        self.state["next"] = nxt
        self.rounding_skips = skips
        self.cleared = counter[0]
        return None

    def finish(self):
        pass    # no EOL on SLC loops

    def report_lines(self, addressed):
        lines = []
        for kind in slc.KINDS:
            if self.state["next"][kind] > self.state["start"][kind]:
                lines.append("Last %s address used: **%s**" % (slc.KIND_NAMES[kind].lower(),
                                                               self.address(kind, self.state["next"][kind] - 1)))
        if self.cleared:
            lines.append("%d unused address parameter(s) cleared" % self.cleared)
        for element_id, kind, first, last in self.rounding_skips:
            lines.append("Skipped by rounding rules: %s (before element %d)"
                         % (self._range_text(kind, first, last), element_id))
        for heading, keys in (("Types with Address Options (option asked)", self.option_prompted),
                              ("Types with a kind but no address count (count asked)", self.count_prompted),
                              ("Types not defined in Address SLC - Config (asked)", self.undefined_seen)):
            if keys:
                lines.append("%s: %s" % (heading, "; ".join(sorted(keys))))
        lines.append("Address SLC - Config table: `%s`" % slc.table_path())
        return lines


# ======================================================================================
# Circuit type, picking, report and main
# ======================================================================================


def choose_circuit_type():
    """The run for the chosen circuit type, or None if cancelled."""
    choice = forms.CommandSwitchWindow.show(CIRCUIT_TYPES, message="Auto-Circuit: which circuit type?")
    if choice == "NAC":
        return NotificationRun("N")
    if choice == "Voice":
        return NotificationRun("V")
    if choice == "SLC":
        return SlcRun()
    return None


def pick_chain(run, min_picks=2):
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
        return _pick_loop(ogs, run, min_picks)
    finally:
        if tg is not None:
            try:
                tg.RollBack()
            except Exception:
                pass


def _pick_loop(ogs, run, min_picks):
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
        if len(picks) >= min_picks:
            return [p["el"] for p in picks]
        forms.alert("Select at least %d element(s)." % min_picks, title=TITLE)
        return None

    anchor = run.state.get("anchor")
    if anchor is not None:
        run.set_anchor(anchor)
    if anchor is not None:
        start_note = " (new devices, after element %d)" % eid(anchor)
    elif run.state["resumed"]:
        start_note = " (new devices; you choose where they connect next)"
    else:
        start_note = ""

    while True:
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
            return [p["el"] for p in picks] if len(picks) >= min_picks else None
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
        if anchor is not None and k == eid(anchor):
            forms.toast("That is the device the circuit continues from; the new conduit starts there.", title=TITLE)
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


def chain_items(run, connected):
    """([(element, info)] to address, [(element, info)] connected but not addressed), each element once."""
    items, passed, seen = [], [], set()
    for el in connected:
        k = eid(el)
        if k in seen:
            continue
        seen.add(k)
        info = run.classify(el)
        (items if info["addr"] else passed).append((el, info))
    return items, passed


# ---------------- choosing where the new devices connect ----------------

CANCELLED = object()
OPT_SELECT_START = "Select a device to continue from (insert after it)"


def choose_anchor(run, new):
    """The device the new conduit starts from, None for a new circuit, or CANCELLED."""
    new_ids = set(eid(e) for e in new)
    anchor = run.state.get("anchor")
    if anchor is not None:
        return anchor
    if not run.state["resumed"]:
        return None
    options = run.last_device_options()
    labels = [label for label, _dev in options] + [OPT_SELECT_START]
    devices = dict(options)
    while True:
        choice = forms.CommandSwitchWindow.show(
            labels, message="%s: where do the %d new device(s) connect?" % (run.circuit_text(), len(new)))
        if not choice:
            return CANCELLED
        if choice == OPT_SELECT_START:
            el = pick_addressed_device("Select the device on %s (or its tag) to continue from - the new devices "
                                       "go right after it. Esc to go back" % run.circuit_text())
            if el is None:
                continue
            if not run.on_circuit(el):
                forms.alert("That device is not on %s. Pick a device on the circuit." % run.circuit_text(),
                            title=TITLE)
                continue
        else:
            el = devices[choice]
        if eid(el) in new_ids:
            forms.alert("That device is one of the new devices you picked. Choose a different device to continue "
                        "from.", title=TITLE)
            continue
        run.set_anchor(el)
        return el


def is_conduit_fitting(el):
    try:
        return eid(el.Category.Id) == int(BuiltInCategory.OST_ConduitFitting)
    except Exception:
        return False


def run_between(a, start, b):
    """The conduit and fittings joining device a to device b, starting with the conduit `start` leaving a.
    Returns ([elements], None), or (None, reason) if they are not joined by plain conduit and fittings or the
    run splits between them (deleting it would cut off the other branch)."""
    a_id, b_id = eid(a), eid(b)
    type_id = eid(start.GetTypeId())
    parent, nodes = {eid(start): None}, {eid(start): start}
    frontier, found = [start], False
    while frontier and not found:
        following = []
        for el in frontier:
            for group in ct.connected_elements(el):
                for n in group:
                    k = eid(n)
                    if k == a_id or k in parent:
                        continue
                    if k == b_id:
                        parent[k] = eid(el)
                        found = True
                        continue
                    if isinstance(n, Conduit):
                        if eid(n.GetTypeId()) != type_id:
                            continue
                    elif not is_conduit_fitting(n):
                        continue    # a device, box or anything else: the run doesn't go through it
                    parent[k] = eid(el)
                    nodes[k] = n
                    following.append(n)
        frontier = following
    if not found:
        return None, ("they are not joined by conduit and fittings only (there may be a junction box or another "
                      "device between them, or conduit of another type)")
    path, k = [], parent[b_id]
    while k is not None:
        path.append(nodes[k])
        k = parent[k]
    for el in path:
        if not isinstance(el, Conduit) and len([g for g in ct.connected_elements(el) if g]) > 2:
            return None, "the conduit splits (a tee or cross fitting) between them"
    return path, None


def find_insert(run, anchor):
    """What comes after the anchor along the conduit.
    Returns (None, None) when nothing on the circuit is after it (the new devices extend the circuit),
    ({"next": device right after the anchor, "members": devices on the circuit after the anchor in order of
    connection, "path": conduit and fittings between the anchor and "next"}, None) to insert, or
    (None, reason) / (CANCELLED, None)."""
    sides = []
    for group in ct.connected_elements(anchor):
        c = None
        for n in group:
            if isinstance(n, Conduit):
                c = n
                break
        if c is None:
            continue
        order, problem = ct.follow(doc, anchor, c, nv.is_device)
        if problem or not order:
            continue
        members = [el for el in order if run.on_circuit(el)]
        signs = [run.compare(anchor, el) for el in members]
        sides.append({"conduit": c, "order": order, "members": members,
                      "before": -1 in signs, "after": 1 in signs})
    candidates = [sd for sd in sides if sd["members"] and not sd["before"]]
    if len(candidates) > 1 and len([sd for sd in candidates if sd["after"]]) == 1:
        candidates = [sd for sd in candidates if sd["after"]]
    if not candidates:
        return None, None
    side = candidates[0]
    if len(candidates) > 1:
        labels = {}
        for sd in candidates:
            first = sd["members"][0]
            labels["Toward element %d (%s), %d device(s) on %s" % (
                eid(first), run.downstream_info(first).get("old") or element_key(first), len(sd["members"]),
                run.circuit_text())] = sd
        choice = forms.CommandSwitchWindow.show(sorted(labels.keys()),
                                                message="Which way is downstream of the device you continue from?")
        if not choice:
            return CANCELLED, None
        side = labels[choice]
    nxt = side["order"][0]
    path, why = run_between(anchor, side["conduit"], nxt)
    if why:
        return None, ("The new devices can't be inserted between {} and {}: {}.\n\nPick a device on a straight "
                      "run of conduit to continue from.".format(element_label(anchor), element_label(nxt), why))
    return {"next": nxt, "members": side["members"], "path": path}, None


def unreached(run, anchor, ids):
    """Devices on the circuit that come after the anchor by number but were not found along the conduit."""
    out = []
    for el in all_devices():
        if eid(el) in ids or eid(el) == eid(anchor):
            continue
        if run.on_circuit(el) and run.compare(anchor, el) == 1:
            out.append(el)
    return out


# ---------------- report ----------------


def report(run, made_links, total_links, conduits_made, addressed, passed, notes):
    output.print_md("### Auto-Circuit: {} {}".format(run.name, run.circuit_text()))
    output.print_md("- {} ({})".format(run.circuit_text(), ("continued from %s" % run.state["from"])
                                       if run.state["resumed"] else "new"))
    output.print_md("- Conduit: {} of {} link(s) created, {} conduit segment(s)".format(
        made_links, total_links, conduits_made))
    output.print_md("- Devices addressed: **{}**".format(len(addressed)))
    for el, info, text in addressed:
        output.print_md("    - {} : {}".format(eid(el), run.preview_line(el, info, text)))
    for line in run.report_lines(addressed):
        output.print_md("- {}".format(line))
    if passed:
        output.print_md("- Connected but not addressed:")
        for el, info in passed:
            output.print_md("    - {} : {} ({})".format(eid(el), info["key"], info["why"]))
    output.print_md("- Routing preferences: `{}`".format(mounting_rules.rules_path()))
    for line in notes:
        output.print_md("- {}".format(line))
    for msg in run.problems:
        output.print_md("- Issue: {}".format(msg))


# ---------------- main ----------------


def main():
    # ---- 1. circuit type, 2. which circuit / loop (and limits) ----
    run = choose_circuit_type()
    if run is None or not run.setup():
        return

    # ---- 3. pick the new devices ----
    new = pick_chain(run, min_picks=1 if run.state["resumed"] else 2)
    if not new:
        return

    # ---- 4. where they connect: after the last device, or inserted after a device you pick ----
    anchor = choose_anchor(run, new)
    if anchor is CANCELLED:
        return
    insert = None
    if anchor is not None:
        new = [e for e in new if eid(e) != eid(anchor)]
        insert, why = find_insert(run, anchor)
        if insert is CANCELLED:
            return
        if why:
            forms.alert(why, title=TITLE)
            uidoc.Selection.SetElementIds(List[ElementId]([anchor.Id]))
            return
        if insert is not None:
            new_ids = set(eid(e) for e in new)
            if eid(insert["next"]) in new_ids or any(eid(m) in new_ids for m in insert["members"]):
                forms.alert("One of the new devices is already on {} after {}. Pick devices that aren't on the "
                            "circuit yet.".format(run.circuit_text(), element_label(anchor)), title=TITLE)
                return
            run.prepare_insert(anchor, insert["members"])
    chain = ([anchor] if anchor is not None else []) + new + ([insert["next"]] if insert else [])
    if not new or len(chain) < 2:
        forms.alert("There is nothing to connect.", title=TITLE)
        return

    # Everything from here on (removing the old run, moves, conduit, addresses) is one Undo; a cancel undoes it all.
    tg = TransactionGroup(doc, "Auto-Circuit")
    tg.Start()
    result = None
    try:
        result = build(run, chain, anchor, insert)
    except Exception as ex:
        forms.alert("Stopped by an unexpected error, so nothing was changed:\n\n{}".format(ex), title=TITLE)
        result = None
    finally:
        if result is not None:
            tg.Assimilate()
        else:
            tg.RollBack()
    if result is None:
        return
    if result.get("select") is not None:
        uidoc.Selection.SetElementIds(List[ElementId]([result["select"].Id]))
    report(run, *result["report"])


def build(run, chain, anchor, insert):
    """Removes the old run (insert), plans and creates the conduit and writes the addresses.
    Returns {"report": (...), "select": element or None} to keep the changes, or None to undo them all."""
    removed = 0
    if insert is not None:
        ids = List[ElementId]([e.Id for e in insert["path"]])
        error = commit(Transaction(doc, "Auto-Circuit: remove conduit for the insert"), lambda: doc.Delete(ids))
        if error:
            forms.alert("The conduit between {} and {} could not be removed: {}".format(
                element_label(anchor), element_label(insert["next"]), error), title=TITLE)
            return None
        removed = len(insert["path"])

    # ---- routing preferences: mounting + conduit type (Auto Conduit - Config) ----
    rules = mounting_rules.load_rules()
    walls = set(eid(e) for e in chain
                if mounting_rules.get_mounting_for_element(e, rules) == mounting_rules.WALL)
    fixed = set(eid(e) for e in ([anchor, insert["next"]] if insert else []))   # can't be skipped

    n = len(chain)
    need = {}
    for i, e in enumerate(chain):
        need[eid(e)] = need.get(eid(e), 0) + (1 if i in (0, n - 1) else 2)

    skip = set()
    fallback = set()
    checked = set()
    for e in chain:
        k = eid(e)
        if k not in walls or k in checked:
            continue
        checked.add(k)
        if free_top_count(e) >= need[k]:
            continue
        if k in fixed:
            fallback.add(k)
            continue
        choice = forms.alert(
            "Wall device {} has {} unconnected top Conduit connector(s) but needs {}.\n\n"
            "Skip this device (it is not connected or addressed), or use its closest available "
            "connector(s)?".format(element_label(e), free_top_count(e), need[k]),
            title=TITLE, options=[OPT_CLOSEST, OPT_SKIP])
        if not choice:
            return None
        if choice == OPT_SKIP:
            skip.add(k)
        else:
            fallback.add(k)

    seq = []
    for e in chain:
        if eid(e) in skip:
            continue
        if seq and eid(seq[-1]) == eid(e):
            continue
        seq.append(e)
    if len(seq) < 2:
        forms.alert("Fewer than two elements remain after skipping devices.", title=TITLE)
        return None

    link_types, missing = resolve_link_types(seq, rules)
    if missing:
        forms.alert("These conduit types from Auto Conduit - Config were not found in this project:\n\n{}\n\n"
                    "Runs using them will use the default conduit type instead.".format("\n".join(missing)),
                    title=TITLE)
    if any(t is None for t in link_types):
        default_type = choose_default_type()
        if default_type is None:
            return None
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
        return None

    offset = None
    while offset is None:
        txt = forms.ask_for_string(default=DEFAULT_ELEVATION_TEXT,
                                   prompt="Conduit elevation above '{}':".format(level.Name),
                                   title="Auto-Circuit - Conduit Elevation")
        if txt is None:
            return None
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
        if partial and insert is None:
            options.append(OPT_SKIP_DEV)
            text += ("\n\n'{}' creates the {} link(s) before it and addresses only the devices they "
                     "connect.".format(OPT_SKIP_DEV, len(partial)))
        if moves:
            options.append(OPT_ADJUST)
            text += ("\n\n'{}' moves the second device {} so it lines up with the first, "
                     "then plans the chain again.".format(OPT_ADJUST, moves[0][1]))
        options.append(OPT_CANCEL_CHAIN)
        if insert is not None:
            text += ("\n\nAn insert has to reconnect to {}, so the chain can't stop early; Cancel puts the removed "
                     "conduit back.".format(element_label(insert["next"])))
        text += "\n\nThe second device is left selected so you can find it."
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
        return None
    print_debug(z_target)

    # ---- 6. number the devices (new ones, then everything after them when inserting) and confirm ----
    def items_for(connected_links):
        connected = seq[:connected_links + 1]
        if insert is not None:
            connected = [e for e in connected if eid(e) != eid(insert["next"])]
        items, passed = chain_items(run, connected)
        if insert is not None:
            seen = set(eid(e) for e, _i in items + passed)
            for m in insert["members"]:
                if eid(m) in seen:
                    continue
                seen.add(eid(m))
                info = run.downstream_info(m)
                if info["addr"]:
                    items.append((m, info))
                else:
                    passed.append((m, info))
        return items, passed

    items, passed = items_for(len(plan))
    planned, error = run.plan(items)
    if error:
        forms.alert("The devices can't be addressed: {}\n\nNothing was changed.".format(error), title=TITLE)
        return None
    new_ids = set(eid(e) for e in chain[1:-1]) if insert else set()
    lines = [run.preview_line(el, info, text) for el, info, text in planned[:PREVIEW_LIMIT]]
    if len(planned) > PREVIEW_LIMIT:
        lines.append("... and {} more".format(len(planned) - PREVIEW_LIMIT))
    if not planned:
        lines.append("(no devices on the chain take a {} address)".format(run.name))
    notes = run.confirm_notes(planned) if planned else []
    if insert is not None:
        notes.insert(0, "Inserts after {}: the conduit to {} ({} conduit / fitting element(s)) is replaced and "
                        "the {} device(s) after it on the conduit are renumbered.".format(
                            element_label(anchor), element_label(insert["next"]), removed,
                            len([1 for e, _i, _t in planned if eid(e) not in new_ids])))
        missed = unreached(run, anchor, set(eid(e) for e, _i, _t in planned))
        if missed:
            notes.append("{} device(s) on {} come after it by number but are not on this conduit run, so they "
                         "keep their addresses (they may now duplicate): elements {}.".format(
                             len(missed), run.circuit_text(), ", ".join(str(eid(e)) for e in missed[:10])))
    if passed:
        notes.append("{} element(s) on the chain are connected but not addressed (see the report).".format(
            len(passed)))
    go_on = forms.alert("Create {} conduit link(s) and address {} device(s) on {}?\n\n{}\n\n{}".format(
        len(plan), len(planned), run.circuit_text(), "\n".join(lines), "\n".join(notes)),
        title=TITLE, yes=True, no=True)
    if not go_on:
        return None

    # ---- 7. create the conduit, address, finish (EOL) ----
    made_links = 0
    conduits = []
    failure = None
    addressed = []
    for i, o in enumerate(plan):
        try:
            conduits.extend(create_link(o["a"], o["b"], o["pts"], link_types[i], level.Id))
        except Exception as ex:
            failure = "Link {} of {} failed while creating conduit: {}".format(i + 1, total_links, ex)
            break
        made_links += 1
    if made_links == 0 or (failure and insert is not None):
        forms.alert("{}\n\nNothing was changed.".format(failure or "No conduit was created."), title=TITLE)
        return None
    if made_links < len(plan):
        items, passed = items_for(made_links)   # only the devices that were connected
        planned, error = run.plan(items)
    if planned:
        error = run.write(planned, conduits)
        if error:
            run.problems.append("Nothing was addressed: {}".format(error))
        else:
            addressed = planned
            try:
                run.finish()
            except Exception as ex:
                run.problems.append("EOL parameters were not set: {}".format(ex))

    notes = []
    if insert is not None:
        notes.append("Inserted after {}; removed {} conduit / fitting element(s) to {}.".format(
            element_label(anchor), removed, element_label(insert["next"])))
    if failure:
        notes.append(failure)
    if culprit is not None:
        notes.append("{} could not be connected and is now selected; the devices after it were not connected "
                     "or addressed.".format(element_label(culprit)))
    return {"report": (made_links, total_links, len(conduits), addressed, passed, notes), "select": culprit}


main()
