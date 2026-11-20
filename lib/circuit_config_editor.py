# -*- coding: utf-8 -*-
# circuit_config_editor module - version v5
# Change log (last change first):
#   v5 - Family Defaults Config v5: several rows can be selected and set at once (Set selected rows); filters
#        (Category, Circuit Type, Mounting, Device Type, Conduit Type, Address Group) and Sort by; a Circuit column
#        (SLC: SLC Address parameters, NAC: a Notification Circuit parameter); unsaved changes tracked by edits
#        (expanding a family no longer counts as one).
#   v4 - Auto Circuit - SLC / NAC / Voice v1: the help text says what a blank Device Type does (asked when the
#        device is addressed).
#   v3 - Family Defaults Config v3: renamed from Auto Circuit - Config (window title and messages).
#   v2 - Auto Circuit - Config v2: Address Groups are a table of Group / Subgroup / Addresses (one row per subgroup);
#        Round To is typed on Family Defaults (the Address Rounding table is removed).
#   v1 - Auto Circuit - Config v1: the combined routing and addressing settings window (Family Defaults; Address and
#        Routing Defaults), replacing the Auto Conduit, Address SLC and Address NAC / Voice config windows.
"""The Family Defaults Config window (lib/circuit_config.py holds the settings). show_editor(doc).

Family Defaults tab: every Fire Alarm Device and Electrical Equipment family in the project (and any in the settings
that aren't loaded), each with its types under it (double-click a family, or Expand All). Setting a value on a family
sets it on all its types; a family whose types differ shows <varies>. A blank value is not set. Several rows can be
selected and set at once; the list can be filtered and sorted (families keep their types under them). The Circuit
column: SLC = the family has SLC Address parameters, NAC = it has a Notification Circuit parameter (families that
aren't placed are opened in the background to check, the first time Circuit Type is filtered or sorted on).
Address and Routing Defaults tab: conduit elevations per conduit type and the Address Groups with their subgroups."""
import os

import clr
clr.AddReference("System.Data")
from System import String, Boolean, DBNull
from System.Data import DataTable, DataRowState
from Microsoft.Win32 import OpenFileDialog
from Autodesk.Revit.DB import BuiltInCategory, FilteredElementCollector
from pyrevit import forms

import circuit_config as cc
import slc_addressing as slc  # which parameters are SLC Address parameters
import mounting_rules         # conduit type labels in the project
import conduit_routing as cr  # reading a length such as 15'-0"
import ew_common as ec        # shared helpers (lib/ew_common.py)

TITLE = "Family Defaults Config"
VARIES = "<varies>"
NOT_LOADED = "(not in project)"
CATEGORIES = [(BuiltInCategory.OST_FireAlarmDevices, "Fire Alarm Device"),
              (BuiltInCategory.OST_ElectricalEquipment, "Electrical Equipment")]
OPEN, CLOSED = u"▾", u"▸"
# (DataTable column, settings field)
SETTINGS = [("Mounting", "mounting"), ("DeviceType", "device_type"), ("ConduitType", "conduit_type"),
            ("AddressGroup", "address_group"), ("RoundTo", "round_to")]
SETTING_COLUMNS = dict(SETTINGS)
ANY, BLANK, NO_CHANGE, CLEAR = "(any)", "(blank)", "(no change)", "(clear)"
NAC_PARAM = "notification circuit"      # a family with this parameter is a NAC device (Circuit Type filter)
SLC_DEVICES, NAC_DEVICES, NEITHER = "SLC Devices", "NAC Devices", "Neither"
NOT_CHECKED = "?"
# filter drop-down -> column; Category and Circuit Type are about the family, the rest also show matching types
FILTERS = [("f_category", "Category"), ("f_circuit", "Circuit"), ("f_mounting", "Mounting"),
           ("f_device", "DeviceType"), ("f_conduit", "ConduitType"), ("f_group", "AddressGroup")]
FAMILY_FILTERS = ("Category", "Circuit")
SORTS = [("Family", None), ("Category", "Category"), ("Circuit Type", "Circuit"), ("Mounting", "Mounting"),
         ("Device Type", "DeviceType"), ("Conduit Type", "ConduitType"), ("Address Group", "AddressGroup"),
         ("Round To", "RoundTo")]
# Set selected rows: drop-down -> column
SETTERS = [("s_mounting", "Mounting"), ("s_device", "DeviceType"), ("s_conduit", "ConduitType"),
           ("s_group", "AddressGroup"), ("s_round", "RoundTo")]


def cell_text(v):
    if v is None or isinstance(v, DBNull):
        return u""
    return (u"%s" % v).strip()


def _like(text):
    """Text made safe inside a DataView LIKE pattern."""
    out = []
    for ch in text.replace("'", "''"):
        out.append("[%s]" % ch if ch in "[]*%" else ch)
    return "".join(out)


def project_types(doc):
    """{family name: (category label, set of 'Family : Type' keys, the Family)} for the loaded device and equipment
    types."""
    found = {}
    for cat, label in CATEGORIES:
        for t in FilteredElementCollector(doc).OfCategory(cat).WhereElementIsElementType().ToElements():
            try:
                family, key = t.FamilyName, ec.type_key(t)
            except Exception:
                continue
            entry = found.setdefault(family, (label, set(), getattr(t, "Family", None)))
            entry[1].add(key)
    return found


