# -*- coding: utf-8 -*-
# nac_voice_eol module - version v1
# Change log (last change first):
#   v1 - Address NAC v6 / Address Voice v6 / Auto-Circuit v12: the end of each NAC / Voice circuit, one copy for the
#        three tools (moved from nac_voice_addressing and Auto-Circuit's copy). The EOL device is marked as before;
#        the totals now go on every device (Circuit Current and Circuit Voltage for NAC, Circuit Wattage for Voice)
#        instead of an estimate in the EOL device's Comments.
"""The end of each NAC / Voice circuit, worked out again whenever a run adds devices to it or moves devices off it.
Used by Address NAC, Address Voice and Auto-Circuit: update(doc, touched, transaction name).

Every device on the circuit, by its device number (N1-2.3 is number 3):
- NAC EOL / Voice EOL (Yes / No): Yes on the last device (the highest number), No on the rest.
- NAC circuits:   Circuit Current = the current (Current) of the devices numbered up to and including this one.
                  Circuit Voltage = the voltage left at the device, point to point (see nac_voice_types).
- Voice circuits: Circuit Wattage = the wattage (Wattage) of the devices numbered up to and including this one.
Comments are left alone, apart from clearing an EOL estimate an older Address NAC wrote there."""
from Autodesk.Revit.DB import Transaction, BuiltInParameter, BuiltInCategory
from Autodesk.Revit.DB.Electrical import Conduit

import nac_voice_types as nv
import conduit_trace as ct      # the shared conduit tracing (lib/conduit_trace.py)
import ew_common as ec        # shared helpers (lib/ew_common.py)

eid_int = ec.eid_int


def update(doc, touched, transaction_name):
    """Marks the EOL and fills the totals on every circuit in touched {(kind, power supply, circuit)}, in one
    transaction. Returns (summary lines, problems). If Revit doesn't keep the change, nothing is written and the
    summary lines are dropped (the reason is in problems)."""
    if not touched:
        return [], []
    circuits = circuits_of(doc, touched)
    changes, lines, problems = [], [], []
    for key in sorted(touched):
        members = circuits.get(key, [])
        if not members:
            continue
        kind, source, circuit = key
        mark_eol(kind, source, circuit, members, changes, lines, problems)
        if kind == "N":
            nac_totals(doc, source, circuit, members, changes, lines, problems)
        else:
            voice_totals(doc, source, circuit, members, changes, lines, problems)
    if not changes:
        return lines, problems

    def work():
        for p, value in changes:
            p.Set(value)

    error = ec.commit(Transaction(doc, transaction_name), work)
    if error:
        problems.append("EOL parameters and circuit totals were not set: %s" % error)
        lines = []
    return lines, problems


def circuits_of(doc, touched):
    """{(kind, power supply, circuit): [(device number, device)]} for the circuits in touched, one pass."""
    kinds = set(k for k, _s, _c in touched)
    circuits = {}
    for el in nv.all_devices(doc):
        for kind in nv.KINDS:
            if kind not in kinds:
                continue
            parsed = nv.address_on(el, kind)
            if parsed and (kind, parsed[0], parsed[1]) in touched:
                circuits.setdefault((kind, parsed[0], parsed[1]), []).append((parsed[2], el))
    return circuits


# ---------- EOL ----------
def mark_eol(kind, source, circuit, members, changes, lines, problems):
    """EOL = Yes on the last device of the circuit, No on every other device on it."""
    last = max(n for n, _el in members)
    name = nv.EOL_PARAM_NAMES[kind]
    ends, missing = [], 0
    for n, el in members:
        p = nv.get_yes_no(el, name)
        if p is None:
            missing += 1
            if n == last:
                problems.append("%s: the last device (element %d) has no writable %s parameter."
                                % (nv.fmt_address(kind, source, circuit, n), eid_int(el.Id), name))
            continue
        value = 1 if n == last else 0
        if n == last:
            ends.append(eid_int(el.Id))
        if p.AsInteger() != value:
            changes.append((p, value))
    circuit_text = nv.fmt_circuit(kind, source, circuit)
    if len(ends) > 1:
        problems.append("%s: %d devices share the last address %s; all are set to %s = Yes."
                        % (circuit_text, len(ends), nv.fmt_address(kind, source, circuit, last), name))
    if ends:
        lines.append("%s: %s = Yes on %s (element %s)"
                     % (circuit_text, name, nv.fmt_address(kind, source, circuit, last),
                        ", ".join(str(i) for i in ends)))
    if missing:
        problems.append("%s: %d device(s) have no writable %s parameter." % (circuit_text, missing, name))


