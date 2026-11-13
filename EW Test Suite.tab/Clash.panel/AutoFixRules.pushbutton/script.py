# -*- coding: utf-8 -*-
# Auto Fix Rules script - version v4
__title__ = "Auto Fix\nRules"
__doc__ = "Set the rules Link Clash's Auto Fix follows: distances, which kinds of fix are allowed, and their order."

from pyrevit import forms

import clash_rules

XAML = """
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Auto Fix Rules" Width="520" SizeToContent="Height" ResizeMode="NoResize"
        WindowStartupLocation="CenterScreen">
    <StackPanel Margin="12">
        <TextBlock Text="General" FontWeight="Bold" />
        <CheckBox x:Name="ask_before" Content="Ask before applying each fix (starting setting)" Margin="0,6,0,0" />
        <DockPanel Margin="0,6,0,0">
            <TextBox x:Name="clearance" DockPanel.Dock="Right" Width="70" />
            <TextBlock Text="Clearance to keep from linked elements (inches)" VerticalAlignment="Center" />
        </DockPanel>

        <TextBlock Text="1. Move the conduit sideways" FontWeight="Bold" Margin="0,14,0,0" />
        <CheckBox x:Name="allow_shift" Content="Allow sideways moves" Margin="0,6,0,0" />
        <DockPanel Margin="0,6,0,0">
            <TextBox x:Name="max_shift" DockPanel.Dock="Right" Width="70" />
            <TextBlock Text="Maximum sideways move (inches)" VerticalAlignment="Center" />
        </DockPanel>
        <DockPanel Margin="0,6,0,0">
            <TextBox x:Name="shift_step" DockPanel.Dock="Right" Width="70" />
            <TextBlock Text="Step between positions tried (inches)" VerticalAlignment="Center" />
        </DockPanel>

        <TextBlock Text="2. Jogs (saddles) around the clashing element" FontWeight="Bold" Margin="0,14,0,0" />
        <CheckBox x:Name="allow_h_jog" Content="Allow horizontal jogs (90 degree bends)" Margin="0,6,0,0" />
        <CheckBox x:Name="allow_v_jog" Content="Allow vertical jogs (angled bends)" Margin="0,6,0,0" />
        <DockPanel Margin="0,6,0,0">
            <StackPanel DockPanel.Dock="Right" Orientation="Horizontal">
                <ComboBox x:Name="v_jog_min_angle" Width="70" />
                <TextBlock Text=" to " VerticalAlignment="Center" />
                <ComboBox x:Name="v_jog_max_angle" Width="70" />
            </StackPanel>
            <TextBlock Text="Vertical jog angles, smallest tried first (degrees)" VerticalAlignment="Center"
                       TextWrapping="Wrap" />
        </DockPanel>
        <DockPanel Margin="0,6,0,0">
            <TextBox x:Name="max_saddle_length" DockPanel.Dock="Right" Width="70" />
            <TextBlock Text="Longest vertical jog before a steeper angle is used (inches)"
                       VerticalAlignment="Center" TextWrapping="Wrap" />
        </DockPanel>
        <DockPanel Margin="0,6,0,0">
            <TextBox x:Name="jog_lead" DockPanel.Dock="Right" Width="70" />
            <TextBlock Text="Straight run between the obstacle and the jog (inches)" VerticalAlignment="Center" />
        </DockPanel>
        <DockPanel Margin="0,6,0,0">
            <TextBox x:Name="jog_min_leg" DockPanel.Dock="Right" Width="70" />
            <TextBlock Text="Shortest piece a jog may create (inches)" VerticalAlignment="Center" />
        </DockPanel>

        <TextBlock Text="3. Raise or lower the whole conduit" FontWeight="Bold" Margin="0,14,0,0" />
        <DockPanel Margin="0,6,0,0">
            <ComboBox x:Name="elevation_mode" DockPanel.Dock="Right" Width="170" />
            <TextBlock Text="Conduit with one clash: change its elevation" VerticalAlignment="Center" />
        </DockPanel>
        <CheckBox x:Name="majority_elevation" Margin="0,6,0,0">
            <TextBlock TextWrapping="Wrap"
                       Text="Conduit with several clashes: first try one elevation change that clears most of them, then jog around the rest" />
        </CheckBox>
        <DockPanel Margin="0,6,0,0">
            <TextBox x:Name="max_elev_change" DockPanel.Dock="Right" Width="70" />
            <TextBlock Text="Maximum elevation change (inches)" VerticalAlignment="Center" />
        </DockPanel>

        <DockPanel Margin="0,6,0,0">
            <ComboBox x:Name="device_mode" DockPanel.Dock="Right" Width="220" />
            <TextBlock Text="Device connected to the conduit" VerticalAlignment="Center" />
        </DockPanel>

        <TextBlock x:Name="status_text" Foreground="Firebrick" TextWrapping="Wrap" Margin="0,12,0,0" />
        <StackPanel Orientation="Horizontal" HorizontalAlignment="Right" Margin="0,8,0,0">
            <Button x:Name="defaults_btn" Content="Reset to defaults" Padding="10,2" Margin="0,0,20,0" />
            <Button x:Name="save_btn" Content="Save" Width="80" Margin="0,0,6,0" />
            <Button x:Name="cancel_btn" Content="Cancel" Width="80" />
        </StackPanel>
    </StackPanel>
</Window>
"""