def circuit_text(names):
    """'SLC', 'NAC', 'SLC + NAC' or 'None' for a family with these parameter names."""
    found = []
    if any(slc.param_position(n) is not None for n in names):
        found.append("SLC")
    if any((n or u"").strip().lower() == NAC_PARAM for n in names):
        found.append("NAC")
    return " + ".join(found) or "None"


def _param_names(element):
    names = []
    try:
        for p in element.Parameters:
            try:
                names.append(p.Definition.Name)
            except Exception:
                pass
    except Exception:
        pass
    return names


def placed_circuits(doc):
    """{family name: circuit text} from a placed instance of each family (its instance and type parameters)."""
    found = {}
    for cat, _label in CATEGORIES:
        for el in FilteredElementCollector(doc).OfCategory(cat).WhereElementIsNotElementType().ToElements():
            try:
                symbol = doc.GetElement(el.GetTypeId())
                family = symbol.FamilyName
            except Exception:
                continue
            if family not in found:
                found[family] = circuit_text(_param_names(el) + _param_names(symbol))
    return found


def family_file_circuit(doc, family):
    """Circuit text of a family that isn't placed, from its family file opened in the background (nothing is
    changed or reloaded), or NOT_CHECKED if it can't be opened."""
    fdoc = None
    try:
        if family is None or family.IsInPlace or not family.IsEditable:
            return NOT_CHECKED
        fdoc = doc.EditFamily(family)
        return circuit_text([fp.Definition.Name for fp in fdoc.FamilyManager.Parameters])
    except Exception:
        return NOT_CHECKED
    finally:
        try:
            if fdoc is not None:
                fdoc.Close(False)
        except Exception:
            pass


