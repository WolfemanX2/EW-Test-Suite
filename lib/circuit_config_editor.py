# -*- coding: utf-8 -*-
# circuit_config_editor module - version v1
# Change log (last change first):
#   v1 - Auto Circuit - Config v1: the combined routing and addressing settings window (Family Defaults; Address and
#        Routing Defaults), replacing the Auto Conduit, Address SLC and Address NAC / Voice config windows.
"""The Auto Circuit - Config window (lib/circuit_config.py holds the settings). show_editor(doc).

Family Defaults tab: every Fire Alarm Device and Electrical Equipment family in the project (and any in the settings
that aren't loaded), each with its types under it (double-click a family, or Expand All). Setting a value on a family
sets it on all its types; a family whose types differ shows <varies>. A blank value is not set.
Address and Routing Defaults tab: conduit elevations per conduit type, Address Groups and Address Rounding values."""
import os

import clr
clr.AddReference("System.Data")
from System import String, Boolean, DBNull
from System.Data import DataTable, DataRowState
from Microsoft.Win32 import OpenFileDialog
from Autodesk.Revit.DB import BuiltInCategory, FilteredElementCollector
from pyrevit import forms

import circuit_config as cc
import mounting_rules         # conduit type labels in the project
import conduit_routing as cr  # reading a length such as 15'-0"
import ew_common as ec        # shared helpers (lib/ew_common.py)

TITLE = "Auto Circuit - Config"
VARIES = "<varies>"
NOT_LOADED = "(not in project)"
CATEGORIES = [(BuiltInCategory.OST_FireAlarmDevices, "Fire Alarm Device"),
              (BuiltInCategory.OST_ElectricalEquipment, "Electrical Equipment")]
OPEN, CLOSED = u"▾", u"▸"
# (DataTable column, settings field)
SETTINGS = [("Mounting", "mounting"), ("DeviceType", "device_type"), ("ConduitType", "conduit_type"),
            ("AddressGroup", "address_group"), ("RoundTo", "round_to")]
SETTING_COLUMNS = dict(SETTINGS)


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
    """{family name: (category label, set of 'Family : Type' keys)} for the loaded device and equipment types."""
    found = {}
    for cat, label in CATEGORIES:
        for t in FilteredElementCollector(doc).OfCategory(cat).WhereElementIsElementType().ToElements():
            try:
                family, key = t.FamilyName, ec.type_key(t)
            except Exception:
                continue
            found.setdefault(family, (label, set()))[1].add(key)
    return found


