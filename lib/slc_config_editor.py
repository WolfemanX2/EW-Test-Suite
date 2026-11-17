# -*- coding: utf-8 -*-
# slc_config_editor module - version v2
"""The Address SLC - Config window: editable table of the Family : Type rules used by Address SLC.
Opened by the Address SLC - Config button and by Shift+Click on Address SLC."""
import os

import clr
clr.AddReference("System.Data")
from System import String, DBNull
from System.Data import DataTable, DataRowState
from Microsoft.Win32 import OpenFileDialog
from Autodesk.Revit.DB import StorageType
from pyrevit import forms

import slc_addressing as slc

TITLE = "Address SLC - Config"
KIND_BY_NAME = dict((name, kind) for kind, name in slc.KIND_NAMES.items())


def cell_text(v):
    if v is None or isinstance(v, DBNull):
        return ""
    return (u"%s" % v).strip()


# ---------- Loaded family scan ----------
def inspect_family(doc, fam):
    """Number of SLC Address instance text parameters inside a family file, found by opening it in the
    background (nothing is modified or reloaded). None = can't inspect."""
    fdoc = None
    try:
        if fam.IsInPlace or not fam.IsEditable:
            return None
        fdoc = doc.EditFamily(fam)
    except Exception:
        return None
    try:
        count = 0
        for fp in fdoc.FamilyManager.Parameters:
            try:
                if (fp.IsInstance and fp.StorageType == StorageType.String
                        and slc.param_position(fp.Definition.Name) is not None):
                    count += 1
            except Exception:
                pass
        return count
    except Exception:
        return None
    finally:
        try:
            fdoc.Close(False)
        except Exception:
            pass


def loaded_types_info(doc, family_cache):
    """{"Family : Type": (address parameter count or None, source)} for ALL loaded Fire Alarm Device types.
    source = 'placed device' or 'family file'. family_cache {family id: count or None} avoids re-inspecting."""
    reader = slc.AddressParamReader()
    placed = {}         # family id -> address parameter count, from the first placed instance of each type
    seen_types = set()
    for el in slc.device_instances(doc):
        tid = slc.eid_int(el.GetTypeId())
        if tid in seen_types:
            continue
        seen_types.add(tid)
        fam = getattr(doc.GetElement(el.GetTypeId()), "Family", None)
        if fam is None:
            continue
        fid = slc.eid_int(fam.Id)
        placed[fid] = max(placed.get(fid, 0), len(reader.get(el)))

    fams = {}           # family id -> [Family, [type keys]]
    for s in slc.device_types(doc):
        fam = getattr(s, "Family", None)
        if fam is None:
            continue
        try:
            key = s.FamilyName + " : " + s.Name
        except Exception:
            continue
        fams.setdefault(slc.eid_int(fam.Id), [fam, []])[1].append(key)

    todo = [fid for fid in fams if fid not in placed and fid not in family_cache]
    if todo:
        with forms.ProgressBar(title="Inspecting unplaced families ({value} of {max_value})",
                               cancellable=True) as pb:
            for i, fid in enumerate(todo, start=1):
                if pb.cancelled:
                    break
                family_cache[fid] = inspect_family(doc, fams[fid][0])
                pb.update_progress(i, len(todo))

    result = {}
    for fid, (fam, keys) in fams.items():
        if fid in placed:
            count, src = placed[fid], "placed device"
        else:
            count, src = family_cache.get(fid), "family file"
        for k in keys:
            result[k] = (count, src)
    return result


