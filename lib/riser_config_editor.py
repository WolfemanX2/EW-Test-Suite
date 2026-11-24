# -*- coding: utf-8 -*-
# riser_config_editor module - version v7
# Change log (last change first):
#   v7 - Riser - Config v13: Circuit label offset (ft) and Line end (Text, or a loaded Generic Annotation type).
#   v6 - Riser - Config v12: each riser tab has a Panel detail family box - the detail item family drawn for the
#        head end (picked from the loaded Detail Item families, or typed).
#   v5 - Riser - Config v11: the Address Callouts help says where callouts now go (a band below the address text,
#        joined to the device by detail lines) and that their origin should be the top of the callout.
#   v4 - Riser - Config v10: fixed 'Cannot import name Visibility' when the window opened (the WPF assembly is now
#        loaded here instead of relying on pyRevit having loaded it first); messages use ew_common.alert.
#   v3 - Riser - Config v9: the Rules column and its window are gone (a type is always drawn with its own symbols);
#        the SLC tab shows each type's Address Group (Family Defaults Config) and an Address Callouts table - a
#        callout symbol per Address Group subgroup, used on the riser instead of the 45 degree address text.
#        Messages use pyRevit option bars / plain boxes instead of the warning popup.
"""The Riser - Config window: one tab per riser (SLC Riser, NAC Riser), laid out like Family Defaults Config.

Each tab has the riser's drawing settings (view scale, spacing, devices per line, wrap rounding, address text
offset) and its table of the symbols drawn for each Family : Type (in order, one address under each, the last
takes the rest). A device's addresses are written under it as 45 degree text. On a tab whose store has
ADDRESS_CALLOUTS (SLC Riser), a type's Address Group from Family Defaults Config is shown, and the Address Callouts
table gives each Address Group subgroup an optional callout symbol: a device of that subgroup (worked out from its
number of addresses) is labeled with the callout instead, its parameters filled from the device's same-named ones.

A tab reads and writes its riser's own files through a store module with load_table, save_table, table_path,
load_settings, save_settings, settings_path, DEFAULT_SETTINGS, SETTING_LIMITS, SCALES and ADDRESS_CALLOUTS:
    SLC Riser  lib/slc_riser.py   riser_symbols.json / riser_settings.json (callouts in the settings file)
    NAC Riser  lib/nac_riser.py   nac_riser_symbols.json / nac_riser_settings.json
To add a riser (e.g. Voice), add a (header, prefix, store) line to TABS.

show_editor() opens the window."""
import clr
clr.AddReference("System.Data")
clr.AddReference("PresentationCore")        # System.Windows.Visibility (loaded here, not left to pyRevit)
clr.AddReference("PresentationFramework")

from System import String, DBNull
from System.Data import DataTable, DataRowState
from Autodesk.Revit.DB import FilteredElementCollector, BuiltInCategory
from pyrevit import revit, forms
from System.Windows import Visibility
from System.Windows.Controls import TextChangedEventHandler
from System.Windows.Controls.Primitives import TextBoxBase

import slc_riser as sr     # SLC Riser's files, and the table entries / symbols / callouts shared by the risers
import nac_riser           # NAC Riser's files
import circuit_config as cc    # Family Defaults Config: each type's Address Group and the groups' subgroups
import ew_common as ec        # shared helpers: alert without the warning sound (lib/ew_common.py)

doc = revit.doc
TITLE = "Riser - Config"
TABS = [("SLC Riser", "slc_", sr), ("NAC Riser", "nac_", nac_riser)]     # (tab header, name prefix, store)
SCOPES = [("Fire Alarm Device types", BuiltInCategory.OST_FireAlarmDevices),
          ("Electrical Equipment types (panels)", BuiltInCategory.OST_ElectricalEquipment)]
TEXT_LABEL = "(45 degree address text)"     # the Address Callouts table when a subgroup has no callout
CLOSE_ANYWAY = "Close Without Saving"
KEEP_EDITING = "Keep Editing"


def note(msg):
    """A message box without the warning icon and sound."""
    ec.alert(msg, title=TITLE)


END_TEXT = "Text (SLC RETURN / NAC RETURN)"


def generic_annotation_types():
    """'Family : Type' of the Generic Annotation types loaded in the project, sorted."""
    names = set()
    for s in (FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_GenericAnnotation)
              .WhereElementIsElementType().ToElements()):
        try:
            names.add(sr.type_key(s))
        except Exception:
            pass
    return sorted(names, key=lambda n: n.upper())


def detail_families():
    """Names of the Detail Item families loaded in the project, sorted."""
    names = set()
    for s in (FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_DetailComponents)
              .WhereElementIsElementType().ToElements()):
        try:
            names.add(s.FamilyName)
        except Exception:
            pass
    return sorted(names, key=lambda n: n.upper())