EDITOR_XAML = """
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Auto Circuit - Config"
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
                        <RowDefinition Height="*"/>
                    </Grid.RowDefinitions>
                    <TextBlock Grid.Row="0" TextWrapping="Wrap" Margin="0,0,0,8"
                               Text="Double-click a family to show or hide its types. A value set on a family is set on all its types; &lt;varies&gt; means its types differ. Blank = not set: the conduit type is asked for, the device is not addressed until it has a Device Type, and Address Group blank asks how many addresses. Address Group and Round To are for Module and Detector types; the groups and rounding values are on the Address and Routing Defaults tab."/>
                    <DockPanel Grid.Row="1" Margin="0,0,0,8" LastChildFill="False">
                        <TextBlock Text="Search:" VerticalAlignment="Center" Margin="0,0,6,0" DockPanel.Dock="Left"/>
                        <TextBox x:Name="search_box" Width="240" TextChanged="search_changed" DockPanel.Dock="Left"/>
                        <Button Content="Expand All" Width="90" Margin="12,0,6,0" Click="expand_click" DockPanel.Dock="Left"/>
                        <Button Content="Collapse All" Width="90" Click="collapse_click" DockPanel.Dock="Left"/>
                    </DockPanel>
                    <DataGrid x:Name="grid" Grid.Row="2" AutoGenerateColumns="False"
                              CanUserAddRows="False" CanUserDeleteRows="False" CanUserSortColumns="False"
                              SelectionMode="Single" SelectionUnit="FullRow" GridLinesVisibility="All"
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
                            <DataGridComboBoxColumn Header="Mounting" SelectedItemBinding="{Binding Mounting}" Width="90"/>
                            <DataGridComboBoxColumn Header="Device Type" SelectedItemBinding="{Binding DeviceType}" Width="120"/>
                            <DataGridComboBoxColumn Header="Conduit Type" SelectedItemBinding="{Binding ConduitType}" Width="220"/>
                            <DataGridComboBoxColumn Header="Address Group" SelectedItemBinding="{Binding AddressGroup}" Width="140"/>
                            <DataGridComboBoxColumn Header="Round To" SelectedItemBinding="{Binding RoundTo}" Width="80"/>
                        </DataGrid.Columns>
                    </DataGrid>
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
                    <Grid Grid.Column="2">
                        <Grid.RowDefinitions>
                            <RowDefinition Height="2*"/>
                            <RowDefinition Height="12"/>
                            <RowDefinition Height="*"/>
                        </Grid.RowDefinitions>
                        <GroupBox Grid.Row="0" Header="Address Groups">
                            <Grid Margin="6">
                                <Grid.RowDefinitions>
                                    <RowDefinition Height="Auto"/>
                                    <RowDefinition Height="*"/>
                                    <RowDefinition Height="Auto"/>
                                </Grid.RowDefinitions>
                                <TextBlock Grid.Row="0" TextWrapping="Wrap" Margin="0,0,0,6"
                                           Text="A name and how many addresses it fills (1-24), e.g. Dual Zone = 12. A type set to 'Choose a group' is offered these when it is addressed. Type in the blank bottom row to add one."/>
                                <DataGrid x:Name="group_grid" Grid.Row="1" AutoGenerateColumns="False"
                                          CanUserAddRows="True" CanUserDeleteRows="True" HeadersVisibility="Column"
                                          GridLinesVisibility="All">
                                    <DataGrid.Columns>
                                        <DataGridTextColumn Header="Group Name" Binding="{Binding Name}" Width="*"/>
                                        <DataGridTextColumn Header="Addresses" Binding="{Binding Count}" Width="90"/>
                                    </DataGrid.Columns>
                                </DataGrid>
                                <Button Grid.Row="2" Content="Delete Selected Groups" Width="160" Margin="0,6,0,0"
                                        HorizontalAlignment="Left" Click="delete_group_click"/>
                            </Grid>
                        </GroupBox>
                        <GroupBox Grid.Row="2" Header="Address Rounding">
                            <Grid Margin="6">
                                <Grid.RowDefinitions>
                                    <RowDefinition Height="Auto"/>
                                    <RowDefinition Height="*"/>
                                    <RowDefinition Height="Auto"/>
                                </Grid.RowDefinitions>
                                <TextBlock Grid.Row="0" TextWrapping="Wrap" Margin="0,0,0,6"
                                           Text="Values offered under Round To: a device starts on the next multiple (5: M004 becomes M005)."/>
                                <DataGrid x:Name="round_grid" Grid.Row="1" AutoGenerateColumns="False"
                                          CanUserAddRows="True" CanUserDeleteRows="True" HeadersVisibility="Column"
                                          GridLinesVisibility="All">
                                    <DataGrid.Columns>
                                        <DataGridTextColumn Header="Round up to a multiple of" Binding="{Binding Value}" Width="*"/>
                                    </DataGrid.Columns>
                                </DataGrid>
                                <Button Grid.Row="2" Content="Delete Selected Values" Width="160" Margin="0,6,0,0"
                                        HorizontalAlignment="Left" Click="delete_round_click"/>
                            </Grid>
                        </GroupBox>
                    </Grid>
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
        self._busy = False      # True while values are copied between a family and its types
        self.conduit_labels = mounting_rules.list_conduit_type_labels(doc)

        text = clr.GetClrType(String)
        self.dt = DataTable("Families")
        for name in ("Arrow", "Name", "Category", "Family", "Key", "Search") + tuple(c for c, _f in SETTINGS):
            self.dt.Columns.Add(name, text)
        self.dt.Columns.Add("IsFamily", clr.GetClrType(Boolean))
        self.dt.Columns.Add("Expanded", clr.GetClrType(Boolean))
        self.dt_elev = DataTable("Elevations")
        self.dt_elev.Columns.Add("ConduitType", text)
        self.dt_elev.Columns.Add("Elevation", text)
        self.dt_groups = DataTable("Groups")
        self.dt_groups.Columns.Add("Name", text)
        self.dt_groups.Columns.Add("Count", text)
        self.dt_round = DataTable("Rounding")
        self.dt_round.Columns.Add("Value", text)

        self._fill(cfg)
        self.dt.ColumnChanging += self._column_changing
        self.dt.ColumnChanged += self._column_changed
        for table in (self.dt_groups, self.dt_round):
            table.RowChanged += self._lists_changed
            table.RowDeleted += self._lists_changed
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
            self.dt_round.Clear()
            in_project = project_types(self.doc)
            families = set(in_project) | set(cfg["families"]) | set(cc.family_of(k) for k in cfg["types"])
            self.family_rows, self.type_rows = {}, {}
            for family in sorted(families, key=lambda f: f.lower()):
                category, keys = in_project.get(family, (NOT_LOADED, set()))
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
            for name, count in cfg["address_groups"]:
                row = self.dt_groups.NewRow()
                row["Name"], row["Count"] = name, str(count)
                self.dt_groups.Rows.Add(row)
            for value in cfg["rounding"]:
                row = self.dt_round.NewRow()
                row["Value"] = str(value)
                self.dt_round.Rows.Add(row)
            labels = list(self.conduit_labels) + sorted(l for l in cfg["elevations"] if l not in self.conduit_labels)
            for label in labels:
                row = self.dt_elev.NewRow()
                row["ConduitType"], row["Elevation"] = label, cfg["elevations"].get(label, u"")
                self.dt_elev.Rows.Add(row)
            self.notes = list(cfg["notes"])
            for table in (self.dt, self.dt_elev, self.dt_groups, self.dt_round):
                table.AcceptChanges()
        finally:
            self._busy = False
        self.view = self.dt.DefaultView
        self._filter()
        self.grid.ItemsSource = self.view
        self.elev_grid.ItemsSource = self.dt_elev.DefaultView
        self.group_grid.ItemsSource = self.dt_groups.DefaultView
        self.round_grid.ItemsSource = self.dt_round.DefaultView
        self._set_choices(cfg)
        self.status_text.Text = "%d families, %d types" % (len(self.family_rows),
                                                           sum(len(v) for v in self.type_rows.values()))

    def _new_row(self, name, family, category, key, is_family):
        row = self.dt.NewRow()
        row["Arrow"] = CLOSED if is_family else u""
        row["Name"], row["Family"], row["Category"], row["Key"] = name, family, category, key
        row["Search"] = (key or family).lower()
        row["IsFamily"], row["Expanded"] = is_family, False
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
        """The values each drop-down offers (the current lists of groups and rounding values)."""
        groups = [cell_text(r["Name"]) for r in self._live(self.dt_groups) if cell_text(r["Name"])]
        rounding = [cell_text(r["Value"]) for r in self._live(self.dt_round) if cell_text(r["Value"])]
        used = dict((c, set(cell_text(r[c]) for r in self._live(self.dt))) for c, _f in SETTINGS)

        def choices(base, column):
            extra = sorted(v for v in used[column] if v and v != VARIES and v not in base)
            return [u""] + base + extra + [VARIES]

        columns = self.grid.Columns
        columns[3].ItemsSource = choices(list(cc.MOUNTINGS), "Mounting")
        columns[4].ItemsSource = choices(list(cc.DEVICE_TYPES), "DeviceType")
        columns[5].ItemsSource = choices(list(self.conduit_labels), "ConduitType")
        columns[6].ItemsSource = choices([cc.CHOOSE_GROUP] + groups, "AddressGroup")
        columns[7].ItemsSource = choices(rounding, "RoundTo")

    @staticmethod
    def _live(table):
        for row in table.Rows:
            if row.RowState != DataRowState.Deleted and row.RowState != DataRowState.Detached:
                yield row

    def _filter(self):
        text = (self.search_box.Text or u"").strip().lower()
        rule = "(IsFamily = True OR Expanded = True)"
        if text:
            rule += " AND Search LIKE '*%s*'" % _like(text)
        self.view.RowFilter = rule

    def _commit(self):
        for grid in (self.grid, self.elev_grid, self.group_grid, self.round_grid):
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
        try:
            self._set_choices()
        except Exception:
            pass

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
        if column is not None and column.DisplayIndex > 2:
            return      # a double-click on a setting opens its drop-down instead
        item = self.grid.SelectedItem
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
        self.status_text.Text = "%d row(s) deleted (unsaved)" % len(victims)

    def delete_group_click(self, sender, args):
        self._delete_selected(self.group_grid)

    def delete_round_click(self, sender, args):
        self._delete_selected(self.round_grid)

    # ---------- Saving ----------
    def _collect(self):
        """(config, [errors]) from the window."""
        cfg, errors = cc.empty(), []
        names = set()
        for n, row in enumerate(self._live(self.dt_groups), start=1):
            name, count = cell_text(row["Name"]), cell_text(row["Count"])
            if not name and not count:
                continue
            if not name:
                errors.append("Address Groups row %d: the group name is blank." % n)
                continue
            if name in names or name in (cc.CHOOSE_GROUP, VARIES):
                errors.append("Address Groups row %d: '%s' is %s." % (n, name, "used twice" if name in names
                                                                       else "a reserved name"))
                continue
            if not count.isdigit() or not 1 <= int(count) <= cc.MAX_ADDRESSES:
                errors.append("Address Groups row %d (%s): Addresses must be a whole number from 1 to %d."
                              % (n, name, cc.MAX_ADDRESSES))
                continue
            names.add(name)
            cfg["address_groups"].append((name, int(count)))
        for n, row in enumerate(self._live(self.dt_round), start=1):
            value = cell_text(row["Value"])
            if not value:
                continue
            if not value.isdigit() or int(value) < 2:
                errors.append("Address Rounding row %d: '%s' must be a whole number, 2 or more." % (n, value))
                continue
            if int(value) not in cfg["rounding"]:
                cfg["rounding"].append(int(value))
        cfg["rounding"].sort()
        cr.bind(self.doc, None, TITLE)
        for row in self._live(self.dt_elev):
            label, text = cell_text(row["ConduitType"]), cell_text(row["Elevation"])
            if not text:
                continue
            if cr.parse_length(text) is None:
                errors.append("Conduit Elevations (%s): '%s' can't be read as a length, e.g. 15'-0\"." % (label, text))
                continue
            cfg["elevations"][label] = text

        groups = set(name for name, _c in cfg["address_groups"])
        for family in sorted(self.family_rows, key=lambda f: f.lower()):
            frow, trows = self.family_rows[family], self.type_rows[family]
            for column, field in SETTINGS:
                rows = trows or [frow]
                for row in rows:
                    value = cell_text(row[column])
                    where = cell_text(row["Key"]) or family
                    if field == "address_group" and value and value not in groups and value != cc.CHOOSE_GROUP:
                        errors.append("%s: Address Group '%s' is not one of the Address Groups." % (where, value))
                    if field == "round_to" and value and (not value.isdigit() or int(value) not in cfg["rounding"]):
                        errors.append("%s: Round To %s is not one of the Address Rounding values." % (where, value))
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
        for table in (self.dt, self.dt_elev, self.dt_groups, self.dt_round):
            table.AcceptChanges()
        self.status_text.Text = "Saved"

    def _unsaved(self):
        return any(t.GetChanges() is not None for t in (self.dt, self.dt_elev, self.dt_groups, self.dt_round))

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