# ---------- Editor window ----------
EDITOR_XAML = """
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Address SLC - Config"
        Width="1160" Height="520" MinWidth="980" MinHeight="380"
        WindowStartupLocation="CenterScreen"
        Closing="window_closing">
    <Grid Margin="12">
        <Grid.RowDefinitions>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="*"/>
            <RowDefinition Height="Auto"/>
        </Grid.RowDefinitions>

        <TextBlock Grid.Row="0" TextWrapping="Wrap" Margin="0,0,0,8"
                   Text="Define how each Family Type is addressed. Number of Addresses blank = the tool prompts for the count. Address Options = named choices offered when the device is picked, typed as &quot;Label&quot;:Number and separated by commas, e.g. &quot;Single Zone&quot;:6, &quot;Dual Zone&quot;:12, &quot;Triple Zone&quot;:23 (leave Number of Addresses blank for these). Round Up To Multiple Of = type any whole number (2-999), e.g. 5 = start on the next multiple of 5 (M004 becomes M005). Type in the blank bottom row to add an entry."/>

        <DataGrid x:Name="grid" Grid.Row="1"
                  AutoGenerateColumns="False"
                  CanUserAddRows="True" CanUserDeleteRows="True"
                  SelectionMode="Extended" SelectionUnit="FullRow"
                  GridLinesVisibility="All" HeadersVisibility="Column">
            <DataGrid.Columns>
                <DataGridTextColumn Header="Family Type" Binding="{Binding FamilyType}" Width="*"/>
                <DataGridComboBoxColumn Header="Device Type" SelectedItemBinding="{Binding DeviceType}"
                                        Width="100"/>
                <DataGridComboBoxColumn Header="Number of Addresses" SelectedItemBinding="{Binding Addresses}"
                                        Width="140"/>
                <DataGridTextColumn Header="Address Options" Binding="{Binding Options}" Width="300"/>
                <DataGridTextColumn Header="Round Up To Multiple Of" Binding="{Binding RoundTo}" Width="170"/>
            </DataGrid.Columns>
        </DataGrid>

        <DockPanel Grid.Row="2" Margin="0,10,0,0" LastChildFill="False">
            <Button Content="Add Types From Project..." Width="170" Margin="0,0,8,0"
                    Click="add_click" DockPanel.Dock="Left"/>
            <Button Content="Delete Selected Rows" Width="140" Margin="0,0,8,0"
                    Click="delete_click" DockPanel.Dock="Left"/>
            <Button x:Name="open_button" Content="Open Table File" Width="110" Margin="0,0,8,0"
                    Click="open_click" DockPanel.Dock="Left"/>
            <Button Content="Load Default Config..." Width="150" Click="load_default_click"
                    DockPanel.Dock="Left"
                    ToolTip="Copy the rules from a default config file into your local config. The default file is only read, never changed."/>
            <Button Content="Close" Width="80" Click="close_click" DockPanel.Dock="Right"/>
            <Button Content="Save" Width="80" Margin="0,0,8,0" Click="save_click" DockPanel.Dock="Right"/>
            <TextBlock x:Name="status_text" VerticalAlignment="Center" Margin="12,0,0,0"
                       DockPanel.Dock="Left"/>
        </DockPanel>
    </Grid>
</Window>
"""