EDITOR_XAML = """
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Family Defaults Config"
        Width="1180" Height="640" MinWidth="980" MinHeight="420"
        WindowStartupLocation="CenterScreen"
        Closing="window_closing">
    <Grid Margin="12">
        <Grid.RowDefinitions>
            <RowDefinition Height="*"/>
            <RowDefinition Height="Auto"/>
        </Grid.RowDefinitions>
        <TabControl Grid.Row="0">
            <TabItem Header="Family Defaults">
                <Grid Margin="8">
                    <Grid.RowDefinitions>
                        <RowDefinition Height="Auto"/>
                        <RowDefinition Height="Auto"/>
                        <RowDefinition Height="Auto"/>
                        <RowDefinition Height="*"/>
                        <RowDefinition Height="Auto"/>
                    </Grid.RowDefinitions>
                    <TextBlock Grid.Row="0" TextWrapping="Wrap" Margin="0,0,0,8"
                               Text="Double-click a family to show or hide its types. A value set on a family is set on all its types; &lt;varies&gt; means its types differ. Blank = not set: the conduit type is asked for, the Device Type is asked when the device is addressed, and Address Group blank asks how many addresses. Address Group and Round To are for Module and Detector types: the groups are on the Address and Routing Defaults tab; Round To is a number you type (5: M004 becomes M005). Ctrl+click or Shift+click to select several rows, then set them together at the bottom. Circuit: SLC = the family has SLC Address parameters, NAC = it has a Notification Circuit parameter."/>
                    <DockPanel Grid.Row="1" Margin="0,0,0,8" LastChildFill="False">
                        <TextBlock Text="Search:" VerticalAlignment="Center" Margin="0,0,6,0" DockPanel.Dock="Left"/>
                        <TextBox x:Name="search_box" Width="240" TextChanged="search_changed" DockPanel.Dock="Left"/>
                        <Button Content="Expand All" Width="90" Margin="12,0,6,0" Click="expand_click" DockPanel.Dock="Left"/>
                        <Button Content="Collapse All" Width="90" Click="collapse_click" DockPanel.Dock="Left"/>
                        <TextBlock Text="Sort by:" VerticalAlignment="Center" Margin="18,0,6,0" DockPanel.Dock="Left"/>
                        <ComboBox x:Name="sort_box" Width="130" SelectionChanged="sort_changed" DockPanel.Dock="Left"/>
                    </DockPanel>
                    <WrapPanel Grid.Row="2" Margin="0,0,0,8">
                        <TextBlock Text="Filter -" VerticalAlignment="Center" FontWeight="SemiBold" Margin="0,0,8,0"/>
                        <TextBlock Text="Category:" VerticalAlignment="Center" Margin="0,0,4,0"/>
                        <ComboBox x:Name="f_category" Width="140" Margin="0,0,10,0" SelectionChanged="filter_changed"/>
                        <TextBlock Text="Circuit Type:" VerticalAlignment="Center" Margin="0,0,4,0"/>
                        <ComboBox x:Name="f_circuit" Width="100" Margin="0,0,10,0" SelectionChanged="filter_changed"/>
                        <TextBlock Text="Mounting:" VerticalAlignment="Center" Margin="0,0,4,0"/>
                        <ComboBox x:Name="f_mounting" Width="80" Margin="0,0,10,0" SelectionChanged="filter_changed"/>
                        <TextBlock Text="Device Type:" VerticalAlignment="Center" Margin="0,0,4,0"/>
                        <ComboBox x:Name="f_device" Width="110" Margin="0,0,10,0" SelectionChanged="filter_changed"/>
                        <TextBlock Text="Conduit Type:" VerticalAlignment="Center" Margin="0,0,4,0"/>
                        <ComboBox x:Name="f_conduit" Width="160" Margin="0,0,10,0" SelectionChanged="filter_changed"/>
                        <TextBlock Text="Address Group:" VerticalAlignment="Center" Margin="0,0,4,0"/>
                        <ComboBox x:Name="f_group" Width="120" Margin="0,0,10,0" SelectionChanged="filter_changed"/>
                        <Button Content="Clear Filters" Width="90" Click="clear_filters_click"/>
                    </WrapPanel>
                    <DataGrid x:Name="grid" Grid.Row="3" AutoGenerateColumns="False"
                              CanUserAddRows="False" CanUserDeleteRows="False" CanUserSortColumns="False"
                              SelectionMode="Extended" SelectionUnit="FullRow" GridLinesVisibility="All"
                              HeadersVisibility="Column" MouseDoubleClick="grid_double_click">
                        <DataGrid.RowStyle>
                            <Style TargetType="DataGridRow">
                                <Style.Triggers>
                                    <DataTrigger Binding="{Binding IsFamily}" Value="True">
                                        <Setter Property="FontWeight" Value="SemiBold"/>
                                        <Setter Property="Background" Value="#FFEFEFEF"/>
                                    </DataTrigger>
                                </Style.Triggers>
                            </Style>
                        </DataGrid.RowStyle>
                        <DataGrid.Columns>
                            <DataGridTextColumn Header="" Binding="{Binding Arrow}" Width="22" IsReadOnly="True"/>
                            <DataGridTextColumn Header="Family / Type" Binding="{Binding Name}" Width="*" IsReadOnly="True"/>
                            <DataGridTextColumn Header="Category" Binding="{Binding Category}" Width="130" IsReadOnly="True"/>
                            <DataGridTextColumn Header="Circuit" Binding="{Binding Circuit}" Width="80" IsReadOnly="True"/>
                            <DataGridComboBoxColumn Header="Mounting" SelectedItemBinding="{Binding Mounting}" Width="90"/>
                            <DataGridComboBoxColumn Header="Device Type" SelectedItemBinding="{Binding DeviceType}" Width="120"/>
                            <DataGridComboBoxColumn Header="Conduit Type" SelectedItemBinding="{Binding ConduitType}" Width="220"/>
                            <DataGridComboBoxColumn Header="Address Group" SelectedItemBinding="{Binding AddressGroup}" Width="140"/>
                            <DataGridTextColumn Header="Round To" Binding="{Binding RoundTo}" Width="80"/>
                        </DataGrid.Columns>
                    </DataGrid>
                    <WrapPanel Grid.Row="4" Margin="0,8,0,0">
                        <TextBlock Text="Set selected rows -" VerticalAlignment="Center" FontWeight="SemiBold" Margin="0,0,8,0"/>
                        <TextBlock Text="Mounting:" VerticalAlignment="Center" Margin="0,0,4,0"/>
                        <ComboBox x:Name="s_mounting" Width="100" Margin="0,0,10,0"/>
                        <TextBlock Text="Device Type:" VerticalAlignment="Center" Margin="0,0,4,0"/>
                        <ComboBox x:Name="s_device" Width="110" Margin="0,0,10,0"/>
                        <TextBlock Text="Conduit Type:" VerticalAlignment="Center" Margin="0,0,4,0"/>
                        <ComboBox x:Name="s_conduit" Width="160" Margin="0,0,10,0"/>
                        <TextBlock Text="Address Group:" VerticalAlignment="Center" Margin="0,0,4,0"/>
                        <ComboBox x:Name="s_group" Width="120" Margin="0,0,10,0"/>
                        <TextBlock Text="Round To:" VerticalAlignment="Center" Margin="0,0,4,0"/>
                        <ComboBox x:Name="s_round" Width="100" Margin="0,0,10,0" IsEditable="True"/>
                        <Button Content="Apply to Selected" Width="120" Click="apply_selected_click"/>
                    </WrapPanel>
                </Grid>
            </TabItem>
            <TabItem Header="Address and Routing Defaults">
                <Grid Margin="8">
                    <Grid.ColumnDefinitions>
                        <ColumnDefinition Width="*"/>
                        <ColumnDefinition Width="16"/>
                        <ColumnDefinition Width="*"/>
                    </Grid.ColumnDefinitions>
                    <GroupBox Grid.Column="0" Header="Conduit Elevations">
                        <Grid Margin="6">
                            <Grid.RowDefinitions>
                                <RowDefinition Height="Auto"/>
                                <RowDefinition Height="*"/>
                            </Grid.RowDefinitions>
                            <TextBlock Grid.Row="0" TextWrapping="Wrap" Margin="0,0,0,6"
                                       Text="Height above the level that runs of each conduit type are drawn at, e.g. 15'-0&quot; or 180&quot;. Blank = asked when the conduit is created."/>
                            <DataGrid x:Name="elev_grid" Grid.Row="1" AutoGenerateColumns="False"
                                      CanUserAddRows="False" CanUserDeleteRows="False" HeadersVisibility="Column"
                                      GridLinesVisibility="All">
                                <DataGrid.Columns>
                                    <DataGridTextColumn Header="Conduit Type" Binding="{Binding ConduitType}" Width="*" IsReadOnly="True"/>
                                    <DataGridTextColumn Header="Elevation" Binding="{Binding Elevation}" Width="110"/>
                                </DataGrid.Columns>
                            </DataGrid>
                        </Grid>
                    </GroupBox>
                    <GroupBox Grid.Column="2" Header="Address Groups">
                        <Grid Margin="6">
                            <Grid.RowDefinitions>
                                <RowDefinition Height="Auto"/>
                                <RowDefinition Height="*"/>
                                <RowDefinition Height="Auto"/>
                            </Grid.RowDefinitions>
                            <TextBlock Grid.Row="0" TextWrapping="Wrap" Margin="0,0,0,6"
                                       Text="One row per subgroup: rows with the same Group name make one group, e.g. MMS Cabinet: Single Zone 6, Dual Zone 12, Triple Zone 18, Quad Zone 24. A device whose Address Group has several subgroups chooses one when it is addressed; a group with one subgroup always fills that many addresses (its Subgroup can be left blank). Addresses: 1-24. Type in the blank bottom row to add one."/>
                            <DataGrid x:Name="group_grid" Grid.Row="1" AutoGenerateColumns="False"
                                      CanUserAddRows="True" CanUserDeleteRows="True" HeadersVisibility="Column"
                                      GridLinesVisibility="All">
                                <DataGrid.Columns>
                                    <DataGridTextColumn Header="Group" Binding="{Binding Group}" Width="*"/>
                                    <DataGridTextColumn Header="Subgroup" Binding="{Binding Subgroup}" Width="*"/>
                                    <DataGridTextColumn Header="Addresses" Binding="{Binding Count}" Width="80"/>
                                </DataGrid.Columns>
                            </DataGrid>
                            <Button Grid.Row="2" Content="Delete Selected Rows" Width="160" Margin="0,6,0,0"
                                    HorizontalAlignment="Left" Click="delete_group_click"/>
                        </Grid>
                    </GroupBox>
                </Grid>
            </TabItem>
        </TabControl>
        <DockPanel Grid.Row="1" Margin="0,10,0,0" LastChildFill="False">
            <Button Content="Open File" Width="90" Margin="0,0,8,0" Click="open_click" DockPanel.Dock="Left"/>
            <Button Content="Load Default Config..." Width="150" Click="load_default_click" DockPanel.Dock="Left"/>
            <TextBlock x:Name="status_text" VerticalAlignment="Center" Margin="12,0,0,0" DockPanel.Dock="Left"/>
            <Button Content="Close" Width="80" Click="close_click" DockPanel.Dock="Right"/>
            <Button Content="Save" Width="80" Margin="0,0,8,0" Click="save_click" DockPanel.Dock="Right"/>
        </DockPanel>
    </Grid>
</Window>
"""