# ---------- Totals ----------
def running_totals(members, value_of):
    """[(device number, device, total)] in device-number order. total = value_of summed over every device numbered
    up to and including this one (devices sharing a number share the total)."""
    ordered = sorted(members, key=lambda m: m[0])
    by_number, total = {}, 0.0
    for n, el in ordered:
        total += value_of(el)
        by_number[n] = total
    return [(n, el, by_number[n]) for n, el in ordered]


def _set_text(el, name, text, changes):
    """Queues the text for the device's text parameter. Returns 1 if the device has no writable one, else 0."""
    p = nv.get_param(el, name)
    if p is None or p.IsReadOnly:
        return 1
    if (p.AsString() or "") != text:
        changes.append((p, text))
    return 0


def _clear_old_comment(el, changes):
    """Clears an EOL estimate an older Address NAC wrote to Comments. Returns 1 if there was one."""
    try:
        p = el.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
    except Exception:
        return 0
    if p is None or p.IsReadOnly or not nv.is_eol_comment(p.AsString() or ""):
        return 0
    changes.append((p, ""))
    return 1


def _missing_problems(circuit_text, missing, problems):
    for name, count in missing:
        if count:
            problems.append("%s: %d device(s) have no writable %s parameter." % (circuit_text, count, name))


def nac_totals(doc, source, circuit, members, changes, lines, problems):
    """Circuit Current and Circuit Voltage on every device of a NAC circuit."""
    amps, no_current = {}, 0
    for _n, el in members:
        a = nv.get_current(doc, el)
        if a is None:
            no_current += 1
            a = 0.0
        amps[eid_int(el.Id)] = a
    running = running_totals(members, lambda el: amps[eid_int(el.Id)])
    total = running[-1][2]
    volts, notes = voltages(doc, source, circuit, members, amps, total)
    if no_current:
        notes.insert(0, "%d device(s) have no Current value (counted as 0 A)" % no_current)

    missing_current = missing_volts = cleared = 0
    for _n, el, run in running:
        v = volts.get(eid_int(el.Id))
        missing_current += _set_text(el, nv.CIRCUIT_CURRENT_PARAM, nv.fmt_amps(run), changes)
        missing_volts += _set_text(el, nv.CIRCUIT_VOLTAGE_PARAM, nv.fmt_volts(v) if v is not None else "", changes)
        cleared += _clear_old_comment(el, changes)
    if cleared:
        notes.append("old EOL estimate cleared from Comments on %d device(s)" % cleared)

    circuit_text = nv.fmt_circuit("N", source, circuit)
    last = running[-1][0]
    eol_volts = [volts[eid_int(el.Id)] for n, el, _r in running if n == last and eid_int(el.Id) in volts]
    summary = "%s: %s, %s on %d device(s) - total %s" % (circuit_text, nv.CIRCUIT_CURRENT_PARAM,
                                                          nv.CIRCUIT_VOLTAGE_PARAM, len(running), nv.fmt_amps(total))
    if eol_volts:
        summary += ", %s at the EOL" % nv.fmt_volts(min(eol_volts))
    lines.append(summary + (("  (%s)" % "; ".join(notes)) if notes else ""))

    low = [(volts[eid_int(el.Id)], n, el) for n, el, _r in running
           if eid_int(el.Id) in volts and volts[eid_int(el.Id)] < nv.MIN_DEVICE_VOLTS]
    if low:
        v, n, el = min(low, key=lambda x: x[0])
        problems.append("%s: estimated voltage at %s (element %d) is %s, below %g V%s."
                        % (circuit_text, nv.fmt_address("N", source, circuit, n), eid_int(el.Id), nv.fmt_volts(v),
                           nv.MIN_DEVICE_VOLTS, (" (%d device(s) below)" % len(low)) if len(low) > 1 else ""))
    _missing_problems(circuit_text, [(nv.CIRCUIT_CURRENT_PARAM, missing_current),
                                     (nv.CIRCUIT_VOLTAGE_PARAM, missing_volts)], problems)


