# -*- coding: utf-8 -*-
# nac_voice_config_editor module - version v1
# Change log (last change first):
#   v1 - Address NAC / Voice - Config v5 / Address NAC v6 / Address Voice v6: the Address NAC / Voice - Config window,
#        moved here from the Config button (unchanged) so Shift+Click on Address NAC / Voice opens it too, as Shift+Click
#        on Address SLC opens Address SLC - Config.
"""The Address NAC / Voice - Config window: editable table of the Family : Type rules used by Address NAC, Address
Voice and Auto-Circuit. Opened by the Address NAC / Voice - Config button and by Shift+Click on Address NAC or
Address Voice: show_editor(doc)."""
import clr
clr.AddReference("System.Data")
from System import String, DBNull
from System.Data import DataTable, DataRowState
from Autodesk.Revit.DB import StorageType, FilteredElementCollector
from pyrevit import forms

import nac_voice_types as nv
import ew_common as ec        # shared helpers (lib/ew_common.py)

doc = None      # set by show_editor
TITLE = "Address NAC / Voice - Config"
ADDRESS_NAMES = dict((nv.PARAM_NAMES[k]["address"].lower(), k) for k in nv.KINDS)


def cell_text(v):
    if v is None or isinstance(v, DBNull):
        return ""
    return str(v).strip()


# ---------- Loaded family scan ----------
def inspect_family(fam):
    """Kinds ("N", "V") whose Address parameter is an instance text parameter inside a family file, found by
    opening it in the background (nothing is modified or reloaded). None = can't inspect."""
    fdoc = None
    try:
        if fam.IsInPlace or not fam.IsEditable:
            return None
        fdoc = doc.EditFamily(fam)
    except Exception:
        return None
    try:
        kinds = set()
        for fp in fdoc.FamilyManager.Parameters:
            try:
                kind = ADDRESS_NAMES.get(fp.Definition.Name.strip().lower())
                if kind and fp.IsInstance and fp.StorageType == StorageType.String:
                    kinds.add(kind)
            except Exception:
                pass
        return kinds
    except Exception:
        return None
    finally:
        try:
            fdoc.Close(False)
        except Exception:
            pass


def loaded_types_info(family_cache):
    """{"Family : Type": (set of kinds or None, source)} for ALL loaded device types.
    source = 'placed device' or 'family file'. family_cache {family id: kinds or None} avoids re-inspecting."""
    placed = {}
    seen_types = set()
    symbols = []
    for cat in nv.DEVICE_CATEGORIES:
        for el in FilteredElementCollector(doc).OfCategory(cat).WhereElementIsNotElementType().ToElements():
            tid = el.GetTypeId()
            tid_int = nv.eid_int(tid)
            if tid_int in seen_types:
                continue
            seen_types.add(tid_int)
            fam = getattr(doc.GetElement(tid), "Family", None)
            if fam is None:
                continue
            placed.setdefault(nv.eid_int(fam.Id), set()).update(nv.kinds_on_element(el))
        symbols.extend(FilteredElementCollector(doc).OfCategory(cat).WhereElementIsElementType().ToElements())

    fams = {}   # family id -> [Family, [type keys]]
    for s in symbols:
        fam = getattr(s, "Family", None)
        if fam is None:
            continue
        try:
            key = ec.type_key(s)
        except Exception:
            continue
        fams.setdefault(nv.eid_int(fam.Id), [fam, []])[1].append(key)

    todo = [fid for fid in fams if fid not in placed and fid not in family_cache]
    if todo:
        with forms.ProgressBar(title="Inspecting unplaced families ({value} of {max_value})",
                               cancellable=True) as pb:
            for i, fid in enumerate(todo, start=1):
                if pb.cancelled:
                    break
                family_cache[fid] = inspect_family(fams[fid][0])
                pb.update_progress(i, len(todo))

    result = {}
    for fid, (fam, keys) in fams.items():
        if fid in placed:
            kinds, src = placed[fid], "placed device"
        else:
            kinds, src = family_cache.get(fid), "family file"
        for k in keys:
            result[k] = (kinds, src)
    return result