class ConfigEditor(forms.WPFWindow):
    def __init__(self, doc, table):
        forms.WPFWindow.__init__(self, EDITOR_XAML, literal_string=True)
        self.doc = doc
        self._family_cache = {}     # family id -> address parameter count (or None)

        # Data model: DataTable binds cleanly to a WPF DataGrid. Every column is text so a cell can be blank;
        # the values are checked when the table is saved.
        self.dt = DataTable("AddressingConfig")
        string_type = clr.GetClrType(String)
        self.dt.Columns.Add("FamilyType", string_type)
        self.dt.Columns.Add("DeviceType", string_type).DefaultValue = slc.KIND_NAMES[slc.MODULE]
        self.dt.Columns.Add("Addresses", string_type).DefaultValue = "1"
        self.dt.Columns.Add("Options", string_type).DefaultValue = ""
        self.dt.Columns.Add("RoundTo", string_type).DefaultValue = ""

        self.grid.Columns[1].ItemsSource = [slc.KIND_NAMES[k] for k in slc.KINDS]
        self.grid.Columns[2].ItemsSource = [""] + [str(i) for i in range(1, slc.MAX_ADDRESSES + 1)]

        self._fill(table)
        self.grid.ItemsSource = self.dt.DefaultView
        self.status_text.Text = "%d type(s) loaded" % len(table)
        self.open_button.ToolTip = slc.table_path()

    # ---- Helpers ----
    def _add_row(self, key, rule):
        row = self.dt.NewRow()
        row["FamilyType"] = key
        row["DeviceType"] = slc.KIND_NAMES[rule["kind"]]
        row["Addresses"] = str(rule["count"]) if rule["count"] else ""
        row["Options"] = slc.format_options(rule["options"])
        row["RoundTo"] = str(rule["round_to"]) if rule["round_to"] else ""
        self.dt.Rows.Add(row)

    def _fill(self, table):
        """Replace every row with the table's rules and mark the grid as saved."""
        self.dt.Clear()
        for key in sorted(table.keys()):
            self._add_row(key, table[key])
        self.dt.AcceptChanges()

    def _live_rows(self):
        for row in self.dt.Rows:
            if row.RowState != DataRowState.Deleted:
                yield row

    def _commit(self):
        try:
            self.grid.CommitEdit()      # the cell being typed in
            self.grid.CommitEdit()      # its row
        except Exception:
            pass

    def _alert(self, text):
        forms.alert(text, title=TITLE)

    # ---- Buttons ----
    def add_click(self, sender, args):
        self._commit()
        existing = set(cell_text(r["FamilyType"]) for r in self._live_rows())

        scope = forms.CommandSwitchWindow.show(
            ["All loaded types", "Only types with SLC Address"],
            message="Which loaded Fire Alarm Device types do you want to list?")
        if not scope:
            return
        only_address = scope.startswith("Only")

        try:
            info = loaded_types_info(self.doc, self._family_cache)
        except Exception as ex:
            self._alert("Could not list the loaded types:\n%s" % ex)
            return

        labels, defaults = {}, {}
        for key, (count, src) in info.items():
            if key in existing:
                continue
            if only_address and not count:
                continue
            if count is None:
                note = "could not inspect"
            elif count == 0:
                note = "no SLC Address"
            else:
                note = "%d address params, from %s" % (count, src)
            labels["%s   [%s]" % (key, note)] = key
            defaults[key] = min(count, slc.MAX_ADDRESSES) if count else 1

        if not labels:
            self._alert("No additional Fire Alarm Device types to add.\n\nTry 'All loaded types' to include "
                        "families without detectable SLC Address parameters.")
            return

        picked = forms.SelectFromList.show(sorted(labels.keys()), title="Add types to the table",
                                           button_name="Add Selected", multiselect=True)
        if not picked:
            return
        for label in picked:
            key = labels[label]
            self._add_row(key, slc.new_rule(slc.MODULE, defaults[key]))
        self.status_text.Text = "%d type(s) added (unsaved)" % len(picked)

    def delete_click(self, sender, args):
        self._commit()
        victims = [i for i in list(self.grid.SelectedItems) if hasattr(i, "Row")]
        for item in victims:
            item.Row.Delete()
        self.status_text.Text = "%d row(s) deleted (unsaved)" % len(victims)

    def open_click(self, sender, args):
        path = slc.table_path()
        try:
            if not os.path.isfile(path):
                slc.write_table(path, {})   # create an empty file
            os.startfile(path)
        except Exception as ex:
            self._alert("Could not open the file:\n%s\n\nPath: %s" % (ex, path))

    def load_default_click(self, sender, args):
        """Copy the rules of a default config file into the local table. The default is only read."""
        self._commit()
        local = slc.table_path()

        dialog = OpenFileDialog()
        dialog.Title = "Select the default config file"
        dialog.Filter = "Config files (*.json)|*.json|All files (*.*)|*.*"
        dialog.CheckFileExists = True
        last = slc.last_default_path()
        if last:
            try:
                folder = os.path.dirname(last)
                if folder and os.path.isdir(folder):
                    dialog.InitialDirectory = folder
                dialog.FileName = os.path.basename(last)
            except Exception:
                pass    # a bad remembered path just means no preselection
        if not dialog.ShowDialog(self):
            return
        source = dialog.FileName

        if slc.same_path(source, local):
            self._alert("That file is your local config, the file this window saves to.\n\n"
                        "Choose the default config file instead.")
            return
        try:
            table = slc.read_table(source)      # read only: the default file is never written
        except Exception as ex:
            self._alert("Could not read the default config:\n%s\n\nPath: %s" % (ex, source))
            return
        if not table:
            self._alert("The default config has no Family Type rules:\n%s" % source)
            return

        current = len([r for r in self._live_rows() if cell_text(r["FamilyType"])])
        unsaved = self.dt.GetChanges() is not None
        go_on = forms.alert(
            "Replace the %d type(s) in your local config with the %d type(s) from the default config?\n\n"
            "Default (only read, never changed):\n%s\n\nLocal config (saved now):\n%s%s\n\n"
            "The current local config is kept as a backup next to it."
            % (current, len(table), source, local,
               "\n\nYour unsaved changes in this window will be lost." if unsaved else ""),
            title=TITLE, yes=True, no=True)
        if not go_on:
            return

        try:
            slc.backup_table()
            slc.save_table(table)
        except Exception as ex:
            self._alert("Could not write the local config:\n%s\n\nPath: %s" % (ex, local))
            return
        slc.remember_default_path(source)
        self._fill(table)
        self.status_text.Text = "Loaded %d type(s) from the default config and saved locally" % len(table)

    def save_click(self, sender, args):
        self._commit()
        table, errors, seen = {}, [], set()
        kept = []       # (row, rule) of the rows that were saved
        for idx, row in enumerate(self._live_rows(), start=1):
            key = cell_text(row["FamilyType"])
            kind_text = cell_text(row["DeviceType"])
            count_text = cell_text(row["Addresses"])
            options_text = cell_text(row["Options"])
            round_text = cell_text(row["RoundTo"])

            if not key and not count_text and not options_text and not round_text:
                continue    # blank row (a Device Type alone is just the column default)
            if not key:
                errors.append("Row %d: Family Type is blank." % idx)
                continue
            if key in seen:
                errors.append("Row %d: duplicate Family Type '%s'." % (idx, key))
                continue
            seen.add(key)
            where = "Row %d (%s): " % (idx, key)

            kind = KIND_BY_NAME.get(kind_text)
            if kind is None:
                errors.append(where + "Device Type must be Module or Detector.")
                continue

            count = None    # blank = prompt later
            if count_text:
                if not count_text.isdigit():
                    errors.append(where + "Number of Addresses is not a number.")
                    continue
                count = int(count_text)
                if count < 1 or count > slc.MAX_ADDRESSES:
                    errors.append(where + "Number of Addresses must be 1-%d or blank." % slc.MAX_ADDRESSES)
                    continue

            options, problem = slc.parse_options(options_text)
            if problem:
                errors.append(where + "Address Options: " + problem)
                continue
            if options and count:
                errors.append(where + "set either Number of Addresses or Address Options, not both.")
                continue

            round_to = None
            if round_text:
                if not round_text.isdigit() or not 2 <= int(round_text) <= slc.MAX_NUMBER:
                    errors.append(where + "Round Up To Multiple Of must be a whole number from 2 to %d, "
                                          "or blank." % slc.MAX_NUMBER)
                    continue
                round_to = int(round_text)

            table[key] = slc.new_rule(kind, count, options, round_to)
            kept.append((row, table[key]))

        if errors:
            self._alert("Nothing was saved. Please fix:\n\n" + "\n".join(errors))
            return
        try:
            slc.save_table(table)
        except Exception as ex:
            self._alert("Could not save the lookup table:\n%s\n\nPath: %s" % (ex, slc.table_path()))
            return

        # Show the options the way they were understood (a:6 becomes "a":6).
        for row, rule in kept:
            shown = slc.format_options(rule["options"])
            if cell_text(row["Options"]) != shown:
                row["Options"] = shown
        self.dt.AcceptChanges()
        self.status_text.Text = "Saved %d type(s)" % len(table)

    def close_click(self, sender, args):
        self.Close()

    def window_closing(self, sender, args):
        self._commit()
        if self.dt.GetChanges() is not None:
            discard = forms.alert("You have unsaved changes.\n\nClose without saving?",
                                  title=TITLE, yes=True, no=True)
            if not discard:
                args.Cancel = True


def show_editor(doc):
    """Open the editor. Refuses when the table can't be read, so a broken file is never overwritten."""
    try:
        table = slc.load_table()
    except Exception as ex:
        forms.alert("Could not read the lookup table:\n%s\n\nPath: %s\n\nFix or remove the file, then try again."
                    % (ex, slc.table_path()), title=TITLE)
        return
    ConfigEditor(doc, table).ShowDialog()
