# -*- coding: utf-8 -*-
# riser_layout module - version v23
# Change log (last change first):
#   v23 - SLC Riser v44 / NAC Riser v9 (code check, no change to the drawings): assign_symbols' unused repeat
#         option removed.
#   v22 - SLC Riser v43 / NAC Riser v8: address callouts - a device's info may carry "callout" (the extents of its
#         Address Group callout symbol), drawn where its 45 degree text would go (out["callouts"]) and given the
#         same room; the symbol rules (rule_matches, pick_rule) are removed.
#   v21 - SLC Riser v35 / NAC Riser v1 (cleanup, no change to the drawings): removed the T-tap rows (build_rows, the
#         T-TAP FROM label) and the unused panel_dy / exit_low options; rows no longer carry "source".
#   v20 - Code consolidation step 2 (no change to SLC Riser's results): the tee rule in flat_rows is now
#         tee_order, which conduit_trace also uses, so the addressing tools treat a tee the same way.
#   v19 - SLC Riser v32: a tee'd branch is drawn at the split, out and back (feed and return), then the
#         main run carries on (flat_rows).
"""The parts of the riser tools that don't touch Revit: following the conduit from the panel to find the
order of connection, splitting the result into rows, and working out where everything is drawn.

Elements are plain ids here; the riser engine (lib/riser_tool.py) supplies the connections and does the drawing.

tee_order is the tee rule for both SLC Riser and the conduit tracing of the addressing tools (lib/conduit_trace.py),
so a tee is treated the same way everywhere."""


def assign_symbols(addresses, count):
    """Which addresses go under each symbol drawn for one device: [(symbol index, [addresses])]. Each symbol is
    drawn once, in order, with one address each; the last symbol takes the rest (1 symbol: it gets every address,
    as a first-last range)."""
    count = max(1, int(count))
    addresses = list(addresses)
    out = []
    for i in range(count):
        if i < count - 1:
            out.append((i, addresses[i:i + 1]))
        else:
            out.append((i, addresses[i:]))
    return out


def find_path(root, target, ports, is_node):
    """The passed-through ids joining root to target without going through another device, or []."""
    parent = {root: None}
    queue = [root]
    while queue:
        e = queue.pop(0)
        for group in ports(e):
            for nxt in group:
                if nxt in parent:
                    continue
                parent[nxt] = e
                if nxt == target:
                    path = []
                    while parent[e] is not None:
                        path.append(e)
                        e = parent[e]
                    return path
                if not is_node(nxt):
                    queue.append(nxt)
    return []


def trace(root, ports, is_node, starts=None):
    """Follow the connections outward from root.

    starts: the first device of each run, in the order the runs are wanted. Each run is then followed
    away from root starting at that device, and only those runs are followed. None = every connector
    of root, in connector order.

    ports(id)   -> one list of connected ids per connector of that element
    is_node(id) -> True for an element that is drawn (a device); everything else (conduit, fittings,
                   boxes, devices that aren't on this riser) is passed through

    Returns (children, returns, passed):
      children {id: [next device ids]}   root and every device found, in order of connection
      returns  set of device ids whose onward conduit comes back to root (a Class A return)
      passed   ids that were passed through, in the order they were reached"""
    visited = set([root])
    children = {root: []}
    returns = set()
    passed = []
    # One connector at a time, finishing everything beyond it before the next one, so a loop that comes
    # back to the panel is followed all the way round from its first end.
    if starts:
        for s in starts:
            visited.update(find_path(root, s, ports, is_node))   # the way back to root is not a return
        visited.update(starts)
        children[root] = list(starts)
        stack = []
        for s in reversed(starts):
            children[s] = []
            stack.append((s, iter(ports(s))))
    else:
        stack = [(root, iter(ports(root)))]
    while stack:
        node, groups = stack[-1]
        try:
            group = next(groups)
        except StopIteration:
            stack.pop()
            continue
        found = []
        queue = list(group)
        while queue:
            e = queue.pop(0)
            if e in visited:
                if e == root and node != root:
                    returns.add(node)
                continue
            visited.add(e)
            if is_node(e):
                found.append(e)
            else:
                passed.append(e)
                for g in ports(e):
                    queue.extend(g)
        children[node].extend(found)
        for k in reversed(found):
            children[k] = []
            stack.append((k, iter(ports(k))))
    return children, returns, passed


