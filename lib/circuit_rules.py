# -*- coding: utf-8 -*-
# circuit_rules module - version v1
# Change log (last change first):
#   v1 - Auto Circuit - SLC / NAC / Voice v1: Family Defaults Config read the way the addressing sessions read
#        their tables (SlcRules, NacLabels), and the Device Type of a type.
"""Family Defaults Config (lib/circuit_config.py) as the tables the addressing sessions use, so the Auto Circuit
tools can run them with these settings:

SlcRules    {"Family : Type": Address SLC rule}: Module / Detector with the count or subgroups of its Address Group
            and its Round To; Head End. Other types (NAC / Voice, or not set) have no rule.
NacLabels   {"Family : Type": "NAC Only" | "Voice Only" | "NAC and Voice" | "Head End"}; other types have none.
Only .get(key) and `in` are offered: a type's value comes from the type, else its family."""
import circuit_config as cc
import slc_addressing as slc

_SLC_KINDS = {cc.MODULE: slc.MODULE, cc.DETECTOR: slc.DETECTOR, cc.HEAD_END: slc.HEAD_END}


def device_type(cfg, key):
    """The Device Type set for a 'Family : Type' (or its family), or None."""
    return cc.setting(cfg, key, "device_type")


class _View(object):
    def __init__(self, cfg):
        self.cfg, self._cache = cfg, {}

    def get(self, key, default=None):
        if key not in self._cache:
            self._cache[key] = self._value(key)
        value = self._cache[key]
        return default if value is None else value

    def __contains__(self, key):
        return self.get(key) is not None

    def _value(self, key):
        raise NotImplementedError


class SlcRules(_View):
    """Address SLC rules from Family Defaults Config. An Address Group with one subgroup is a fixed count; with
    several, its subgroups are the choices offered when the device is addressed. No group (or a group that isn't
    there any more): asked how many."""
    def _value(self, key):
        kind = _SLC_KINDS.get(device_type(self.cfg, key))
        if kind is None:
            return None
        if kind == slc.HEAD_END:
            return slc.new_rule(slc.HEAD_END)
        count, options = None, []
        group = cc.setting(self.cfg, key, "address_group")
        subs = cc.subgroups(self.cfg, group) if group else None
        if subs and len(subs) == 1:
            count = subs[0][1]
        elif subs:
            options = [(name or str(n), n) for name, n in subs]
        return slc.new_rule(kind, count, options, cc.setting(self.cfg, key, "round_to"))


class NacLabels(_View):
    """NAC / Voice device types from Family Defaults Config (the same names Address NAC / Voice uses)."""
    def _value(self, key):
        label = device_type(self.cfg, key)
        return label if label in cc.NAC_TYPES or label == cc.HEAD_END else None