def cell_text(v):
    if v is None or isinstance(v, DBNull):
        return ""
    return str(v).strip()


def loaded_type_keys(category):
    keys = set()
    for s in FilteredElementCollector(doc).OfCategory(category).WhereElementIsElementType().ToElements():
        try:
            keys.add(sr.type_key(s))
        except Exception:
            pass
    return keys


SEP = "  >  "      # between the symbols of one type, in the table


SYMBOL_LIST_XAML = """
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Riser Symbols"
        Width="820" Height="520" MinWidth="640" MinHeight="380"
        WindowStartupLocation="CenterScreen">
    <Grid Margin="12">
        <Grid.RowDefinitions>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="*"/>
            <RowDefinition Height="Auto"/>
        </Grid.RowDefinitions>
        <Grid.ColumnDefinitions>
            <ColumnDefinition Width="*"/>
            <ColumnDefinition Width="Auto"/>
            <ColumnDefinition Width="*"/>
            <ColumnDefinition Width="Auto"/>
        </Grid.ColumnDefinitions>

        <TextBlock x:Name="title_text" Grid.Row="0" Grid.ColumnSpan="4" TextWrapping="Wrap" Margin="0,0,0,8"/>

        <DockPanel Grid.Row="1" Grid.Column="0">
            <TextBox x:Name="filter_box" DockPanel.Dock="Top" Margin="0,0,0,4" TextChanged="filter_changed"
                     ToolTip="Filter the loaded symbols"/>
            <ListBox x:Name="available_list" SelectionMode="Extended" MouseDoubleClick="add_click"/>
        </DockPanel>

        <StackPanel Grid.Row="1" Grid.Column="1" VerticalAlignment="Center" Margin="8,0">
            <Button Content="Add &gt;" Width="80" Margin="0,0,0,6" Click="add_click"/>
            <Button Content="&lt; Remove" Width="80" Click="remove_click"/>
        </StackPanel>

        <DockPanel Grid.Row="1" Grid.Column="2">
            <TextBlock DockPanel.Dock="Top" Text="Drawn in this order:" Margin="0,0,0,4"/>
            <ListBox x:Name="chosen_list" SelectionMode="Single" MouseDoubleClick="remove_click"/>
        </DockPanel>

        <StackPanel Grid.Row="1" Grid.Column="3" VerticalAlignment="Center" Margin="8,0,0,0">
            <Button Content="Move Up" Width="80" Margin="0,0,0,6" Click="up_click"/>
            <Button Content="Move Down" Width="80" Click="down_click"/>
        </StackPanel>

        <DockPanel Grid.Row="2" Grid.ColumnSpan="4" Margin="0,10,0,0" LastChildFill="False">
            <Button Content="Cancel" Width="80" IsCancel="True" Click="cancel_click" DockPanel.Dock="Right"/>
            <Button Content="OK" Width="80" Margin="0,0,8,0" IsDefault="True" Click="ok_click" DockPanel.Dock="Right"/>
        </DockPanel>
    </Grid>
</Window>
"""


class SymbolListEditor(forms.WPFWindow):
    """Choose symbols, in order. self.result = [symbols] or None."""
    def __init__(self, title, symbols, current):
        forms.WPFWindow.__init__(self, SYMBOL_LIST_XAML, literal_string=True)
        self.all_symbols = list(symbols)
        self.result = None
        self.title_text.Text = ("Riser symbols for %s, in the order they are drawn. Each symbol gets one of the "
                                "device's addresses and the last symbol takes the rest. A symbol can be added "
                                "more than once." % title)
        self.available_list.ItemsSource = self.all_symbols
        for sym in current:
            self.chosen_list.Items.Add(sym)

    def filter_changed(self, sender, args):
        text = (self.filter_box.Text or "").strip().lower()
        self.available_list.ItemsSource = [x for x in self.all_symbols if text in x.lower()]

    def add_click(self, sender, args):
        for sym in list(self.available_list.SelectedItems):
            self.chosen_list.Items.Add(sym)

    def remove_click(self, sender, args):
        i = self.chosen_list.SelectedIndex
        if i >= 0:
            self.chosen_list.Items.RemoveAt(i)
            self.chosen_list.SelectedIndex = min(i, self.chosen_list.Items.Count - 1)

    def _move(self, step):
        i = self.chosen_list.SelectedIndex
        j = i + step
        if i < 0 or j < 0 or j >= self.chosen_list.Items.Count:
            return
        sym = self.chosen_list.Items[i]
        self.chosen_list.Items.RemoveAt(i)
        self.chosen_list.Items.Insert(j, sym)
        self.chosen_list.SelectedIndex = j

    def up_click(self, sender, args):
        self._move(-1)

    def down_click(self, sender, args):
        self._move(1)

    def ok_click(self, sender, args):
        self.result = [str(x) for x in self.chosen_list.Items]
        self.Close()

    def cancel_click(self, sender, args):
        self.Close()


