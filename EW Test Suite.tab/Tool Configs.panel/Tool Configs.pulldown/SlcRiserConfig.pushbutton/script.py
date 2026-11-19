# -*- coding: utf-8 -*-
# SLC Riser - Config script - version v6
__title__ = "SLC Riser - Config v6"
__doc__ = ("Drawing settings for SLC Riser (drafting view scale, spacing between devices, devices per line "
           "before wrapping, wrap rounding, address text offset) and the table of the symbol drawn for each Family : Type.\n\n"
           "The symbols are any loaded Generic Annotation or Detail Item types. A type can have several, drawn in "
           "order: once each, or (Repeat) as a pattern repeated along the device's addresses with one address "
           "under each symbol. 'Add Types From Project' lists "
           "the loaded Fire Alarm Device types, or the Electrical Equipment types for panels.")

import clr
clr.AddReference("System.Data")
from System import String, Boolean, DBNull
from System.Data import DataTable, DataRowState
from Autodesk.Revit.DB import FilteredElementCollector, BuiltInCategory
from pyrevit import revit, forms

import slc_riser as sr

doc = revit.doc
TITLE = "SLC Riser - Config"
SCOPES = [("Fire Alarm Device types", BuiltInCategory.OST_FireAlarmDevices),
          ("Electrical Equipment types (panels)", BuiltInCategory.OST_ElectricalEquipment)]


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


EDITOR_XAML = """
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="SLC Riser - Config"
        Width="980" Height="680" MinWidth="680" MinHeight="480"
        WindowStartupLocation="CenterScreen"
        Closing="window_closing">
    <Grid Margin="12">
        <Grid.RowDefinitions>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="*"/>
            <RowDefinition Height="Auto"/>
        </Grid.RowDefinitions>

        <GroupBox Grid.Row="0" Header="Riser drawing" Margin="0,0,0,10" Padding="8">
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
                </Grid.RowDefinitions>
                <TextBlock Grid.Row="0" Grid.Column="0" Text="Drafting view scale:" VerticalAlignment="Center" Margin="0,0,8,6"/>
                <ComboBox x:Name="scale_box" Grid.Row="0" Grid.Column="1" Margin="0,0,0,6" IsEditable="False"
                          SelectionChanged="setting_changed"/>
                <TextBlock Grid.Row="0" Grid.Column="3" Text="Spacing between devices (ft):" VerticalAlignment="Center" Margin="0,0,8,6"/>
                <TextBox x:Name="spacing_box" Grid.Row="0" Grid.Column="4" Margin="0,0,0,6" TextChanged="setting_changed"/>
                <TextBlock Grid.Row="1" Grid.Column="0" Text="Devices before wrapping:" VerticalAlignment="Center" Margin="0,0,8,0"/>
                <TextBox x:Name="per_line_box" Grid.Row="1" Grid.Column="1" Margin="0,0,0,6" TextChanged="setting_changed"/>
                <TextBlock Grid.Row="1" Grid.Column="3" Text="Address text below line (in):" VerticalAlignment="Center" Margin="0,0,8,6"/>
                <TextBox x:Name="offset_box" Grid.Row="1" Grid.Column="4" Margin="0,0,0,6" TextChanged="setting_changed"/>
                <TextBlock Grid.Row="2" Grid.Column="0" Text="Wrap rounding (devices):" VerticalAlignment="Center" Margin="0,0,8,0"
                           ToolTip="A line only wraps when it would have more than Devices before wrapping + this many devices. 40 and 5: 41 to 45 devices stay on one line."/>
                <TextBox x:Name="rounding_box" Grid.Row="2" Grid.Column="1" TextChanged="setting_changed"
                         ToolTip="A line only wraps when it would have more than Devices before wrapping + this many devices. 40 and 5: 41 to 45 devices stay on one line."/>
                <TextBlock Grid.Row="2" Grid.Column="3" Grid.ColumnSpan="2" VerticalAlignment="Center" Margin="0,0,8,0"
                           Foreground="Gray" TextWrapping="Wrap"
                           Text="Wraps only past Devices before wrapping + rounding."/>
                <Button Grid.Row="2" Grid.Column="5" Content="Defaults" Width="80" HorizontalAlignment="Right"
                        Click="defaults_click"/>
            </Grid>
        </GroupBox>

        <TextBlock Grid.Row="1" TextWrapping="Wrap" Margin="0,0,0,8"
                   Text="Choose the symbols drawn on riser diagrams for each Family Type, in order (double-click a row, or use Set Symbols). Without Repeat each symbol is drawn once with one address, and the last symbol takes the rest. With Repeat the symbols are a pattern repeated along the device's addresses, one address under each: addresses 1-18 with 3 symbols draws the 3 symbols 6 times. Symbols are the Generic Annotation and Detail Item types loaded in this project. Type in the blank bottom row to add an entry (Family : Type, exactly as Revit shows it)."/>

        <DataGrid x:Name="grid" Grid.Row="2" MouseDoubleClick="grid_double_click"
                  AutoGenerateColumns="False"
                  CanUserAddRows="True" CanUserDeleteRows="True"
                  SelectionMode="Extended" SelectionUnit="FullRow"
                  GridLinesVisibility="All" HeadersVisibility="Column">
            <DataGrid.Columns>
                <DataGridTextColumn Header="Family Type"
                                    Binding="{Binding FamilyType}" Width="*"/>
                <DataGridTextColumn Header="Riser Symbols (in order)"
                                    Binding="{Binding Symbol}" IsReadOnly="True" Width="1.4*"/>
                <DataGridCheckBoxColumn Header="Repeat"
                                        Binding="{Binding Repeat, UpdateSourceTrigger=PropertyChanged}" Width="70"/>
            </DataGrid.Columns>
        </DataGrid>

        <DockPanel Grid.Row="3" Margin="0,10,0,0" LastChildFill="False">
            <Button Content="Add Types From Project..." Width="170"
                    Margin="0,0,8,0" Click="add_click" DockPanel.Dock="Left"/>
            <Button Content="Set Symbols For Selected..." Width="180"
                    Margin="0,0,8,0" Click="set_click" DockPanel.Dock="Left"/>
            <Button Content="Delete Selected Rows" Width="140"
                    Click="delete_click" DockPanel.Dock="Left"/>
            <Button Content="Close" Width="80" Click="close_click"
                    DockPanel.Dock="Right"/>
            <Button Content="Save" Width="80" Margin="0,0,8,0" Click="save_click"
                    DockPanel.Dock="Right"/>
            <TextBlock x:Name="status_text" VerticalAlignment="Center"
                       Margin="12,0,0,0" DockPanel.Dock="Left"/>
        </DockPanel>
    </Grid>
</Window>
"""


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
            <CheckBox x:Name="repeat_check" DockPanel.Dock="Left" VerticalAlignment="Center"
                      Content="Repeat the pattern along the device's addresses (one address under each symbol)"/>
            <Button Content="Cancel" Width="80" IsCancel="True" Click="cancel_click" DockPanel.Dock="Right"/>
            <Button Content="OK" Width="80" Margin="0,0,8,0" IsDefault="True" Click="ok_click" DockPanel.Dock="Right"/>
        </DockPanel>
    </Grid>