# ---------- Editor window ----------
EDITOR_XAML = """
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Address NAC / Voice - Config"
        Width="760" Height="520" MinWidth="620" MinHeight="380"
        WindowStartupLocation="CenterScreen"
        Closing="window_closing">
    <Grid Margin="12">
        <Grid.RowDefinitions>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="*"/>
            <RowDefinition Height="Auto"/>
        </Grid.RowDefinitions>

        <TextBlock Grid.Row="0" TextWrapping="Wrap" Margin="0,0,0,8"
                   Text="Define which addresses each Family Type gets. NAC Only fills NAC Address and NAC Circuit, Voice Only fills Voice Address and Voice Circuit, NAC and Voice fills all four. Head End (the panel, power supplies) is never addressed. Type in the blank bottom row to add an entry (Family : Type, exactly as Revit shows it)."/>

        <DataGrid x:Name="grid" Grid.Row="1"
                  AutoGenerateColumns="False"
                  CanUserAddRows="True" CanUserDeleteRows="True"
                  SelectionMode="Extended" SelectionUnit="FullRow"
                  GridLinesVisibility="All" HeadersVisibility="Column">
            <DataGrid.Columns>
                <DataGridTextColumn Header="Family Type"
                                    Binding="{Binding FamilyType}" Width="*"/>
                <DataGridComboBoxColumn Header="Device Type"
                                        SelectedItemBinding="{Binding DeviceType}"
                                        Width="150"/>
            </DataGrid.Columns>
        </DataGrid>

        <DockPanel Grid.Row="2" Margin="0,10,0,0" LastChildFill="False">
            <Button Content="Add Types From Project..." Width="170"
                    Margin="0,0,8,0" Click="add_click" DockPanel.Dock="Left"/>
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
        self._family_cache = {}     # family id -> kinds (or None)

        # Data model: DataTable binds cleanly to a WPF DataGrid.
        self.dt = DataTable("NacVoiceTypes")
        self.dt.Columns.Add("FamilyType", clr.GetClrType(String))
        kind_col = self.dt.Columns.Add("DeviceType", clr.GetClrType(String))
        kind_col.DefaultValue = nv.NAC_ONLY
        self.grid.Columns[1].ItemsSource = list(nv.TYPE_LABELS)

        for key in sorted(table.keys()):
            self._add_row(key, table[key])
        self.dt.AcceptChanges()
        self.grid.ItemsSource = self.dt.DefaultView
        self.status_text.Text = "%d type(s) loaded" % len(table)

    def _add_row(self, key, label):
        row = self.dt.NewRow()
        row["FamilyType"] = key
        row["DeviceType"] = label
        self.dt.Rows.Add(row)

    def _live_rows(self):
        for row in self.dt.Rows:
            if row.RowState != DataRowState.Deleted:
                yield row

    # ---- Buttons ----
    def add_click(self, sender, args):
        self.grid.CommitEdit()
        existing = set(cell_text(r["FamilyType"]) for r in self._live_rows())

        scope = forms.CommandSwitchWindow.show(
            ["Only types with NAC / Voice parameters", "All loaded types"],
            message="Which loaded Fire Alarm Device types do you want to list?")
        if not scope:
            return
        only_params = scope.startswith("Only")

        labels, defaults = {}, {}
        for key, (kinds, src) in loaded_types_info(self._family_cache).items():
            if key in existing:
                continue
            if only_params and not kinds:
                continue
            suggested = nv.label_for_kinds(kinds)
            if kinds is None:
                tag = "could not inspect"
            elif not kinds:
                tag = "no NAC / Voice parameters"
            else:
                tag = "%s, from %s" % (suggested, src)
            labels["%s [%s]" % (key, tag)] = key
            defaults[key] = suggested or nv.NAC_ONLY

        if not labels:
            forms.alert("No additional Fire Alarm Device types to add.\n\nTry 'All loaded types' to include "
                        "families without detectable NAC / Voice parameters.", title=TITLE)
            return

        picked = forms.SelectFromList.show(sorted(labels.keys()), title="Add types to the table",
                                           button_name="Add Selected", multiselect=True)
        if not picked:
            return
        for label in picked:
            key = labels[label]
            self._add_row(key, defaults[key])
        self.status_text.Text = "%d type(s) added (unsaved) - check the suggested Device Type" % len(picked)

    def delete_click(self, sender, args):
        self.grid.CommitEdit()
        victims = [i for i in list(self.grid.SelectedItems) if hasattr(i, "Row")]
        for item in victims:
            item.Row.Delete()
        self.status_text.Text = "%d row(s) deleted (unsaved)" % len(victims)

    def save_click(self, sender, args):
        self.grid.CommitEdit()
        table, errors, seen = {}, [], set()
        for idx, row in enumerate(self._live_rows(), start=1):
            key = cell_text(row["FamilyType"])
            label = cell_text(row["DeviceType"])
            if not key and not label:
                continue    # fully blank row
            if not key:
                errors.append("Row %d: Family Type is blank." % idx)
                continue
            if key in seen:
                errors.append("Row %d: duplicate Family Type '%s'." % (idx, key))
                continue
            seen.add(key)
            if label not in nv.TYPE_KINDS:
                errors.append("Row %d (%s): Device Type must be one of: %s."
                              % (idx, key, ", ".join(nv.TYPE_LABELS)))
                continue
            table[key] = label

        if errors:
            forms.alert("Nothing was saved. Please fix:\n\n" + "\n".join(errors), title=TITLE)
            return
        try:
            nv.save_table(table)
        except Exception as ex:
            forms.alert("Could not save the lookup table:\n%s\n\nPath: %s" % (ex, nv.table_path()), title=TITLE)
            return
        self.dt.AcceptChanges()
        self.status_text.Text = "Saved %d type(s)" % len(table)

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


def show_editor(document):
    """Open the editor. Refuses when the table can't be read, so a broken file is never overwritten."""
    global doc
    doc = document
    try:
        table = nv.load_table()
    except Exception as ex:
        forms.alert("Could not read the lookup table:\n%s\n\nPath: %s" % (ex, nv.table_path()), title=TITLE)
        return
    TableEditor(table).ShowDialog()