number_text = sr.number_text      # 4.5 -> '4.5', 6.0 -> '6' (lib/slc_riser.py)


TAB_XAML = """
            <TabItem Header="PFX_HEADER">
                <Grid Margin="8">
                    <Grid.RowDefinitions>
                        <RowDefinition Height="Auto"/>
                        <RowDefinition Height="Auto"/>
                        <RowDefinition Height="*"/>
                    </Grid.RowDefinitions>

                    <GroupBox Grid.Row="0" Header="PFX_HEADER drawing" Margin="0,0,0,10" Padding="8">
                        <Grid>
                            <Grid.ColumnDefinitions>
                                <ColumnDefinition Width="Auto"/>
                                <ColumnDefinition Width="150"/>
                                <ColumnDefinition Width="32"/>
                                <ColumnDefinition Width="Auto"/>
                                <ColumnDefinition Width="90"/>
                                <ColumnDefinition Width="*"/>
                            </Grid.ColumnDefinitions>
                            <Grid.RowDefinitions>
                                <RowDefinition Height="Auto"/>
                                <RowDefinition Height="Auto"/>
                                <RowDefinition Height="Auto"/>
                                <RowDefinition Height="Auto"/>
                                <RowDefinition Height="Auto"/>
                            </Grid.RowDefinitions>
                            <TextBlock Grid.Row="4" Grid.Column="0" Text="Circuit label offset (ft):" VerticalAlignment="Center" Margin="0,6,8,0"
                                       ToolTip="How far right of the start of the one-line the circuit label (A, N1-2) and its line down sit, in feet in the view."/>
                            <TextBox x:Name="PFX_label_x_box" Grid.Row="4" Grid.Column="1" Margin="0,6,0,0"/>
                            <TextBlock Grid.Row="4" Grid.Column="3" Text="Line end:" VerticalAlignment="Center" Margin="0,6,8,0"
                                       ToolTip="What goes at the end of each one-line: the riser's end text (SLC RETURN / NAC RETURN), or a Generic Annotation (its origin goes on the end of the line)."/>
                            <ComboBox x:Name="PFX_end_box" Grid.Row="4" Grid.Column="4" Grid.ColumnSpan="2" Margin="0,6,0,0"
                                      IsEditable="False"/>
                            <TextBlock Grid.Row="3" Grid.Column="0" Text="Panel detail family:" VerticalAlignment="Center" Margin="0,6,8,0"
                                       ToolTip="The Detail Item family drawn for the head end panel on this riser (its Panel #, Location, reference lines and Loop Spacing parameters are used)."/>
                            <ComboBox x:Name="PFX_panel_family_box" Grid.Row="3" Grid.Column="1" Grid.ColumnSpan="4" Margin="0,6,0,0"
                                      IsEditable="True"
                                      ToolTip="Pick a loaded Detail Item family, or type the family name."/>
                            <TextBlock Grid.Row="0" Grid.Column="0" Text="Drafting view scale:" VerticalAlignment="Center" Margin="0,0,8,6"/>
                            <ComboBox x:Name="PFX_scale_box" Grid.Row="0" Grid.Column="1" Margin="0,0,0,6" IsEditable="False"/>
                            <TextBlock Grid.Row="0" Grid.Column="3" Text="Spacing between devices (ft):" VerticalAlignment="Center" Margin="0,0,8,6"/>
                            <TextBox x:Name="PFX_spacing_box" Grid.Row="0" Grid.Column="4" Margin="0,0,0,6"/>
                            <TextBlock Grid.Row="1" Grid.Column="0" Text="Devices before wrapping:" VerticalAlignment="Center" Margin="0,0,8,0"/>
                            <TextBox x:Name="PFX_per_line_box" Grid.Row="1" Grid.Column="1" Margin="0,0,0,6"/>
                            <TextBlock Grid.Row="1" Grid.Column="3" Text="Address text below line (in):" VerticalAlignment="Center" Margin="0,0,8,6"/>
                            <TextBox x:Name="PFX_offset_box" Grid.Row="1" Grid.Column="4" Margin="0,0,0,6"/>
                            <TextBlock Grid.Row="2" Grid.Column="0" Text="Wrap rounding (devices):" VerticalAlignment="Center" Margin="0,0,8,0"
                                       ToolTip="A line only wraps when it would have more than Devices before wrapping + this many devices. 40 and 5: 41 to 45 devices stay on one line."/>
                            <TextBox x:Name="PFX_rounding_box" Grid.Row="2" Grid.Column="1"
                                     ToolTip="A line only wraps when it would have more than Devices before wrapping + this many devices. 40 and 5: 41 to 45 devices stay on one line."/>
                            <TextBlock Grid.Row="2" Grid.Column="3" Grid.ColumnSpan="2" VerticalAlignment="Center" Margin="0,0,8,0"
                                       Foreground="Gray" TextWrapping="Wrap"
                                       Text="Wraps only past Devices before wrapping + rounding."/>
                            <Button x:Name="PFX_defaults_btn" Grid.Row="2" Grid.Column="5" Content="Defaults" Width="80" HorizontalAlignment="Right"/>
                        </Grid>
                    </GroupBox>

                    <TextBlock Grid.Row="1" TextWrapping="Wrap" Margin="0,0,0,8"
                               Text="Choose the symbols drawn on PFX_HEADER diagrams for each Family Type, in order (one address under each, the last symbol takes the rest). Double-click a Symbols cell (or use the buttons) to edit. Symbols are the Generic Annotation and Detail Item types loaded in this project. Type in the blank bottom row to add an entry (Family : Type, exactly as Revit shows it). Addresses are written under the device as 45 degree text, unless its Address Group subgroup has a callout (right)."/>

                    <Grid Grid.Row="2">
                        <Grid.ColumnDefinitions>
                            <ColumnDefinition Width="*"/>
                            <ColumnDefinition Width="Auto"/>
                        </Grid.ColumnDefinitions>
                        <DockPanel Grid.Column="0">
                            <DockPanel DockPanel.Dock="Bottom" Margin="0,10,0,0" LastChildFill="False">
                                <Button x:Name="PFX_add_btn" Content="Add Types From Project..." Width="170" Margin="0,0,8,0" DockPanel.Dock="Left"/>
                                <Button x:Name="PFX_set_btn" Content="Set Symbols For Selected..." Width="180" Margin="0,0,8,0" DockPanel.Dock="Left"/>
                                <Button x:Name="PFX_delete_btn" Content="Delete Selected Rows" Width="140" DockPanel.Dock="Left"/>
                            </DockPanel>
                            <DataGrid x:Name="PFX_grid"
                                      AutoGenerateColumns="False"
                                      CanUserAddRows="True" CanUserDeleteRows="True"
                                      SelectionMode="Extended" SelectionUnit="FullRow"
                                      GridLinesVisibility="All" HeadersVisibility="Column">
                                <DataGrid.Columns>
                                    <DataGridTextColumn Header="Family Type"
                                                        Binding="{Binding FamilyType}" Width="*"/>
                                    <DataGridTextColumn Header="Symbols (in order)"
                                                        Binding="{Binding Symbol}" IsReadOnly="True" Width="1.2*"/>
                                    <DataGridTextColumn Header="Address Group (Family Defaults)"
                                                        Binding="{Binding AddressGroup}" IsReadOnly="True" Width="0.8*"/>
                                </DataGrid.Columns>
                            </DataGrid>
                        </DockPanel>

                        <GroupBox x:Name="PFX_callout_box" Grid.Column="1" Width="460" Margin="12,0,0,0" Padding="6"
                                  Header="Address Callouts (by Address Group subgroup)">
                            <DockPanel>
                                <TextBlock DockPanel.Dock="Top" TextWrapping="Wrap" Margin="0,0,0,6"
                                           Text="A device whose type has this Address Group in Family Defaults Config, with this many addresses, is labeled with the callout symbol instead of the 45 degree address text. The callouts go in a band below the bottom of the line's address text, each joined to its device by detail lines (down, across, down) and moved right if it would overlap the one before; build them as Generic Annotations with their origin at the top of the callout. Their parameters are filled from the device's parameters with the same names (SLC Address ... SLC Address 24, Panel #, ...). The groups and subgroups come from Family Defaults Config."/>
                                <DockPanel DockPanel.Dock="Bottom" Margin="0,8,0,0" LastChildFill="False">
                                    <Button x:Name="PFX_callout_set_btn" Content="Set Callout For Selected..." Width="170" Margin="0,0,8,0" DockPanel.Dock="Left"/>
                                    <Button x:Name="PFX_callout_text_btn" Content="Use 45 Degree Text" Width="130" DockPanel.Dock="Left"/>
                                </DockPanel>
                                <DataGrid x:Name="PFX_callout_grid" AutoGenerateColumns="False" IsReadOnly="True"
                                          CanUserAddRows="False" CanUserDeleteRows="False"
                                          SelectionMode="Extended" SelectionUnit="FullRow"
                                          GridLinesVisibility="All" HeadersVisibility="Column">
                                    <DataGrid.Columns>
                                        <DataGridTextColumn Header="Address Group" Binding="{Binding Group}" Width="*"/>
                                        <DataGridTextColumn Header="Subgroup" Binding="{Binding Subgroup}" Width="*"/>
                                        <DataGridTextColumn Header="Addresses" Binding="{Binding Count}" Width="70"/>
                                        <DataGridTextColumn Header="Callout" Binding="{Binding Shown}" Width="1.4*"/>
                                    </DataGrid.Columns>
                                </DataGrid>
                            </DockPanel>
                        </GroupBox>
                    </Grid>
                </Grid>
            </TabItem>
"""

