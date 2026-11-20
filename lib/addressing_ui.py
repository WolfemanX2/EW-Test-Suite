# -*- coding: utf-8 -*-
# addressing_ui module - version v1
# Change log (last change first):
#   v1 - Code consolidation step 5 (Address SLC v9, Auto-Circuit v9): the windows and menus the addressing tools share,
#        moved here from Address SLC, nac_voice_addressing and Auto-Circuit (which had copies of them).
"""Windows and menus shared by the addressing tools (Address SLC, Address NAC / Voice, Auto-Circuit).

FROM_SELECTED / NEW_CIRCUIT / FROM_EXISTING   the three choices every addressing tool starts with
choose               one of a list of choices: buttons, or a searchable list when there are many
preselected_device   the one device selected (directly or by its tag) when a tool starts
NewLoopDialog        N#, L# and the starting module / detector numbers of a new SLC loop
CountDialog          how many SLC addresses to fill on a device, and which kind
NewCircuitDialog     power supply, circuit and starting device number of a new NAC / Voice circuit"""
from pyrevit import forms

import slc_addressing as slc
import nac_voice_types as nv
import ew_common as ec        # shared helpers (lib/ew_common.py)

FROM_SELECTED = "Continue from Selected"
NEW_CIRCUIT = "New Circuit"
FROM_EXISTING = "Continue from Existing Circuit"
BUTTON_LIMIT = 10   # more choices than this -> searchable list instead of buttons


def _xml(text):
    """Text made safe for a XAML attribute."""
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;"))


# ---------- Menus ----------
def choose(options, message):
    """One of options, or None. Buttons for a short list, a searchable list for a long one."""
    if len(options) > BUTTON_LIMIT:
        return forms.SelectFromList.show(options, title=message, button_name="Select", multiselect=False)
    return forms.CommandSwitchWindow.show(options, message=message)


def preselected_device(doc, uidoc):
    """The one device selected (directly or by its tag) when the tool was started, or None (nothing
    selected, or more than one device)."""
    devices = {}
    try:
        for eid in uidoc.Selection.GetElementIds():
            el = ec.resolve_device(doc.GetElement(eid))
            if el is not None:
                devices[ec.eid_int(el.Id)] = el
    except Exception:
        return None
    return list(devices.values())[0] if len(devices) == 1 else None


# ---------- New SLC loop ----------
NEW_LOOP_XAML = """
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="__TITLE__"
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
            <Button Content="__CANCEL__" Width="80" IsCancel="True" Click="cancel_click"/>
        </StackPanel>
    </StackPanel>
</Window>
"""


class NewLoopDialog(forms.WPFWindow):
    """N#, L# and the two starting numbers for a new loop, asked in one window.
    self.result = (n, l, start module, start detector), or None if cancelled.
    title: the window title; cancel_text: the cancel button ('Cancel' in Address SLC, 'Back' in Auto-Circuit)."""
    def __init__(self, title="Address SLC - New Loop", cancel_text="Cancel"):
        xaml = NEW_LOOP_XAML.replace("__TITLE__", _xml(title)).replace("__CANCEL__", _xml(cancel_text))
        forms.WPFWindow.__init__(self, xaml, literal_string=True)
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


# ---------- SLC address count ----------
COUNT_XAML = """
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="__TITLE__"
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
            <Button Content="__SKIP__" Width="__SKIP_WIDTH__" IsCancel="True" Click="skip_click"/>
        </StackPanel>
    </StackPanel>
</Window>
"""


class CountDialog(forms.WPFWindow):
    """Asks how many addresses to fill on the picked device and, when allowed, which kind.
    choices = [(label or None, count)]; a label makes it a named Address Option.
    self.result = (count, kind, label or None), or None if the device is skipped.
    title / skip_text / skip_width: the window title and the skip button ('Skip Device' in Address SLC,
    'Don\'t Address' in Auto-Circuit)."""
    def __init__(self, message, choices, default_count, default_kind, lock_kind, count_label,
                 title="Address SLC", skip_text="Skip Device", skip_width=90):
        xaml = (COUNT_XAML.replace("__TITLE__", _xml(title)).replace("__SKIP__", _xml(skip_text))
                .replace("__SKIP_WIDTH__", str(skip_width)))
        forms.WPFWindow.__init__(self, xaml, literal_string=True)
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


# ---------- New NAC / Voice circuit ----------
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
    self.result = (source, circuit, start), or None if the user went back.
    tool_title: the tool's name, shown in the window title."""
    def __init__(self, kind, existing, tool_title):
        forms.WPFWindow.__init__(self, NEW_CIRCUIT_XAML, literal_string=True)
        self.kind = kind
        self.existing = existing
        self.result = None
        name = nv.KIND_NAMES[kind]
        self.Title = "%s - new %s circuit" % (tool_title, name)
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