def subtree_sizes(root, children):
    size = {}
    stack = [(root, False)]
    while stack:
        n, done = stack.pop()
        if done:
            size[n] = 1 + sum(size[k] for k in children.get(n, []))
        else:
            stack.append((n, True))
            for k in children.get(n, []):
                stack.append((k, False))
    return size


def tee_order(sides, size, sort_key):
    """The order to take the sides of a split (a tee) in. Shared by SLC Riser (flat_rows) and the conduit
    tracing used by Address SLC, Address NAC / Voice and Auto-Circuit (conduit_trace.trace_downstream).

    The main run is the side with the most devices beyond the split, and it is taken last. The other sides are
    the tee'd branches, taken first in sort_key order. On a tie for the most devices the side that sorts last
    is the main run, so the lower one is taken first as a branch.
    sides: one id per side; size(side) -> number of devices on that side; sort_key(side) -> sort value."""
    sides = list(sides)
    if len(sides) < 2:
        return sides
    main = max(sides, key=lambda s: (size(s), sort_key(s)))
    return sorted((s for s in sides if s != main), key=sort_key) + [main]


def flat_rows(root, children, sort_key):
    """[{"nodes": [device ids in order]}] - one row per run leaving root, with no T-tap rows.

    A conduit teeing off the main run is treated as a feed and a return pulled through the same conduit:
    at the split the tee'd branch is drawn first, out to its end and back, and then the main run carries on.
    The main run is the side with the most devices beyond the split; the other sides are branches, taken in
    order of their first device (sort_key, e.g. the lowest SLC address). Branches off branches work the same."""
    size = subtree_sizes(root, children)
    rows = []
    for start in children.get(root, []):
        order, seen = [], set()
        stack = [start]
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            order.append(cur)
            kids = [k for k in children.get(cur, []) if k not in seen]
            if not kids:
                continue
            # The tee rule (tee_order): branches first in sort order, the main run (most devices beyond the
            # split; a tie goes to the one that sorts last) last. Stack: last pushed is drawn first.
            for k in reversed(tee_order(kids, lambda k: size.get(k, 1), sort_key)):
                stack.append(k)
        rows.append({"nodes": order})
    return rows


def split_lines(nodes, per, rounding=0):
    """Break a row into lines of per devices. A row (or the part left after earlier lines) only wraps when it
    has more than per + rounding devices. With per 40 and rounding 5: 41 or 45 devices stay on one line,
    46 become 40 + 6, and 85 become 40 + 45."""
    per = max(1, int(per))
    rounding = max(0, int(rounding or 0))
    lines, i = [], 0
    while len(nodes) - i > per + rounding:
        lines.append(nodes[i:i + per])
        i += per
    if i < len(nodes):
        lines.append(nodes[i:])
    return lines