def voice_totals(doc, source, circuit, members, changes, lines, problems):
    """Circuit Wattage on every device of a Voice circuit."""
    watts, no_watts = {}, 0
    for _n, el in members:
        w = nv.get_wattage(doc, el)
        if w is None:
            no_watts += 1
            w = 0.0
        watts[eid_int(el.Id)] = w
    running = running_totals(members, lambda el: watts[eid_int(el.Id)])
    missing = 0
    for _n, el, run in running:
        missing += _set_text(el, nv.CIRCUIT_WATTAGE_PARAM, nv.fmt_watts(run), changes)
    circuit_text = nv.fmt_circuit("V", source, circuit)
    notes = ["%d device(s) have no Wattage value (counted as 0 W)" % no_watts] if no_watts else []
    lines.append("%s: %s on %d device(s) - total %s%s"
                 % (circuit_text, nv.CIRCUIT_WATTAGE_PARAM, len(running), nv.fmt_watts(running[-1][2]),
                    ("  (%s)" % "; ".join(notes)) if notes else ""))
    _missing_problems(circuit_text, [(nv.CIRCUIT_WATTAGE_PARAM, missing)], problems)


# ---------- NAC voltage, point to point ----------
def voltages(doc, source, circuit, members, amps, total):
    """({element id: volts left at the device}, [notes]) for a NAC circuit. Devices not joined to the first device
    by conduit marked with the circuit (e.g. N12) get no voltage."""
    notes = []
    pname = nv.CONDUIT_PARAM_NAMES.get("N")
    token = nv.fmt_conduit("N", source, circuit)

    def tagged(el):
        p = nv.get_param(el, pname) if pname else None
        return p is not None and token in nv.conduit_tokens(p.AsString())

    # The circuit: conduit marked with this circuit, through fittings, boxes and devices.
    root = min(members, key=lambda m: m[0])[1]
    parent, els, order = ct.walk(root, lambda el: tagged(el) if isinstance(el, Conduit) else True)
    unreached = len([i for i in amps if i not in parent])
    if unreached:
        notes.append("%d device(s) aren't joined to the first device by conduit marked %s in %s, so their %s is "
                     "left blank and their current is counted for the home run only (address the circuit with "
                     "Automatic)" % (unreached, token, pname, nv.CIRCUIT_VOLTAGE_PARAM))

    # Each conduit carries the current of every device past it, out and back.
    ohms_per_ft = 2 * nv.WIRE_OHMS_PER_1000FT / 1000.0
    beyond = dict.fromkeys(order, 0.0)
    for i in reversed(order):
        beyond[i] += amps.get(i, 0.0)
        if parent[i] is not None:
            beyond[parent[i]] += beyond[i]
    drop = {}
    for i in order:     # breadth first: a parent always comes before the elements it leads to
        up = parent[i]
        drop[i] = drop[up] if up is not None else 0.0
        if isinstance(els[i], Conduit):
            drop[i] += beyond[i] * ct.conduit_length(els[i]) * ohms_per_ft

    # Home run: conduit of the same type from the first device back to the power supply, carrying it all.
    types = set(ct.eid_int(els[i].GetTypeId()) for i in order if isinstance(els[i], Conduit))
    home = home_run_length(root, types, tagged)
    home_drop = 0.0
    if home is None:
        notes.append("home run to the power supply not found (not connected?), so it is not included")
    else:
        home_drop = total * home * ohms_per_ft
    volts = dict((i, nv.SOURCE_VOLTS - home_drop - drop[i]) for i in amps if i in parent)
    return volts, notes


def home_run_length(root, types, tagged):
    """Feet of conduit from the first device back to the nearest power supply, or None if not connected."""
    def is_supply(el):
        try:
            cid = eid_int(el.Category.Id)
        except Exception:
            return False
        if cid == int(BuiltInCategory.OST_ElectricalEquipment):
            return True
        # a fire alarm family that isn't a NAC device (no NAC Address): booster / power supply
        return nv.is_device(el) and nv.get_param(el, nv.PARAM_NAMES["N"]["address"]) is None

    def enter(el):
        if isinstance(el, Conduit):
            return ct.eid_int(el.GetTypeId()) in types and not tagged(el)
        if nv.is_device(el):
            return is_supply(el)    # never pass through another device
        return True                 # fittings, boxes, panels

    parent, els, order = ct.walk(root, enter)
    for i in order[1:]:
        if is_supply(els[i]):
            feet = 0.0
            while i is not None:
                if isinstance(els[i], Conduit):
                    feet += ct.conduit_length(els[i])
                i = parent[i]
            return feet
    return None
