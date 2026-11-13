# -*- coding: utf-8 -*-
# Routing Preferences script - version v1
__title__ = "Routing\nPreferences"
__doc__ = ("Pull in all Fire Alarm Device families in the project and set each family's mounting (Wall/Ceiling) "
           "and default conduit type for runs leaving it.")

from pyrevit import revit, forms
from Autodesk.Revit.DB import (
    FilteredElementCollector, Family, FamilyInstance, BuiltInCategory, ElementId
)
from System.Windows.Controls import Grid, ColumnDefinition, TextBlock, ComboBox
from System.Windows import GridLength, GridUnitType, Thickness, Visibility, VerticalAlignment

import mounting_rules

doc = revit.doc

XAML = """
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Routing Preferences" Width="880" Height="660"
        WindowStartupLocation="CenterScreen">
    <DockPanel Margin="10">
        <StackPanel DockPanel.Dock="Top" Margin="0,0,0,8">
            <TextBlock Text="Search families:" />
            <TextBox x:Name="search_box" Margin="0,2,0,6" />
            <StackPanel Orientation="Horizontal" Margin="0,0,0,6">
                <Button x:Name="all_wall_btn" Content="Set shown to Wall" Padding="8,2" Margin="0,0,6,0" />
                <Button x:Name="all_ceiling_btn" Content="Set shown to Ceiling" Padding="8,2" Margin="0,0,6,0" />
                <Button x:Name="all_clear_btn" Content="Clear shown mounting" Padding="8,2" />
            </StackPanel>
            <StackPanel Orientation="Horizontal" Margin="0,0,0,8">
                <TextBlock Text="Conduit type for shown:" VerticalAlignment="Center" Margin="0,0,6,0" />
                <ComboBox x:Name="bulk_type_combo" Width="300" Margin="0,0,6,0" />
                <Button x:Name="bulk_type_btn" Content="Apply to shown" Padding="8,2" />
            </StackPanel>
            <Grid>
                <Grid.ColumnDefinitions>
                    <ColumnDefinition Width="*" />
                    <ColumnDefinition Width="60" />
                    <ColumnDefinition Width="120" />
                    <ColumnDefinition Width="300" />
                </Grid.ColumnDefinitions>
                <TextBlock Grid.Column="0" Text="Family" FontWeight="Bold" />
                <TextBlock Grid.Column="1" Text="Placed" FontWeight="Bold" />
                <TextBlock Grid.Column="2" Text="Mounting" FontWeight="Bold" />
                <TextBlock Grid.Column="3" Text="Conduit type (runs leaving this family)" FontWeight="Bold" />
            </Grid>
        </StackPanel>
        <StackPanel DockPanel.Dock="Bottom" Orientation="Horizontal" HorizontalAlignment="Right" Margin="0,8,0,0">
            <TextBlock x:Name="status_text" VerticalAlignment="Center" Margin="0,0,12,0" />
            <Button x:Name="save_btn" Content="Save" Width="80" Margin="0,0,6,0" />
            <Button x:Name="cancel_btn" Content="Cancel" Width="80" />
        </StackPanel>
        <ScrollViewer VerticalScrollBarVisibility="Auto">
            <StackPanel x:Name="rows_panel" />
        </ScrollViewer>
    </DockPanel>
</Window>
"""

UNASSIGNED = "Unassigned"
MOUNT_CHOICES = [UNASSIGNED, mounting_rules.WALL, mounting_rules.CEILING]
TYPE_DEFAULT = "(default)"


def collect_families():
    """Returns {family_name: placed_count} for all non-in-place Fire Alarm Device families."""
    cat_id = ElementId(BuiltInCategory.OST_FireAlarmDevices)
    result = {}
    for f in FilteredElementCollector(doc).OfClass(Family):
        try:
            if f.IsInPlace:
                continue
            fc = f.FamilyCategory
            if fc is not None and fc.Id == cat_id:
                result[f.Name] = 0
        except Exception:
            pass
    for inst in (FilteredElementCollector(doc)
                 .OfCategory(BuiltInCategory.OST_FireAlarmDevices)
                 .OfClass(FamilyInstance)):
        try:
            n = inst.Symbol.Family.Name
            if n in result:
                result[n] += 1
        except Exception:
            pass
    return result