WINDOW_XAML = """
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Riser - Config"
        Width="1250" Height="740" MinWidth="760" MinHeight="520"
        WindowStartupLocation="CenterScreen"
        Closing="window_closing">
    <Grid Margin="12">
        <Grid.RowDefinitions>
            <RowDefinition Height="*"/>
            <RowDefinition Height="Auto"/>
        </Grid.RowDefinitions>
        <TabControl x:Name="tabs" Grid.Row="0">
TAB_ITEMS
        </TabControl>
        <DockPanel Grid.Row="1" Margin="0,10,0,0" LastChildFill="False">
            <TextBlock x:Name="status_text" VerticalAlignment="Center" DockPanel.Dock="Left"/>
            <Button Content="Close" Width="80" Click="close_click" DockPanel.Dock="Right"/>
            <Button Content="Save" Width="80" Margin="0,0,8,0" Click="save_click" DockPanel.Dock="Right"/>
        </DockPanel>
    </Grid>
</Window>
"""


def window_xaml():
    items = "".join(TAB_XAML.replace("PFX_HEADER", header).replace("PFX_", prefix) for header, prefix, _ in TABS)
    return WINDOW_XAML.replace("TAB_ITEMS", items)


def _text_table(name, columns):
    table = DataTable(name)
    for column in columns:
        col = table.Columns.Add(column, clr.GetClrType(String))
        col.DefaultValue = ""
    return table