</Window>
"""


class SymbolListEditor(forms.WPFWindow):
    """Choose the symbols of a type, in order, and whether they repeat. self.result = (symbols, repeat) or None."""
    def __init__(self, title, symbols, current, repeat):
        forms.WPFWindow.__init__(self, SYMBOL_LIST_XAML, literal_string=True)
        self.all_symbols = list(symbols)
        self.result = None
        self.title_text.Text = ("Riser symbols for %s. A symbol can be added more than once. Without Repeat each "
                                "symbol is drawn once with one address and the last takes the rest; with Repeat "
                                "the list is a pattern repeated along the device's addresses." % title)
        self.available_list.ItemsSource = self.all_symbols
        for sym in current:
            self.chosen_list.Items.Add(sym)
        self.repeat_check.IsChecked = bool(repeat)

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
        self.result = ([str(x) for x in self.chosen_list.Items], bool(self.repeat_check.IsChecked))
        self.Close()

    def cancel_click(self, sender, args):
        self.Close()


def number_text(v):
    """4.5 -> '4.5', 6.0 -> '6'"""
    return ("%.4f" % v).rstrip("0").rstrip(".") if isinstance(v, float) else str(v)


class TableEditor(forms.WPFWindow):
    def __init__(self, table, settings):
        forms.WPFWindow.__init__(self, EDITOR_XAML, literal_string=True)
        self._loading = True
        self.settings_dirty = False
        self.scale_box.ItemsSource = [label for label, _ in sr.SCALES]
        self._show_settings(settings)

        # Symbols loaded now, plus any saved ones that aren't loaded in this project (so they aren't lost).
        saved = set()
        for entry in table.values():
            saved.update(entry["symbols"])
        self.symbols = sorted(set(sr.available_symbols(doc).keys()) | saved)

        self.dt = DataTable("RiserSymbols")
        self.dt.Columns.Add("FamilyType", clr.GetClrType(String))
        sym_col = self.dt.Columns.Add("Symbol", clr.GetClrType(String))
        sym_col.DefaultValue = ""
        rep_col = self.dt.Columns.Add("Repeat", clr.GetClrType(Boolean))
        rep_col.DefaultValue = False

        for key in sorted(table.keys()):
            self._add_row(key, table[key]["symbols"], table[key]["repeat"])
        self.dt.AcceptChanges()
        self.grid.ItemsSource = self.dt.DefaultView
        self.status_text.Text = "%d type(s) loaded" % len(table)
        self._loading = False

    # ---- Drawing settings ----
    def _show_settings(self, settings):
        self._loading = True
        scale = settings["view_scale"]
        labels = [label for label, num in sr.SCALES if num == scale]
        if not labels:     # a scale saved by hand that isn't in the list
            label = "1 : %d" % scale
            self.scale_box.ItemsSource = [l for l, _ in sr.SCALES] + [label]
            labels = [label]
        self.scale_box.SelectedItem = labels[0]
        self.spacing_box.Text = number_text(settings["device_spacing_ft"])
        self.per_line_box.Text = number_text(settings["devices_per_line"])
        self.rounding_box.Text = number_text(settings["wrap_rounding"])
        self.offset_box.Text = number_text(settings["label_offset_in"])
        self._loading = False

    def setting_changed(self, sender, args):
        if not self._loading:
            self.settings_dirty = True

    def defaults_click(self, sender, args):
        self._show_settings(sr.DEFAULT_SETTINGS)
        self.settings_dirty = True
        self.status_text.Text = "Default drawing settings shown (unsaved)"

    def _read_settings(self, errors):
        """The settings typed in the window, adding a message to errors for each one that isn't valid."""
        out = {}
        label = self.scale_box.SelectedItem
        scale = dict(sr.SCALES).get(label)
        if scale is None and label and str(label).startswith("1 : "):
            scale = int(str(label)[4:])
        if scale is None:
            errors.append("Choose a drafting view scale.")
        out["view_scale"] = scale
        for key, box, what, kind in [("device_spacing_ft", self.spacing_box, "Spacing between devices", float),
                                     ("devices_per_line", self.per_line_box, "Devices before wrapping", int),
                                     ("wrap_rounding", self.rounding_box, "Wrap rounding", int),
                                     ("label_offset_in", self.offset_box, "Address text below line", float)]:
            lo, hi = sr.SETTING_LIMITS[key]
            text = (box.Text or "").strip()
            try:
                value = kind(text)
            except Exception:
                value = None
            if value is None or not lo <= value <= hi:
                errors.append("%s must be a %s from %s to %s." % (what, "whole number" if kind is int else "number",
                                                                  number_text(lo), number_text(hi)))
            out[key] = value
        return out

    def _add_row(self, key, symbols, repeat=False):
        row = self.dt.NewRow()
        row["FamilyType"] = key
        row["Symbol"] = SEP.join(symbols)
        row["Repeat"] = bool(repeat)
        self.dt.Rows.Add(row)

    def _live_rows(self):
        for row in self.dt.Rows:
            if row.RowState != DataRowState.Deleted:
                yield row

    # ---- Buttons ----
    def add_click(self, sender, args):
        self.grid.CommitEdit()
        existing = set(cell_text(r["FamilyType"]) for r in self._live_rows())
        scope = forms.CommandSwitchWindow.show([s[0] for s in SCOPES],
                                               message="Which loaded types do you want to list?")
        if not scope:
            return
        keys = sorted(loaded_type_keys(dict(SCOPES)[scope]) - existing)
        if not keys:
            forms.alert("No additional types to add.", title=TITLE)
            return
        picked = forms.SelectFromList.show(keys, title="Add types to the table",
                                           button_name="Add Selected", multiselect=True)
        if not picked:
            return
        for key in picked:
            self._add_row(key, [])
        self.status_text.Text = "%d type(s) added (unsaved) - choose a Riser Symbol for each" % len(picked)

    def set_click(self, sender, args):
        self.grid.CommitEdit()
        rows = [i.Row for i in list(self.grid.SelectedItems) if hasattr(i, "Row")]
        self._edit_rows(rows)

    def grid_double_click(self, sender, args):
        item = self.grid.CurrentItem
        if item is not None and hasattr(item, "Row"):
            self.grid.CommitEdit()
            self._edit_rows([item.Row])

    def _edit_rows(self, rows):
        if not rows:
            forms.alert("Select one or more rows first.", title=TITLE)
            return
        if not self.symbols:
            forms.alert("No Generic Annotation or Detail Item types are loaded in this project.", title=TITLE)
            return
        first = rows[0]
        current = [x for x in cell_text(first["Symbol"]).split(SEP) if x]
        repeat = bool(first["Repeat"]) if not isinstance(first["Repeat"], DBNull) else False
        title = cell_text(first["FamilyType"]) if len(rows) == 1 else "%d selected types" % len(rows)
        dlg = SymbolListEditor(title, self.symbols, current, repeat)
        dlg.ShowDialog()
        if dlg.result is None:
            return
        symbols, repeat = dlg.result
        for row in rows:
            row["Symbol"] = SEP.join(symbols)
            row["Repeat"] = repeat
        self.status_text.Text = "Symbols set on %d row(s) (unsaved)" % len(rows)

    def delete_click(self, sender, args):
        self.grid.CommitEdit()
        victims = [i for i in list(self.grid.SelectedItems) if hasattr(i, "Row")]
        for item in victims:
            item.Row.Delete()
        self.status_text.Text = "%d row(s) deleted (unsaved)" % len(victims)

    def save_click(self, sender, args):
        self.grid.CommitEdit()
        table, errors, seen, blank = {}, [], set(), 0
        settings = self._read_settings(errors)
        for idx, row in enumerate(self._live_rows(), start=1):
            key = cell_text(row["FamilyType"])
            symbol = cell_text(row["Symbol"])
            repeat = row["Repeat"]
            repeat = False if isinstance(repeat, DBNull) or repeat is None else bool(repeat)
            if not key and not symbol:
                continue    # fully blank row
            if not key:
                errors.append("Row %d: Family Type is blank." % idx)
                continue
            if key in seen:
                errors.append("Row %d: duplicate Family Type '%s'." % (idx, key))
                continue
            seen.add(key)
            if not symbol:
                blank += 1
            table[key] = sr.new_entry([x for x in symbol.split(SEP) if x], repeat)

        if errors:
            forms.alert("Nothing was saved. Please fix:\n\n" + "\n".join(errors), title=TITLE)
            return
        try:
            sr.save_settings(settings)
        except Exception as ex:
            forms.alert("Could not save the drawing settings:\n%s\n\nPath: %s" % (ex, sr.settings_path()),
                        title=TITLE)
            return
        self.settings_dirty = False
        try:
            sr.save_table(table)
        except Exception as ex:
            forms.alert("Could not save the symbol table:\n%s\n\nPath: %s" % (ex, sr.table_path()), title=TITLE)
            return
        self.dt.AcceptChanges()
        self.status_text.Text = "Saved %d type(s)" % len(table)
        if blank:
            self.status_text.Text += " - %d still have no symbol" % blank

    def close_click(self, sender, args):
        self.Close()

    def window_closing(self, sender, args):
        try:
            self.grid.CommitEdit()
        except Exception:
            pass
        if self.dt.GetChanges() is not None or self.settings_dirty:
            discard = forms.alert("You have unsaved changes.\n\nClose without saving?",
                                  title=TITLE, yes=True, no=True)
            if not discard:
                args.Cancel = True


def main():
    try:
        table = sr.load_table()
    except Exception as ex:
        forms.alert("Could not read the symbol table:\n%s\n\nPath: %s" % (ex, sr.table_path()), title=TITLE)
        return
    try:
        settings = sr.load_settings()
    except Exception as ex:
        forms.alert("Could not read the drawing settings, so the defaults are shown:\n%s\n\nPath: %s"
                    % (ex, sr.settings_path()), title=TITLE)
        settings = dict(sr.DEFAULT_SETTINGS)
    TableEditor(table, settings).ShowDialog()


main()
