# -*- coding: utf-8 -*-
# auto_circuit module - version v4
# Change log (last change first):
#   v4 - Code audit (Auto Circuit - SLC v4 / NAC v5 / Voice v5): its message boxes are ec.alert, pyRevit's box without
#        the warning icon and its sound.
#   v3 - Auto Circuit - SLC v3 / NAC v4 / Voice v4: the next device picked sets the session's prefer, so at a
#        split the run goes down its side first.
#   v2 - Auto Circuit - SLC / NAC / Voice v2: Automatically asks for the next device on the circuit (or its tag)
#        instead of the conduit, and finds the conduit leaving the first device towards it.
#   v1 - Auto Circuit - SLC / NAC / Voice v1: the three tools' start (Readdress, Route Conduit, Reroute and
#        Readdress) and Readdress, Manually or Automatically, with Family Defaults Config.
"""Auto Circuit - SLC, Auto Circuit - NAC and Auto Circuit - Voice: one tool per kind of circuit, each running
main(kind) with kind "SLC", "N" (NAC) or "V" (Voice). Shift+Click opens Family Defaults Config.

What to do:
  Readdress              Manually (in order of selection) or Automatically (in order of conduit connection)
  Route Conduit          New Conduit Route / Add to Existing Circuit             (next update)
  Reroute and Readdress  New Conduit Route / Add to Existing Circuit             (next update)

Readdress runs the Address SLC session (slc_session) or the Address NAC / Voice session (nac_voice_addressing)
with Family Defaults Config (lib/circuit_rules.py) instead of their old tables, and with Manual or Automatic chosen
at the start instead of after the first device."""
from Autodesk.Revit.UI.Selection import ObjectType
from Autodesk.Revit.Exceptions import OperationCanceledException
from Autodesk.Revit.DB.Electrical import Conduit
from pyrevit import revit, forms, script

import circuit_config as cc
import circuit_rules as rules
import circuit_config_editor     # Family Defaults Config (Shift+Click)
import slc_session
import slc_addressing as slc
import nac_voice_addressing as nva
import ew_common as ec        # shared helpers (lib/ew_common.py)
import conduit_trace as ct    # following conduit from a device (lib/conduit_trace.py)

TITLES = {"SLC": "Auto Circuit - SLC", "N": "Auto Circuit - NAC", "V": "Auto Circuit - Voice"}
CONFIG_NAME = "Family Defaults Config"

READDRESS = "Readdress"
ROUTE = "Route Conduit"
REROUTE = "Reroute and Readdress"
MANUAL = "Readdress Manually (in order of selection)"
AUTOMATIC = "Readdress Automatically (in order of conduit connection)"
NEW_ROUTE = "New Conduit Route"
ADD_TO_CIRCUIT = "Add to Existing Circuit"

NEXT_DEVICE_EXPLAINED = "Please select Next device to be added to Circuit"
NEXT_DEVICE_PROMPT = "Please select Next device to be added to Circuit (or its tag) - Esc to pick devices manually"


def main(kind, shift_clicked=False):
    """Runs Auto Circuit - SLC ("SLC"), - NAC ("N") or - Voice ("V")."""
    doc = revit.doc
    if shift_clicked:
        circuit_config_editor.show_editor(doc)
        return
    title = TITLES[kind]
    try:
        cfg = cc.load()
    except Exception as ex:
        ec.alert("Could not read %s:\n%s\n\nPath: %s\n\nFix or remove the file, then try again."
                    % (CONFIG_NAME, ex, cc.config_path()), title=title)
        return
    what = forms.CommandSwitchWindow.show([READDRESS, ROUTE, REROUTE], message="%s: what do you want to do?" % title)
    if not what:
        return
    if what == READDRESS:
        how = forms.CommandSwitchWindow.show([MANUAL, AUTOMATIC], message="%s: how do you want to readdress?" % title)
        if how:
            readdress(kind, cfg, how == AUTOMATIC)
        return
    how = forms.CommandSwitchWindow.show([NEW_ROUTE, ADD_TO_CIRCUIT], message="%s - %s:" % (title, what))
    if how:
        ec.alert("%s - %s is coming in the next update of the dev branch." % (what, how), title=title)


# ---------- Readdress ----------
def readdress(kind, cfg, automatic):
    title = TITLES[kind]
    if kind == "SLC":
        slc_session.doc, slc_session.uidoc, slc_session.output = revit.doc, revit.uidoc, script.get_output()
        slc_session.TITLE = title
        SlcReaddress(cfg, automatic, title).run()
    else:
        nva.doc, nva.uidoc, nva.output = revit.doc, revit.uidoc, script.get_output()
        nva.TITLE = title
        NacReaddress(kind, cfg, automatic, title).run()