def _live(table):
    for row in table.Rows:
        if row.RowState != DataRowState.Deleted:
            yield row


class RiserTab(object):
    """One riser's tab: its drawing settings, symbol table and (SLC) address callouts, read from and saved to its
    store's files."""
    def __init__(self, window, header, prefix, store):
        self.w = window
        self.name = header
        self.p = prefix
        self.store = store
        self._loading = True
        self.settings_dirty = False
        self.failed = False     # its table couldn't be read: the tab is shown empty and never saved
        self.callouts_on = bool(getattr(store, "ADDRESS_CALLOUTS", False))
        self.cfg = None         # Family Defaults Config (Address Groups), read for the callouts
        self.extra_callouts = {}    # saved callouts for groups / subgroups no longer in Family Defaults (kept)

        try:
            table = store.load_table()
        except Exception as ex:
            note("Could not read the %s symbol table, so the %s tab can't be changed:\n%s\n\nPath: %s"
                 % (header, header, ex, store.table_path()))
            table, self.failed = {}, True
        try:
            settings = store.load_settings()
        except Exception as ex:
            note("Could not read the %s drawing settings, so the defaults are shown:\n%s\n\nPath: %s"
                 % (header, ex, store.settings_path()))
            settings = dict(store.DEFAULT_SETTINGS)
        callouts = settings.get(sr.CALLOUTS) or {}
        if self.callouts_on:
            try:
                self.cfg = cc.load()
            except Exception as ex:
                note("Could not read Family Defaults Config, so the Address Groups can't be shown on the %s tab:"
                     "\n%s\n\nThe saved callouts are kept." % (header, ex))
                self.cfg = None

        self.c("scale_box").ItemsSource = [label for label, _ in store.SCALES]
        self._show_settings(settings)

        # Symbols loaded now, plus any saved ones that aren't loaded in this project (so they aren't lost).
        saved = set()
        for entry in table.values():
            saved.update(entry["symbols"])
        for subs in callouts.values():
            saved.update(subs.values())
        self.symbols = sorted(set(sr.available_symbols(doc).keys()) | saved)

        self.dt = _text_table("RiserSymbols", ("FamilyType", "Symbol", "AddressGroup"))
        for key in sorted(table.keys()):
            self._add_row(key, table[key]["symbols"])
        self.dt.AcceptChanges()
        self.c("grid").ItemsSource = self.dt.DefaultView
        self.count = len(table)

        self.dt_callouts = _text_table("AddressCallouts", ("Group", "Subgroup", "Count", "Symbol", "Shown"))
        self._fill_callouts(callouts)
        self.c("callout_grid").ItemsSource = self.dt_callouts.DefaultView
        if not self.callouts_on:
            self.c("callout_box").Visibility = Visibility.Collapsed
            self.c("grid").Columns[2].Visibility = Visibility.Collapsed

        # Events (wired here, so each tab's controls call their own tab).
        self.c("panel_family_box").ItemsSource = detail_families()
        self.end_choices = [END_TEXT] + generic_annotation_types()
        self.c("end_box").ItemsSource = self.end_choices
        self.c("end_box").SelectionChanged += self.setting_changed
        self.c("label_x_box").TextChanged += self.setting_changed
        self.c("panel_family_box").AddHandler(TextBoxBase.TextChangedEvent,
                                              TextChangedEventHandler(self.setting_changed))
        self.c("panel_family_box").SelectionChanged += self.setting_changed
        self.c("scale_box").SelectionChanged += self.setting_changed
        for name in ("spacing_box", "per_line_box", "offset_box", "rounding_box"):
            self.c(name).TextChanged += self.setting_changed
        self.c("defaults_btn").Click += self.defaults_click
        self.c("grid").MouseDoubleClick += self.grid_double_click
        self.c("add_btn").Click += self.add_click
        self.c("set_btn").Click += self.set_click
        self.c("delete_btn").Click += self.delete_click
        self.c("callout_grid").MouseDoubleClick += self.callout_set_click
        self.c("callout_set_btn").Click += self.callout_set_click
        self.c("callout_text_btn").Click += self.callout_text_click
        if self.failed:
            for name in ("grid", "defaults_btn", "add_btn", "set_btn", "delete_btn", "scale_box", "spacing_box",
                         "per_line_box", "offset_box", "rounding_box", "panel_family_box", "label_x_box",
                         "end_box", "callout_grid",
                         "callout_set_btn",
                         "callout_text_btn"):
                self.c(name).IsEnabled = False
        self._loading = False

    def c(self, name):
        """This tab's control with that name."""
        return getattr(self.w, self.p + name)

    def status(self, text):
        self.w.status_text.Text = "%s: %s" % (self.name, text)

    # ---- Drawing settings ----
    def _show_settings(self, settings):
        self._loading = True
        scales = self.store.SCALES
        scale = settings["view_scale"]
        labels = [label for label, num in scales if num == scale]
        if not labels:     # a scale saved by hand that isn't in the list
            label = "1 : %d" % scale
            self.c("scale_box").ItemsSource = [l for l, _ in scales] + [label]
            labels = [label]
        self.c("scale_box").SelectedItem = labels[0]
        self.c("spacing_box").Text = number_text(settings["device_spacing_ft"])
        self.c("per_line_box").Text = number_text(settings["devices_per_line"])
        self.c("rounding_box").Text = number_text(settings["wrap_rounding"])
        self.c("offset_box").Text = number_text(settings["label_offset_in"])
        self.c("panel_family_box").Text = settings.get(sr.PANEL_FAMILY_KEY) or sr.DEFAULT_PANEL_FAMILY
        self.c("label_x_box").Text = number_text(settings.get("label_offset_x_ft",
                                                             sr.DEFAULT_SETTINGS["label_offset_x_ft"]))
        end = settings.get(sr.END_SYMBOL_KEY) or ""
        if end and end not in self.end_choices:     # saved, but not loaded in this project: keep it
            self.end_choices = self.end_choices + [end]
            self.c("end_box").ItemsSource = self.end_choices
        self.c("end_box").SelectedItem = end or END_TEXT
        self._loading = False

    def setting_changed(self, sender, args):
        if not self._loading:
            self.settings_dirty = True

    def defaults_click(self, sender, args):
        defaults = dict(self.store.DEFAULT_SETTINGS)
        defaults[sr.PANEL_FAMILY_KEY] = sr.DEFAULT_PANEL_FAMILY
        self._show_settings(defaults)
        self.settings_dirty = True
        self.status("default drawing settings shown (unsaved)")

    def read_settings(self, errors):
        """The settings typed in the tab, adding a message to errors for each one that isn't valid."""
        out = {}
        label = self.c("scale_box").SelectedItem
        scale = dict(self.store.SCALES).get(label)
        if scale is None and label and str(label).startswith("1 : "):
            scale = int(str(label)[4:])
        if scale is None:
            errors.append("%s: choose a drafting view scale." % self.name)
        out["view_scale"] = scale
        for key, name, what, kind in [("device_spacing_ft", "spacing_box", "Spacing between devices", float),
                                      ("devices_per_line", "per_line_box", "Devices before wrapping", int),
                                      ("wrap_rounding", "rounding_box", "Wrap rounding", int),
                                      ("label_offset_in", "offset_box", "Address text below line", float),
                                      ("label_offset_x_ft", "label_x_box", "Circuit label offset", float)]:
            lo, hi = self.store.SETTING_LIMITS[key]
            text = (self.c(name).Text or "").strip()
            try:
                value = kind(text)
            except Exception:
                value = None
            if value is None or not lo <= value <= hi:
                errors.append("%s: %s must be a %s from %s to %s."
                              % (self.name, what, "whole number" if kind is int else "number",
                                 number_text(lo), number_text(hi)))
            out[key] = value
        family = (self.c("panel_family_box").Text or "").strip()
        if not family:
            errors.append("%s: choose the panel detail family." % self.name)
        out[sr.PANEL_FAMILY_KEY] = family
        end = self.c("end_box").SelectedItem
        out[sr.END_SYMBOL_KEY] = "" if (not end or str(end) == END_TEXT) else str(end)
        return out

    # ---- Symbol table ----
    def _group_of(self, key):
        if not self.callouts_on or self.cfg is None or not key:
            return ""
        return cc.setting(self.cfg, key, "address_group") or ""

    def _add_row(self, key, symbols):
        row = self.dt.NewRow()
        row["FamilyType"] = key
        row["Symbol"] = SEP.join(symbols)
        row["AddressGroup"] = self._group_of(key)
        self.dt.Rows.Add(row)

    def _selected_rows(self, grid="grid"):
        return [i.Row for i in list(self.c(grid).SelectedItems) if hasattr(i, "Row")]

    def commit(self):
        try:
            self.c("grid").CommitEdit()
        except Exception:
            pass

    def add_click(self, sender, args):
        self.commit()
        existing = set(cell_text(r["FamilyType"]) for r in _live(self.dt))
        scope = forms.CommandSwitchWindow.show([s[0] for s in SCOPES],
                                               message="Which loaded types do you want to list?")
        if not scope:
            return
        keys = sorted(loaded_type_keys(dict(SCOPES)[scope]) - existing)
        if not keys:
            self.status("no other loaded types to add")
            return
        picked = forms.SelectFromList.show(keys, title="Add types to the %s table" % self.name,
                                           button_name="Add Selected", multiselect=True)
        if not picked:
            return
        for key in picked:
            self._add_row(key, [])
        self.status("%d type(s) added (unsaved) - choose the symbols for each" % len(picked))

    def set_click(self, sender, args):
        self.commit()
        self._edit_rows(self._selected_rows())

    def grid_double_click(self, sender, args):
        grid = self.c("grid")
        item = grid.CurrentItem
        col = grid.CurrentColumn
        if item is None or not hasattr(item, "Row") or col is None:
            return
        if str(col.Header).startswith("Symbols"):
            self.commit()
            self._edit_rows([item.Row])

    def _edit_rows(self, rows):
        if not rows:
            self.status("select one or more rows first")
            return
        if not self.symbols:
            note("No Generic Annotation or Detail Item types are loaded in this project.")
            return
        first = rows[0]
        current = [x for x in cell_text(first["Symbol"]).split(SEP) if x]
        title = cell_text(first["FamilyType"]) if len(rows) == 1 else "%d selected types" % len(rows)
        dlg = SymbolListEditor(title, self.symbols, current)
        dlg.ShowDialog()
        if dlg.result is None:
            return
        for row in rows:
            row["Symbol"] = SEP.join(dlg.result)
        self.status("symbols set on %d row(s) (unsaved)" % len(rows))

    def delete_click(self, sender, args):
        self.commit()
        victims = [i for i in list(self.c("grid").SelectedItems) if hasattr(i, "Row")]
        for item in victims:
            item.Row.Delete()
        self.status("%d row(s) deleted (unsaved)" % len(victims))

    # ---- Address callouts ----
    def _fill_callouts(self, callouts):
        """One row per Address Group subgroup in Family Defaults Config; saved callouts of groups / subgroups that
        aren't there any more are kept aside and saved again."""
        shown = set()
        groups = (self.cfg or {}).get("address_groups") or [] if self.callouts_on else []
        for group, subs in groups:
            for sub, number in subs:
                symbol = (callouts.get(group) or {}).get(sub or "", "")
                row = self.dt_callouts.NewRow()
                row["Group"], row["Subgroup"], row["Count"] = group, sub or "", "%d" % number
                self._set_callout(row, symbol)
                self.dt_callouts.Rows.Add(row)
                shown.add((group, sub or ""))
        for group, subs in callouts.items():
            for sub, symbol in subs.items():
                if (group, sub) not in shown:
                    self.extra_callouts.setdefault(group, {})[sub] = symbol
        self.dt_callouts.AcceptChanges()

    def _set_callout(self, row, symbol):
        row["Symbol"] = symbol or ""
        row["Shown"] = symbol or TEXT_LABEL

    def callout_set_click(self, sender, args):
        rows = self._selected_rows("callout_grid")
        if not rows:
            self.status("select one or more Address Group subgroups first")
            return
        if not self.symbols:
            note("No Generic Annotation or Detail Item types are loaded in this project.")
            return
        first = rows[0]
        what = ("%s - %s" % (cell_text(first["Group"]), cell_text(first["Subgroup"]) or "(only subgroup)")
                if len(rows) == 1 else "%d subgroups" % len(rows))
        picked = forms.SelectFromList.show([TEXT_LABEL] + self.symbols, title="Address callout for %s" % what,
                                           button_name="Use", multiselect=False)
        if not picked:
            return
        for row in rows:
            self._set_callout(row, "" if picked == TEXT_LABEL else picked)
        self.status("callout set on %d subgroup(s) (unsaved)" % len(rows))

    def callout_text_click(self, sender, args):
        rows = self._selected_rows("callout_grid")
        for row in rows:
            self._set_callout(row, "")
        self.status("%d subgroup(s) set to the 45 degree text (unsaved)" % len(rows))

    def read_callouts(self):
        """{group: {subgroup: symbol}} as set in the table, plus the kept ones."""
        out = dict((g, dict(subs)) for g, subs in self.extra_callouts.items())
        for row in _live(self.dt_callouts):
            symbol = cell_text(row["Symbol"])
            if symbol:
                out.setdefault(cell_text(row["Group"]), {})[cell_text(row["Subgroup"])] = symbol
        return out

    # ---- Saving ----
    def has_changes(self):
        self.commit()
        return not self.failed and (self.dt.GetChanges() is not None or self.dt_callouts.GetChanges() is not None
                                    or self.settings_dirty)

    def collect(self, errors):
        """(table, settings, types without a symbol) as typed, adding a message to errors for anything wrong."""
        self.commit()
        table, seen, blank = {}, set(), 0
        settings = self.read_settings(errors)
        settings[sr.CALLOUTS] = self.read_callouts() if self.callouts_on else {}
        for idx, row in enumerate(_live(self.dt), start=1):
            key = cell_text(row["FamilyType"])
            symbol = cell_text(row["Symbol"])
            if not key and not symbol:
                continue    # fully blank row
            if not key:
                errors.append("%s row %d: Family Type is blank." % (self.name, idx))
                continue
            if key in seen:
                errors.append("%s row %d: duplicate Family Type '%s'." % (self.name, idx, key))
                continue
            seen.add(key)
            if not symbol:
                blank += 1
            table[key] = sr.new_entry([x for x in symbol.split(SEP) if x])
        return table, settings, blank

    def save(self, table, settings):
        """Write the tab's files. '' or the reason they couldn't be written."""
        try:
            self.store.save_settings(settings)
        except Exception as ex:
            return ("Could not save the %s drawing settings:\n%s\n\nPath: %s"
                    % (self.name, ex, self.store.settings_path()))
        self.settings_dirty = False
        self.dt_callouts.AcceptChanges()
        try:
            self.store.save_table(table)
        except Exception as ex:
            return "Could not save the %s symbol table:\n%s\n\nPath: %s" % (self.name, ex, self.store.table_path())
        self.dt.AcceptChanges()
        return ""