LABELS = {
    "clearance": "Clearance",
    "max_shift": "Maximum sideways move",
    "shift_step": "Step between positions",
    "jog_lead": "Straight run before the jog",
    "jog_min_leg": "Shortest jog piece",
    "max_elev_change": "Maximum elevation change",
    "max_saddle_length": "Longest vertical jog",
}


def fmt(feet):
    """Feet -> inches text without trailing zeros."""
    return "{:.3f}".format(feet * 12.0).rstrip("0").rstrip(".")


class RulesWindow(forms.WPFWindow):
    def __init__(self, rules):
        forms.WPFWindow.__init__(self, XAML, literal_string=True)
        for m in clash_rules.ELEV_MODES:
            self.elevation_mode.Items.Add(m)
        for m in clash_rules.DEVICE_MODES:
            self.device_mode.Items.Add(m)
        for k in clash_rules.ANGLE_KEYS:
            for a in clash_rules.ANGLES:
                getattr(self, k).Items.Add(a)
        self.fill(rules)
        self.defaults_btn.Click += lambda s, e: self.fill(clash_rules.DEFAULTS)
        self.save_btn.Click += self.on_save
        self.cancel_btn.Click += lambda s, e: self.Close()

    def fill(self, rules):
        for k in clash_rules.BOOL_KEYS:
            getattr(self, k).IsChecked = bool(rules[k])
        for k in clash_rules.LENGTH_KEYS:
            getattr(self, k).Text = fmt(rules[k])
        self.elevation_mode.SelectedItem = rules["elevation_mode"]
        self.device_mode.SelectedItem = rules["device_mode"]
        for k in clash_rules.ANGLE_KEYS:
            getattr(self, k).SelectedIndex = clash_rules.ANGLES.index(rules[k])
        self.status_text.Text = ""

    def on_save(self, sender, args):
        rules = {}
        for k in clash_rules.BOOL_KEYS:
            rules[k] = bool(getattr(self, k).IsChecked)
        for k in clash_rules.LENGTH_KEYS:
            try:
                v = float((getattr(self, k).Text or "").strip())
            except Exception:
                v = None
            if v is None or v <= 0:
                self.status_text.Text = "{} must be a number of inches greater than 0.".format(LABELS[k])
                return
            rules[k] = v / 12.0
        rules["elevation_mode"] = self.elevation_mode.SelectedItem or clash_rules.ELEV_NEVER
        rules["device_mode"] = self.device_mode.SelectedItem or clash_rules.DEVICE_ASK
        for k in clash_rules.ANGLE_KEYS:
            rules[k] = clash_rules.ANGLES[max(0, getattr(self, k).SelectedIndex)]
        if rules["v_jog_min_angle"] > rules["v_jog_max_angle"]:
            self.status_text.Text = "The lowest jog angle can't be larger than the highest."
            return
        if rules["shift_step"] > rules["max_shift"]:
            self.status_text.Text = "The step between positions can't be larger than the maximum sideways move."
            return
        try:
            clash_rules.save_rules(rules)
        except Exception as ex:
            self.status_text.Text = "Could not save the rules: {}".format(ex)
            return
        self.Close()


RulesWindow(clash_rules.load_rules()).ShowDialog()
