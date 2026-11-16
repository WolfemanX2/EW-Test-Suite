# -*- coding: utf-8 -*-
# Riser Symbols script - version v1
__title__ = "Riser\nSymbols"
__doc__ = ("Editable table of the symbol the riser tools draw for each Family : Type.\n\n"
           "The symbol is any loaded Generic Annotation or Detail Item type. 'Add Types From Project' lists "
           "the loaded Fire Alarm Device types, or the Electrical Equipment types for panels.")

import clr
clr.AddReference("System.Data")
from System import String, DBNull
from System.Data import DataTable, DataRowState
from Autodesk.Revit.DB import FilteredElementCollector, BuiltInCategory
from pyrevit import revit, forms

import slc_riser as sr

doc = revit.doc
TITLE = "Riser Symbols"
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
        Title="Riser Symbols"
        Width="860" Height="520" MinWidth="680" MinHeight="380"
        WindowStartupLocation="CenterScreen"
        Closing="window_closing">
    <Grid Margin="12">
        <Grid.RowDefinitions>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="*"/>
            <RowDefinition Height="Auto"/>
        </Grid.RowDefinitions>

        <TextBlock Grid.Row="0" TextWrapping="Wrap" Margin="0,0,0,8"
                   Text="Choose the symbol drawn on riser diagrams for each Family Type. Symbols are the Generic Annotation and Detail Item types loaded in this project. Type in the blank bottom row to add an entry (Family : Type, exactly as Revit shows it)."/>

        <DataGrid x:Name="grid" Grid.Row="1"
                  AutoGenerateColumns="False"
                  CanUserAddRows="True" CanUserDeleteRows="True"
                  SelectionMode="Extended" SelectionUnit="FullRow"
                  GridLinesVisibility="All" HeadersVisibility="Column">
            <DataGrid.Columns>
                <DataGridTextColumn Header="Family Type"
                                    Binding="{Binding FamilyType}" Width="*"/>
                <DataGridComboBoxColumn Header="Riser Symbol"
                                        SelectedItemBinding="{Binding Symbol}"
                                        Width="*"/>
            </DataGrid.Columns>
        </DataGrid>

        <DockPanel Grid.Row="2" Margin="0,10,0,0" LastChildFill="False">
            <Button Content="Add Types From Project..." Width="170"
                    Margin="0,0,8,0" Click="add_click" DockPanel.Dock="Left"/>
            <Button Content="Set Symbol For Selected..." Width="170"
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


class TableEditor(forms.WPFWindow):
    def __init__(self, table):
        forms.WPFWindow.__init__(self, EDITOR_XAML, literal_string=True)

        # Symbols loaded now, plus any saved ones that aren't loaded in this project (so they aren't lost).
        self.symbols = sorted(set(sr.available_symbols(doc).keys()) | set(v for v in table.values() if v))

        self.dt = DataTable("RiserSymbols")
        self.dt.Columns.Add("FamilyType", clr.GetClrType(String))
        sym_col = self.dt.Columns.Add("Symbol", clr.GetClrType(String))
        sym_col.DefaultValue = ""
        self.grid.Columns[1].ItemsSource = [""] + self.symbols

        for key in sorted(table.keys()):
            self._add_row(key, table[key])
        self.dt.AcceptChanges()
        self.grid.ItemsSource = self.dt.DefaultView
        self.status_text.Text = "%d type(s) loaded" % len(table)

    def _add_row(self, key, symbol):
        row = self.dt.NewRow()
        row["FamilyType"] = key
        row["Symbol"] = symbol
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
            self._add_row(key, "")
        self.status_text.Text = "%d type(s) added (unsaved) - choose a Riser Symbol for each" % len(picked)

    def set_click(self, sender, args):
        self.grid.CommitEdit()
        rows = [i.Row for i in list(self.grid.SelectedItems) if hasattr(i, "Row")]
        if not rows:
            forms.alert("Select one or more rows first.", title=TITLE)
            return
        if not self.symbols:
            forms.alert("No Generic Annotation or Detail Item types are loaded in this project.", title=TITLE)
            return
        symbol = forms.SelectFromList.show(self.symbols, title="Symbol for the %d selected row(s)" % len(rows),
                                           button_name="Set Symbol", multiselect=False)
        if not symbol:
            return
        for row in rows:
            row["Symbol"] = symbol
        self.status_text.Text = "Symbol set on %d row(s) (unsaved)" % len(rows)

    def delete_click(self, sender, args):
        self.grid.CommitEdit()
        victims = [i for i in list(self.grid.SelectedItems) if hasattr(i, "Row")]
        for item in victims:
            item.Row.Delete()
        self.status_text.Text = "%d row(s) deleted (unsaved)" % len(victims)

    def save_click(self, sender, args):
        self.grid.CommitEdit()
        table, errors, seen, blank = {}, [], set(), 0
        for idx, row in enumerate(self._live_rows(), start=1):
            key = cell_text(row["FamilyType"])
            symbol = cell_text(row["Symbol"])
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
            table[key] = symbol

        if errors:
            forms.alert("Nothing was saved. Please fix:\n\n" + "\n".join(errors), title=TITLE)
            return
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
        if self.dt.GetChanges() is not None:
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
    TableEditor(table).ShowDialog()


main()