class RiserConfigWindow(forms.WPFWindow):
    def __init__(self):
        forms.WPFWindow.__init__(self, window_xaml(), literal_string=True)
        self.tab_list = [RiserTab(self, header, prefix, store) for header, prefix, store in TABS]
        self.status_text.Text = "   ".join("%s: %d type(s)" % (t.name, t.count) for t in self.tab_list)

    def save_click(self, sender, args):
        errors, collected = [], []
        for tab in self.tab_list:
            if not tab.failed:
                collected.append((tab,) + tab.collect(errors))
        if errors:
            note("Nothing was saved. Please fix:\n\n" + "\n".join(errors))
            return
        parts = []
        for tab, table, settings, blank in collected:
            problem = tab.save(table, settings)
            if problem:
                note(problem)
                return
            text = "%s: %d type(s)" % (tab.name, len(table))
            if blank:
                text += " (%d without a symbol)" % blank
            parts.append(text)
        self.status_text.Text = "Saved - " + "   ".join(parts)

    def close_click(self, sender, args):
        self.Close()

    def window_closing(self, sender, args):
        if any(t.has_changes() for t in self.tab_list):
            answer = forms.CommandSwitchWindow.show([CLOSE_ANYWAY, KEEP_EDITING],
                                                    message="You have unsaved changes in Riser - Config.")
            if answer != CLOSE_ANYWAY:
                args.Cancel = True


def show_editor():
    RiserConfigWindow().ShowDialog()