class ConfigEditor(forms.WPFWindow):
    def __init__(self, doc, cfg):
        forms.WPFWindow.__init__(self, EDITOR_XAML, literal_string=True)
        self.doc = doc
        self._busy = False      # True while values are copied between a family and its types, or filled in
        self._ready = False     # the drop-downs' events wait until the window is filled
        self._dirty = False     # an edit not saved yet
        self.circuits = {}      # family name -> circuit text ('SLC', 'NAC', 'SLC + NAC', 'None', NOT_CHECKED)
        self.conduit_labels = mounting_rules.list_conduit_type_labels(doc)

        text = clr.GetClrType(String)
        self.dt = DataTable("Families")
        for name in (("Arrow", "Name", "Category", "Circuit", "Family", "Key", "Search", "SortKey")
                     + tuple(c for c, _f in SETTINGS)):
            self.dt.Columns.Add(name, text)
        for name in ("IsFamily", "Expanded", "Match"):
            self.dt.Columns.Add(name, clr.GetClrType(Boolean))
        self.dt_elev = DataTable("Elevations")
        self.dt_elev.Columns.Add("ConduitType", text)
        self.dt_elev.Columns.Add("Elevation", text)
        self.dt_groups = DataTable("Groups")
        for name in ("Group", "Subgroup", "Count"):
            self.dt_groups.Columns.Add(name, text)

        self._fill(cfg)
        self.dt.ColumnChanging += self._column_changing
        self.dt.ColumnChanged += self._column_changed
        self.dt_groups.RowChanged += self._lists_changed
        self.dt_groups.RowDeleted += self._lists_changed
        self.dt_elev.ColumnChanged += self._elevation_changed
        self._ready = True
        if cfg["notes"]:
            self.Loaded += lambda sender, args: forms.alert(
                "Your settings were filled from the configs this one replaces (they are left as they were):\n\n- "
                + "\n- ".join(cfg["notes"]), title=TITLE)

    # ---------- Filling the window ----------
    def _fill(self, cfg):
        self._busy = True
        try:
            self.dt.Clear()
            self.dt_elev.Clear()
            self.dt_groups.Clear()
            in_project = project_types(self.doc)
            try:
                placed = placed_circuits(self.doc)
            except Exception:
                placed = {}
            families = set(in_project) | set(cfg["families"]) | set(cc.family_of(k) for k in cfg["types"])
            self.family_rows, self.type_rows, self.family_elements = {}, {}, {}
            for family in sorted(families, key=lambda f: f.lower()):
                category, keys, element = in_project.get(family, (NOT_LOADED, set(), None))
                self.family_elements[family] = element
                if family not in self.circuits:
                    self.circuits[family] = placed.get(family, NOT_CHECKED if element is not None else u"")
                keys = sorted(set(keys) | set(k for k in cfg["types"] if cc.family_of(k) == family))
                frow = self._new_row(family, family, category, "", True)
                self.family_rows[family] = frow
                self.type_rows[family] = []
                for key in keys:
                    label = category if key in in_project.get(family, ("", set()))[1] else NOT_LOADED
                    trow = self._new_row(u"      " + key.split(" : ", 1)[-1], family, label, key, False)
                    for column, field in SETTINGS:
                        trow[column] = self._shown(cc.setting(cfg, key, field, family))
                    self.type_rows[family].append(trow)
                for column, field in SETTINGS:
                    if keys:
                        frow[column] = self._summary(self.type_rows[family], column)
                    else:
                        frow[column] = self._shown((cfg["families"].get(family) or {}).get(field))
            for name, subs in cfg["address_groups"]:
                for sub, count in subs:
                    row = self.dt_groups.NewRow()
                    row["Group"], row["Subgroup"], row["Count"] = name, sub, str(count)
                    self.dt_groups.Rows.Add(row)
            labels = list(self.conduit_labels) + sorted(l for l in cfg["elevations"] if l not in self.conduit_labels)
            for label in labels:
                row = self.dt_elev.NewRow()
                row["ConduitType"], row["Elevation"] = label, cfg["elevations"].get(label, u"")
                self.dt_elev.Rows.Add(row)
            self.notes = list(cfg["notes"])
            for table in (self.dt, self.dt_elev, self.dt_groups):
                table.AcceptChanges()
            self._dirty = False
        finally:
            self._busy = False
        self.view = self.dt.DefaultView
        self._ready = False
        try:
            self._set_choices(cfg)
            self._sort_rows()
            self._match_rows()
        finally:
            self._ready = True
        self._filter()
        self.grid.ItemsSource = self.view
        self.elev_grid.ItemsSource = self.dt_elev.DefaultView
        self.group_grid.ItemsSource = self.dt_groups.DefaultView
        self.status_text.Text = "%d families, %d types" % (len(self.family_rows),
                                                           sum(len(v) for v in self.type_rows.values()))

    def _new_row(self, name, family, category, key, is_family):
        row = self.dt.NewRow()
        row["Arrow"] = CLOSED if is_family else u""
        row["Name"], row["Family"], row["Category"], row["Key"] = name, family, category, key
        row["Circuit"] = self.circuits.get(family, u"")
        row["Search"] = (key or family).lower()
        row["SortKey"] = u""
        row["IsFamily"], row["Expanded"], row["Match"] = is_family, False, True
        for column, _f in SETTINGS:
            row[column] = u""
        self.dt.Rows.Add(row)
        return row

    @staticmethod
    def _shown(value):
        return u"" if value is None else u"%s" % value

    @staticmethod
    def _summary(rows, column):
        values = set(cell_text(r[column]) for r in rows)
        return values.pop() if len(values) == 1 else VARIES

    def _set_choices(self, cfg=None):
        """The values each drop-down offers (the Address Groups as they are in the window now)."""
        groups = []
        for r in self._live(self.dt_groups):
            name = cell_text(r["Group"])
            if name and name not in groups:
                groups.append(name)
        used = dict((c, set(cell_text(r[c]) for r in self._live(self.dt))) for c, _f in SETTINGS)

        def choices(base, column):
            extra = sorted(v for v in used[column] if v and v != VARIES and v not in base)
            return [u""] + base + extra + [VARIES]

        columns = self.grid.Columns
        mountings, devices = list(cc.MOUNTINGS), list(cc.DEVICE_TYPES)
        conduits = list(self.conduit_labels) + sorted(v for v in used["ConduitType"]
                                                      if v and v != VARIES and v not in self.conduit_labels)
        columns[4].ItemsSource = choices(mountings, "Mounting")
        columns[5].ItemsSource = choices(devices, "DeviceType")
        columns[6].ItemsSource = choices(list(self.conduit_labels), "ConduitType")
        columns[7].ItemsSource = choices(groups, "AddressGroup")

        was_ready, self._ready = self._ready, False
        try:
            categories = sorted(set(cell_text(r["Category"]) for r in self._live(self.dt)) - set([u""]))
            for name, items in (("f_category", [ANY] + categories),
                                ("f_circuit", [ANY, SLC_DEVICES, NAC_DEVICES, NEITHER]),
                                ("f_mounting", [ANY, BLANK] + mountings), ("f_device", [ANY, BLANK] + devices),
                                ("f_conduit", [ANY, BLANK] + conduits), ("f_group", [ANY, BLANK] + groups),
                                ("s_mounting", [NO_CHANGE, CLEAR] + mountings),
                                ("s_device", [NO_CHANGE, CLEAR] + devices),
                                ("s_conduit", [NO_CHANGE, CLEAR] + conduits),
                                ("s_group", [NO_CHANGE, CLEAR] + groups), ("s_round", [NO_CHANGE, CLEAR]),
                                ("sort_box", [label for label, _c in SORTS])):
                self._set_items(getattr(self, name), items)
        finally:
            self._ready = was_ready

    @staticmethod
    def _set_items(box, items):
        """New items for a drop-down, keeping what was chosen when it is still there."""
        current = box.SelectedItem
        box.ItemsSource = items
        box.SelectedItem = current if current in items else items[0]

    @staticmethod
    def _live(table):
        for row in table.Rows:
            if row.RowState != DataRowState.Deleted and row.RowState != DataRowState.Detached:
                yield row

    def _filter(self):
        """What the grid shows: families and their open types, narrowed by the filters and the search."""
        text = (self.search_box.Text or u"").strip().lower()
        show_types = any(column not in FAMILY_FILTERS for column in self._wanted())
        rule = "Match = True AND (IsFamily = True OR Expanded = True%s)" % (" OR IsFamily = False" if show_types else "")
        if text:
            rule += " AND Search LIKE '*%s*'" % _like(text)
        self.view.RowFilter = rule

    def _wanted(self):
        """{column: value chosen in its filter}."""
        wanted = {}
        for name, column in FILTERS:
            value = cell_text(getattr(self, name).SelectedItem)
            if value and value != ANY:
                wanted[column] = value
        return wanted

    @staticmethod
    def _matches(row, wanted):
        for column, value in wanted.items():
            have = cell_text(row[column])
            if column == "Circuit":
                ok = {SLC_DEVICES: "SLC" in have.split(" + "), NAC_DEVICES: "NAC" in have.split(" + "),
                      NEITHER: have == "None"}.get(value, False)
            elif value == BLANK:
                ok = have == u""
            else:
                ok = have == value
            if not ok:
                return False
        return True

    def _match_rows(self):
        """Match = the row passes the filters; a family passes when any of its types does."""
        wanted = self._wanted()
        for family, frow in self.family_rows.items():
            trows = self.type_rows[family]
            hits = [self._matches(t, wanted) for t in trows]
            for trow, hit in zip(trows, hits):
                trow["Match"] = hit
            frow["Match"] = any(hits) if trows else self._matches(frow, wanted)

    def _sort_rows(self):
        """Families in the chosen order, each with its types under it."""
        column = dict(SORTS).get(cell_text(self.sort_box.SelectedItem))
        for family, frow in self.family_rows.items():
            value = cell_text(frow[column]) if column else u""
            if column == "RoundTo" and value.isdigit():
                value = value.zfill(6)
            order = u"%s%s|%s" % ("1" if column and not value else "0", value.lower(), family.lower())
            frow["SortKey"] = order + u"|0"
            for trow in self.type_rows[family]:
                trow["SortKey"] = order + u"|1|" + cell_text(trow["Name"]).lower()
        self.view.Sort = "SortKey ASC"

    def _check_circuits(self):
        """Opens the families that aren't placed to see their parameters (once). False if cancelled."""
        todo = [f for f, c in self.circuits.items() if c == NOT_CHECKED and self.family_elements.get(f) is not None]
        if not todo:
            return True
        cancelled = False
        with forms.ProgressBar(title="Checking families that aren't placed ({value} of {max_value})",
                               cancellable=True) as pb:
            for i, family in enumerate(todo, start=1):
                if pb.cancelled:
                    cancelled = True
                    break
                self.circuits[family] = family_file_circuit(self.doc, self.family_elements[family])
                pb.update_progress(i, len(todo))
        self._busy = True
        try:
            for family in todo:
                self.family_rows[family]["Circuit"] = self.circuits[family]
                for trow in self.type_rows[family]:
                    trow["Circuit"] = self.circuits[family]
        finally:
            self._busy = False
        return not cancelled

    def filter_changed(self, sender, args):
        if not self._ready:
            return
        self._commit()
        if "Circuit" in self._wanted():
            self._check_circuits()
        self._match_rows()
        self._filter()

    def sort_changed(self, sender, args):
        if not self._ready:
            return
        self._commit()
        if dict(SORTS).get(cell_text(self.sort_box.SelectedItem)) == "Circuit":
            self._check_circuits()
        self._sort_rows()

    def clear_filters_click(self, sender, args):
        self._ready = False
        try:
            for name, _column in FILTERS:
                box = getattr(self, name)
                box.SelectedIndex = 0
        finally:
            self._ready = True
        self._match_rows()
        self._filter()

    # ---------- Set selected rows ----------
    def apply_selected_click(self, sender, args):
        self._commit()
        rows = [item.Row for item in list(self.grid.SelectedItems) if getattr(item, "Row", None) is not None]
        if not rows:
            self.status_text.Text = "Select the rows to set first (Ctrl+click or Shift+click for several)"
            return
        changes = []
        for name, column in SETTERS:
            box = getattr(self, name)
            value = cell_text(box.Text if column == "RoundTo" else box.SelectedItem)
            if not value or value == NO_CHANGE:
                continue
            if value == CLEAR:
                value = u""
            elif column == "RoundTo" and (not value.isdigit() or int(value) < 2):
                forms.alert("Round To must be a whole number, 2 or more (or (clear)).", title=TITLE)
                return
            changes.append((column, value))
        if not changes:
            self.status_text.Text = "Choose a value to set at the bottom first"
            return
        for row in rows:
            for column, value in changes:
                row[column] = value
        self.status_text.Text = "Set on %d selected row(s) (unsaved)" % len(rows)

    def _commit(self):
        for grid in (self.grid, self.elev_grid, self.group_grid):
            try:
                grid.CommitEdit()       # the cell being typed in
                grid.CommitEdit()       # its row
            except Exception:
                pass

    # ---------- A family sets its types; a type updates its family ----------
    def _column_changing(self, sender, e):
        if self._busy or e.Column.ColumnName not in SETTING_COLUMNS:
            return
        if cell_text(e.ProposedValue) != VARIES:
            return
        row, column = e.Row, e.Column.ColumnName
        if row["IsFamily"]:
            types = self.type_rows.get(cell_text(row["Family"])) or []
            e.ProposedValue = self._summary(types, column) if types else u""
        else:
            e.ProposedValue = cell_text(row[column])     # a type can't be <varies>: keep its value

    def _column_changed(self, sender, e):
        column = e.Column.ColumnName
        if self._busy or column not in SETTING_COLUMNS:
            return
        self._dirty = True
        row = e.Row
        family = cell_text(row["Family"])
        self._busy = True
        try:
            if row["IsFamily"]:
                value = cell_text(row[column])
                if value != VARIES:
                    for trow in self.type_rows.get(family) or []:
                        trow[column] = value
            else:
                self.family_rows[family][column] = self._summary(self.type_rows[family], column)
        finally:
            self._busy = False

    def _lists_changed(self, sender, e):
        if not self._busy:
            self._dirty = True
        try:
            self._set_choices()
        except Exception:
            pass

    def _elevation_changed(self, sender, e):
        if not self._busy:
            self._dirty = True

    # ---------- Showing types ----------
    def _expand(self, family, expanded):
        frow = self.family_rows[family]
        if not self.type_rows.get(family):
            return
        frow["Expanded"], frow["Arrow"] = expanded, (OPEN if expanded else CLOSED)
        for trow in self.type_rows[family]:
            trow["Expanded"] = expanded

    def grid_double_click(self, sender, args):
        column = self.grid.CurrentColumn
        if column is not None and column.DisplayIndex > 3:
            return      # a double-click on a setting opens its drop-down instead
        item = self.grid.CurrentItem
        row = getattr(item, "Row", None)
        if row is None or not row["IsFamily"]:
            return
        self._commit()
        self._busy = True
        try:
            self._expand(cell_text(row["Family"]), not row["Expanded"])
        finally:
            self._busy = False

    def expand_click(self, sender, args):
        self._expand_all(True)

    def collapse_click(self, sender, args):
        self._expand_all(False)

    def _expand_all(self, expanded):
        self._commit()
        self._busy = True
        try:
            for family in self.family_rows:
                self._expand(family, expanded)
        finally:
            self._busy = False

    def search_changed(self, sender, args):
        self._commit()
        self._filter()


    # ---------- Lists on the second tab ----------
    def _delete_selected(self, grid):
        self._commit()
        victims = [i for i in list(grid.SelectedItems) if hasattr(i, "Row")]
        for item in victims:
            item.Row.Delete()
        if victims:
            self._dirty = True
        self.status_text.Text = "%d row(s) deleted (unsaved)" % len(victims)

    def delete_group_click(self, sender, args):
        self._delete_selected(self.group_grid)

    # ---------- Saving ----------
    def _collect(self):
        """(config, [errors]) from the window."""
        cfg, errors = cc.empty(), []
        groups, order = {}, []
        for n, row in enumerate(self._live(self.dt_groups), start=1):
            name, sub, count = cell_text(row["Group"]), cell_text(row["Subgroup"]), cell_text(row["Count"])
            if not name and not sub and not count:
                continue
            where = "Address Groups row %d%s" % (n, (" (%s)" % name) if name else "")
            if not name:
                errors.append("%s: the Group name is blank." % where)
                continue
            if name == VARIES:
                errors.append("%s: '%s' can't be a group name." % (where, name))
                continue
            if not count.isdigit() or not 1 <= int(count) <= cc.MAX_ADDRESSES:
                errors.append("%s: Addresses must be a whole number from 1 to %d." % (where, cc.MAX_ADDRESSES))
                continue
            if name not in groups:
                groups[name] = []
                order.append(name)
            if sub in [s_ for s_, _c in groups[name]]:
                errors.append("%s: the subgroup '%s' is in the group twice." % (where, sub or "(blank)"))
                continue
            groups[name].append((sub, int(count)))
        for name in order:
            if len(groups[name]) > 1 and any(not sub for sub, _c in groups[name]):
                errors.append("Address Groups (%s): a group with several subgroups needs a name for each, so it can "
                              "be chosen." % name)
            cfg["address_groups"].append((name, groups[name]))
        cr.bind(self.doc, None, TITLE)
        for row in self._live(self.dt_elev):
            label, text = cell_text(row["ConduitType"]), cell_text(row["Elevation"])
            if not text:
                continue
            if cr.parse_length(text) is None:
                errors.append("Conduit Elevations (%s): '%s' can't be read as a length, e.g. 15'-0\"." % (label, text))
                continue
            cfg["elevations"][label] = text

        for family in sorted(self.family_rows, key=lambda f: f.lower()):
            frow, trows = self.family_rows[family], self.type_rows[family]
            for column, field in SETTINGS:
                rows = trows or [frow]
                for row in rows:
                    value = cell_text(row[column])
                    where = cell_text(row["Key"]) or family
                    if field == "address_group" and value and value not in groups and value != VARIES:
                        errors.append("%s: Address Group '%s' is not one of the Address Groups." % (where, value))
                    if field == "round_to" and value and value != VARIES and (not value.isdigit() or int(value) < 2):
                        errors.append("%s: Round To '%s' must be a whole number, 2 or more." % (where, value))
                values = set(cell_text(r[column]) for r in rows)
                if len(values) == 1:
                    value = values.pop()        # the same on every type: kept on the family
                    if value:
                        cfg["families"].setdefault(family, {})[field] = (
                            int(value) if field == "round_to" and value.isdigit() else value)
                    continue
                for row in trows:
                    value = cell_text(row[column])
                    if value:
                        cfg["types"].setdefault(cell_text(row["Key"]), {})[field] = (
                            int(value) if field == "round_to" and value.isdigit() else value)
        return cfg, errors

    def save_click(self, sender, args):
        self._commit()
        cfg, errors = self._collect()
        if errors:
            forms.alert("Nothing was saved. Please fix:\n\n" + "\n".join(errors[:25]) +
                        ("\n... and %d more" % (len(errors) - 25) if len(errors) > 25 else ""), title=TITLE)
            return
        try:
            cc.save(cfg)
        except Exception as ex:
            forms.alert("Could not save the settings:\n%s\n\nPath: %s" % (ex, cc.config_path()), title=TITLE)
            return
        for table in (self.dt, self.dt_elev, self.dt_groups):
            table.AcceptChanges()
        self._dirty = False
        self.status_text.Text = "Saved"

    def _unsaved(self):
        return self._dirty

    # ---------- File ----------
    def open_click(self, sender, args):
        path = cc.config_path()
        try:
            if not os.path.isfile(path):
                cc.save(cc.empty())
            os.startfile(path)
        except Exception as ex:
            forms.alert("Could not open the file:\n%s\n\nPath: %s" % (ex, path), title=TITLE)

    def load_default_click(self, sender, args):
        """Replace the settings with a default config file's. The default is only read."""
        self._commit()
        dialog = OpenFileDialog()
        dialog.Title = "Select the default config file"
        dialog.Filter = "Config files (*.json)|*.json|All files (*.*)|*.*"
        dialog.CheckFileExists = True
        if os.path.isfile(cc.DEFAULT_CONFIG):
            dialog.InitialDirectory = os.path.dirname(cc.DEFAULT_CONFIG)
            dialog.FileName = os.path.basename(cc.DEFAULT_CONFIG)
        if not dialog.ShowDialog(self):
            return
        source = dialog.FileName
        try:
            if os.path.normcase(os.path.abspath(source)) == os.path.normcase(os.path.abspath(cc.config_path())):
                forms.alert("That file is your own settings file, the one this window saves to.\n\nChoose the "
                            "default config file instead.", title=TITLE)
                return
            cfg = cc.read(source)
        except Exception as ex:
            forms.alert("Could not read the default config:\n%s\n\nPath: %s" % (ex, source), title=TITLE)
            return
        go_on = forms.alert("Replace your settings with the ones in:\n%s\n\nThe default file is only read. Your "
                            "current settings are saved as a backup next to them.%s"
                            % (source, "\n\nYour unsaved changes in this window will be lost." if self._unsaved()
                               else ""), title=TITLE, yes=True, no=True)
        if not go_on:
            return
        try:
            mine = cc.config_path()
            if os.path.isfile(mine):
                cc.write(mine + ".bak", cc.read(mine))
            cfg["notes"] = []
            cc.save(cfg)
        except Exception as ex:
            forms.alert("Could not write your settings:\n%s\n\nPath: %s" % (ex, cc.config_path()), title=TITLE)
            return
        self._fill(cfg)
        self.status_text.Text = "Loaded the default config and saved it"

    # ---------- Closing ----------
    def close_click(self, sender, args):
        self.Close()

    def window_closing(self, sender, args):
        self._commit()
        if self._unsaved():
            discard = forms.alert("You have unsaved changes.\n\nClose without saving?", title=TITLE, yes=True, no=True)
            if not discard:
                args.Cancel = True


def show_editor(doc):
    """Open the window. Refuses when the settings file can't be read, so a broken file is never overwritten."""
    try:
        cfg = cc.load()
    except Exception as ex:
        forms.alert("Could not read the settings:\n%s\n\nPath: %s\n\nFix or remove the file, then try again."
                    % (ex, cc.config_path()), title=TITLE)
        return
    ConfigEditor(doc, cfg).ShowDialog()