def layout(rows, root, info, returns, cfg):
    """Positions for the whole diagram, in the same length unit as cfg and the extents.

    info[id] = {"mapped": bool, "ext": (left, right, up, down) from the insertion point, "lines": [text],
                "above": text written above the symbol, or "" (optional),
                "callout": (left, right, up, down) of its address callout symbol (optional) - drawn in place of
                the address text, with its insertion point where the text's top corner would go}
    info[root] may also carry "panel": True - the panel is drawn by the caller (out["panel"] = (x, y) of
                its top right corner; its ext is (width, 0, 0, height) from there). It is drawn once and
                every run comes out of its right side, the rows beside it. "exit_dy" is how far below the
                top the first run leaves; a run that ends up below the panel leaves it near its bottom.
                (The riser tools lay out one run at a time, each from its own reference line.)
    A row may carry "label" (its loop or circuit, e.g. "A" or "N1-2"), written above the start of the row.
    cfg      = spacing, per_line, wrap_rounding (extra devices allowed before a line wraps; 0 if not given), pad, text_gap, line_h, char_w, row_gap, above_h (line height of the
               text above a symbol; line_h if not given), label_offset (how far below
               the line a device label's top corner sits; 0 if not given)
    Returns {"symbols": [(x, y, id)], "boxes": [(x, y, left, right, up, down)],
             "lines": [((x1, y1), (x2, y2))], "texts": [(x, y, text, how)], "panel": (x, y) or None,
             "leader_texts": [(x, y, text, end x, end y)], "callouts": [(x, y, id)]}
    "leader_texts" are the loop labels: level text centred on x with its top at y, and a vertical line from
    under it down to (end x, end y) on the riser line. cfg "loop_label_raise" lifts them (0 if not given).

    how: "L" / "C" / "R" = level text with (x, y) at its top left / top centre / top right.
         "A" = the small text above a device symbol, level, with (x, y) at its top centre.
         "D" = a device's label: text at 45 degrees, right justified, hanging down to the left of the
               device. (x, y) is where the text's uppermost corner (its top right corner) goes: on the
               device centreline, label_offset below the riser line.

    The riser line is drawn unbroken through the devices."""
    sp = cfg["spacing"]
    per = max(1, int(cfg["per_line"]))
    pad, text_gap, lh, row_gap = cfg["pad"], cfg["text_gap"], cfg["line_h"], cfg["row_gap"]
    char_w = cfg["char_w"]
    offset = cfg.get("label_offset", 0.0)
    above_h = cfg.get("above_h", lh)

    def above_up(n):
        """How far a symbol and the text above it reach above the riser line."""
        u = info[n]["ext"][2]
        text = info[n].get("above")
        return u + text_gap + (text.count("\n") + 1) * above_h if text else u
    diag = 0.7071067811865476       # sin 45 = cos 45
    out = {"symbols": [], "boxes": [], "lines": [], "texts": [], "panel": None, "leader_texts": [], "callouts": []}
    label_raise = cfg.get("loop_label_raise", 0.0)
    custom_panel = bool(info[root].get("panel"))

    def label_size(n):
        """(length, height) of a device's label before it is turned."""
        lines = info[n]["lines"]
        if not lines:
            return 0.0, 0.0
        return max(len(t) for t in lines) * char_w, len(lines) * lh

    def label_drop(n):
        """How far a device's turned label (or its callout) reaches below the riser line."""
        callout = info[n].get("callout")
        if callout:
            return offset + callout[3]
        length, height = label_size(n)
        return (length + height) * diag + offset if length else 0.0

    def label_reach(n):
        """How far a device's turned label (or its callout) reaches left of the device centreline."""
        callout = info[n].get("callout")
        if callout:
            return callout[0]
        length, height = label_size(n)
        return length * diag if length else 0.0

    def root_depth():
        lines = info[root]["lines"]
        return info[root]["ext"][3] + ((text_gap + len(lines) * lh) if lines else 0.0)

    def place(n, x, y):
        l, r, u, d = info[n]["ext"]
        if n == root and custom_panel:
            out["panel"] = (x, y)
            return
        if info[n]["mapped"]:
            out["symbols"].append((x, y, n))
        else:
            out["boxes"].append((x, y, l, r, u, d))
        above = info[n].get("above")
        if above and n != root:
            out["texts"].append((x, y + above_up(n), above, "A"))
        if n != root and info[n].get("callout"):
            out["callouts"].append((x, y - offset, n))
            return
        if not info[n]["lines"]:
            return
        text = "\n".join(info[n]["lines"])
        if n == root:
            out["texts"].append((x, y - d - text_gap, text, "C"))
        else:
            out["texts"].append((x, y - offset, text, "D"))

    devices = [n for row in rows for n in row["nodes"]]
    reach = max(label_reach(n) for n in devices) if devices else 0.0
    root_r = info[root]["ext"][1]
    back_gap = max(sp * 0.5, reach + pad)   # a wrapped line comes back clear of the first label
    x_first = root_r + max(sp, back_gap + pad)      # first device of every line
    x_back = x_first - back_gap     # where a wrapped line turns at the left
    cursor = None                   # bottom of what has been drawn so far
    panel_bottom = None             # bottom of the panel once it is placed
    panel_top = None                # top of the custom panel once it is placed

    for row in rows:
        nodes = row["nodes"]
        chunks = split_lines(nodes, per, cfg.get("wrap_rounding", 0))

        # Lines run back and forth: the first left to right, the next right to left, and so on. A right to
        # left line starts under the last device of the line above (further right if it has more devices).
        xs_all, prev_len = [], 0
        for ci, chunk in enumerate(chunks):
            if ci % 2 == 0:
                xs_all.append([x_first + k * sp for k in range(len(chunk))])
            else:
                start_col = max(prev_len - 1, len(chunk) - 1)
                xs_all.append([x_first + (start_col - k) * sp for k in range(len(chunk))])
            prev_len = len(chunk)

        def turn_x(ci):
            """x of the vertical line from line ci down to line ci + 1."""
            if ci % 2 == 0:     # turning right, then running back to the left
                a, b = chunks[ci][-1], chunks[ci + 1][0]
                return max(xs_all[ci][-1], xs_all[ci + 1][0]) + max(info[a]["ext"][1], info[b]["ext"][1]) + sp * 0.5
            return x_back       # turning left, clear of the address text, then running right again

        prev_y = None
        for ci, chunk in enumerate(chunks):
            last_chunk = ci == len(chunks) - 1
            forward = ci % 2 == 0
            xs = xs_all[ci]
            up = max(above_up(n) for n in chunk)
            below = max(max(info[n]["ext"][3], label_drop(n)) for n in chunk)
            run_dy = None
            if ci == 0 and custom_panel and panel_top is None:
                run_dy = -abs(info[root].get("exit_dy", 0.0))
            if ci == 0:
                if custom_panel:
                    if panel_top is None:
                        up = max(up, -run_dy - pad)     # the panel's top sits above the first run
                else:
                    up = max(up, info[root]["ext"][2])
                if row.get("label"):
                    up = max(up, lh * 1.4 + label_raise)
                if not custom_panel:
                    below = max(below, root_depth())
            if last_chunk and nodes[-1] in returns:
                up = max(up, lh)
            up += pad
            below += pad

            if cursor is None:
                y = 0.0
            elif ci == 0:
                y = cursor - row_gap - up
            else:
                y = cursor - up

            if ci == 0:
                start = root_r
                if custom_panel and panel_top is None:
                    panel_top = y - run_dy
                    place(root, 0.0, panel_top)
                    panel_bottom = panel_top - info[root]["ext"][3]
                elif panel_bottom is None or not custom_panel:
                    place(root, 0.0, y)
                    panel_bottom = y - info[root]["ext"][3]
                elif y < panel_bottom + pad:
                    # Below the panel: out of its right side near the bottom, then down to this row.
                    exit_y = panel_bottom + min(info[root]["ext"][3], pad)
                    bus_x = root_r + sp * 0.04
                    out["lines"].append(((root_r, exit_y), (bus_x, exit_y)))
                    out["lines"].append(((bus_x, exit_y), (bus_x, y)))
                    start = bus_x
                if row.get("label"):
                    lx = root_r + sp * 0.25
                    out["leader_texts"].append((lx, y + lh * 1.25 + label_raise, row["label"], lx, y))
            else:
                start = turn_x(ci - 1)
                out["lines"].append(((start, prev_y), (start, y)))     # down from the line above

            for n, x in zip(chunk, xs):
                place(n, x, y)
            end = xs[-1]                                # the last device's centre
            if not last_chunk:
                end = turn_x(ci)
            elif nodes[-1] in returns:
                ext = info[chunk[-1]]["ext"]
                if forward:
                    end = xs[-1] + ext[1] + sp * 0.4
                    out["texts"].append((end + sp * 0.05, y + lh * 0.6, "RETURNS TO PANEL", "L"))
                else:
                    end = xs[-1] - ext[0] - sp * 0.4
                    out["texts"].append((end - sp * 0.05, y + lh * 0.6, "RETURNS TO PANEL", "R"))
            out["lines"].append(((min(start, end), y), (max(start, end), y)))   # one unbroken line
            prev_y = y
            cursor = y - below
    return out