class _Preset(object):
    """Manual or Automatic chosen at the start: Manual never offers Automatic; Automatic follows the conduit from
    each device addressed by hand (the first one, or one after a run). Esc on the conduit pick switches to Manual."""
    def _preset(self, automatic):
        self.automatic, self.explained = automatic, False
        self.manual = not automatic

    def _pick_conduit(self, module):
        """Asks for the next device on the circuit (or its tag; a conduit is also accepted) and returns the conduit
        leaving the anchor device towards it, or None (Esc: Manual from now on)."""
        if not self.explained:
            ec.alert(NEXT_DEVICE_EXPLAINED, title=module.TITLE)
            self.explained = True
        while True:
            try:
                ref = module.uidoc.Selection.PickObject(ObjectType.Element, ec.DeviceOrTagFilter(conduit=True),
                                                        NEXT_DEVICE_PROMPT)
            except OperationCanceledException:
                self.manual = True
                return None
            picked = module.doc.GetElement(ref.ElementId)
            if isinstance(picked, Conduit):
                self.prefer = ()
                return picked
            device = ec.resolve_device(picked)
            conduit = None if device is None else _conduit_towards(module.doc, self.anchor, device)
            if conduit is not None:
                # At a split the run goes down the next device's side first (not the tee rule's order).
                self.prefer = (ec.eid_int(device.Id),)
                return conduit
            ec.alert("That device is not connected by conduit downstream of element %d.\n\nSelect the next device "
                     "on the circuit, or press Esc to pick devices manually." % ec.eid_int(self.anchor.Id),
                     title=module.TITLE)


def _conduit_towards(doc, anchor, device):
    """The conduit leaving the anchor device whose downstream run reaches the device, or None."""
    anchor_id, target = ec.eid_int(anchor.Id), ec.eid_int(device.Id)
    if anchor_id == target:
        return None
    candidates, seen = [], set()
    for group in ct.connected_elements(anchor):
        for el in group:
            # Conduit joined to the device, or joined through a fitting / box on its connector.
            near = [el] if isinstance(el, Conduit) else [n for g in ct.connected_elements(el) for n in g
                                                        if isinstance(n, Conduit)]
            for c in near:
                i = ec.eid_int(c.Id)
                if i not in seen:
                    seen.add(i)
                    candidates.append(c)
    for c in candidates:
        found, problem = ct.follow(doc, anchor, c, ec.is_device)
        if not problem and any(ec.eid_int(f.Id) == target for f in found):
            return c
    return None


class SlcReaddress(_Preset, slc_session.Session):
    CONFIG_NAME = CONFIG_NAME           # named in the count / kind questions (addressing_ui.SlcCountRules)
    SKIP_TEXT = "Skip Device"

    def __init__(self, cfg, automatic, title):
        slc_session.Session.__init__(self)
        self.cfg = cfg
        self.COUNT_TITLE = title
        self._preset(automatic)

    def load_table(self):
        self.table = rules.SlcRules(self.cfg)
        return True

    def settings_line(self):
        return "%s: `%s`" % (CONFIG_NAME, cc.config_path())

    def ask_mode(self):
        if self.manual or self.anchor is None:
            return True
        return self.start_automatic()

    def start_automatic(self):
        conduit = self._pick_conduit(slc_session)
        return True if conduit is None else self.run_automatic(conduit)

    def address_device(self, device):
        """NAC / Voice devices are not SLC devices: skipped."""
        key = slc.family_key(slc_session.doc, device)
        label = rules.device_type(self.cfg, key)
        if label in cc.NAC_TYPES:
            self.problems.append("Element %d (%s): a %s device, not addressed by %s."
                                 % (ec.eid_int(device.Id), key, label, slc_session.TITLE))
            forms.toast("%s device - not an SLC device. Skipped." % label, title=slc_session.TITLE)
            return True
        return slc_session.Session.address_device(self, device)


class NacReaddress(_Preset, nva.Session):
    CONFIG_HINT = "define it in %s, or Shift+Click the tool button, to keep it" % CONFIG_NAME

    def __init__(self, kind, cfg, automatic, title):
        nva.Session.__init__(self, kind)
        self.cfg = cfg
        self._preset(automatic)

    def load_table(self):
        return rules.NacLabels(self.cfg)

    def settings_line(self):
        return "%s: `%s`" % (CONFIG_NAME, cc.config_path())

    def ask_mode(self):
        if self.manual or self.anchor is None:
            return
        self.start_automatic()

    def start_automatic(self):
        conduit = self._pick_conduit(nva)
        if conduit is not None:
            self.run_automatic(conduit)

    def device_label(self, el, key, show=False):
        """Module and Detector types are SLC devices: never asked about here, not addressed."""
        if rules.device_type(self.cfg, key) in cc.SLC_TYPES:
            return None
        return nva.Session.device_label(self, el, key, show)

    def address_device(self, el):
        key = nva.nv.family_key(nva.doc, el)
        label = rules.device_type(self.cfg, key)
        if label in cc.SLC_TYPES:
            self.not_this_run.append((ec.eid_int(el.Id), key, label))
            forms.toast("%s device - an SLC device, not addressed by %s. Skipped." % (label, nva.TITLE),
                        title=nva.TITLE)
            return None
        return nva.Session.address_device(self, el)