class RoutingPreferencesWindow(forms.WPFWindow):
    def __init__(self, families, prefs, type_labels):
        forms.WPFWindow.__init__(self, XAML, literal_string=True)
        self.prefs = prefs
        self.type_labels = type_labels
        self.entries = []   # (name, grid, mount_combo, type_combo)

        self.bulk_type_combo.Items.Add(TYPE_DEFAULT)
        for lab in type_labels:
            self.bulk_type_combo.Items.Add(lab)
        self.bulk_type_combo.SelectedIndex = 0

        for name in sorted(families.keys(), key=lambda s: s.lower()):
            self._add_row(name, families[name], prefs.get(name, {}))

        self.search_box.TextChanged += self.on_search
        self.all_wall_btn.Click += lambda s, e: self._set_shown_mount(mounting_rules.WALL)
        self.all_ceiling_btn.Click += lambda s, e: self._set_shown_mount(mounting_rules.CEILING)
        self.all_clear_btn.Click += lambda s, e: self._set_shown_mount(UNASSIGNED)
        self.bulk_type_btn.Click += self.on_bulk_type
        self.save_btn.Click += self.on_save
        self.cancel_btn.Click += lambda s, e: self.Close()
        self.status_text.Text = "{} families".format(len(self.entries))

    def _add_row(self, name, count, entry):
        g = Grid()
        g.Margin = Thickness(0, 2, 0, 2)
        for width in (GridLength(1, GridUnitType.Star), GridLength(60),
                      GridLength(120), GridLength(300)):
            cd = ColumnDefinition()
            cd.Width = width
            g.ColumnDefinitions.Add(cd)

        t1 = TextBlock()
        t1.Text = name
        t1.VerticalAlignment = VerticalAlignment.Center
        Grid.SetColumn(t1, 0)
        g.Children.Add(t1)

        t2 = TextBlock()
        t2.Text = str(count)
        t2.VerticalAlignment = VerticalAlignment.Center
        Grid.SetColumn(t2, 1)
        g.Children.Add(t2)

        mcb = ComboBox()
        for c in MOUNT_CHOICES:
            mcb.Items.Add(c)
        cur_m = entry.get(mounting_rules.KEY_MOUNT)
        mcb.SelectedItem = cur_m if cur_m in MOUNT_CHOICES else UNASSIGNED
        Grid.SetColumn(mcb, 2)
        g.Children.Add(mcb)

        tcb = ComboBox()
        tcb.Items.Add(TYPE_DEFAULT)
        for lab in self.type_labels:
            tcb.Items.Add(lab)
        cur_t = entry.get(mounting_rules.KEY_TYPE)
        if cur_t and cur_t not in self.type_labels:
            tcb.Items.Add(cur_t)   # keep a saved type that isn't in this project
        tcb.SelectedItem = cur_t if cur_t else TYPE_DEFAULT
        Grid.SetColumn(tcb, 3)
        g.Children.Add(tcb)

        self.rows_panel.Children.Add(g)
        self.entries.append((name, g, mcb, tcb))

    def on_search(self, sender, args):
        q = (self.search_box.Text or "").strip().lower()
        for name, g, mcb, tcb in self.entries:
            g.Visibility = Visibility.Visible if (not q or q in name.lower()) else Visibility.Collapsed

    def _set_shown_mount(self, value):
        for name, g, mcb, tcb in self.entries:
            if g.Visibility == Visibility.Visible:
                mcb.SelectedItem = value

    def on_bulk_type(self, sender, args):
        value = self.bulk_type_combo.SelectedItem
        if value is None:
            return
        for name, g, mcb, tcb in self.entries:
            if g.Visibility == Visibility.Visible:
                tcb.SelectedItem = value

    def on_save(self, sender, args):
        new_prefs = dict(self.prefs)   # keep prefs for families not loaded in this project
        for name, g, mcb, tcb in self.entries:
            entry = {}
            m = mcb.SelectedItem
            if m in (mounting_rules.WALL, mounting_rules.CEILING):
                entry[mounting_rules.KEY_MOUNT] = m
            t = tcb.SelectedItem
            if t and t != TYPE_DEFAULT:
                entry[mounting_rules.KEY_TYPE] = t
            if entry:
                new_prefs[name] = entry
            else:
                new_prefs.pop(name, None)
        try:
            mounting_rules.save_rules(new_prefs)
        except Exception as ex:
            forms.alert("Could not save routing preferences:\n{}".format(ex))
            return
        self.Close()


def main():
    families = collect_families()
    if not families:
        forms.alert("No Fire Alarm Device families found in this project.")
        return
    type_labels = mounting_rules.list_conduit_type_labels(doc)
    RoutingPreferencesWindow(families, mounting_rules.load_rules(), type_labels).ShowDialog()


main()
