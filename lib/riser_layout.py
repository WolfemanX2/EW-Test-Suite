# -*- coding: utf-8 -*-
# riser_layout module - version v9
"""The parts of the riser tools that don't touch Revit: following the conduit from the panel to find the
order of connection, splitting the result into rows, and working out where everything is drawn.

Elements are plain ids here; the SLC Riser script supplies the connections and does the drawing."""


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


def build_rows(root, children):
    """[{"nodes": [device ids in order], "source": None or the device id the row taps off}].
    Every run leaving root is a row. Where the conduit splits at a device, the longer side carries on
    in the same row and each other side becomes its own row, listed right after."""
    size = subtree_sizes(root, children)
    rows = []
    stack = [(k, None) for k in reversed(children.get(root, []))]
    while stack:
        start, source = stack.pop()
        chain, branches = [], []
        cur = start
        while True:
            chain.append(cur)
            kids = children.get(cur, [])
            if not kids:
                break
            main = kids[0]
            for k in kids[1:]:
                if size[k] > size[main]:
                    main = k
            for k in kids:
                if k != main:
                    branches.append((k, cur))
            cur = main
        rows.append({"nodes": chain, "source": source})
        for b in reversed(branches):
            stack.append(b)
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
                "above": text written above the symbol, or "" (optional)}
    A row may carry "label" (its loop, e.g. "L2"), written above the start of the row.
    cfg      = spacing, per_line, wrap_rounding (extra devices allowed before a line wraps; 0 if not given), pad, text_gap, line_h, char_w, row_gap, above_h (line height of the
               text above a symbol; line_h if not given), label_offset (how far below
               the line a device label's top corner sits; 0 if not given)
    Returns {"symbols": [(x, y, id)], "boxes": [(x, y, left, right, up, down)],
             "lines": [((x1, y1), (x2, y2))], "texts": [(x, y, text, how)]}

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
    out = {"symbols": [], "boxes": [], "lines": [], "texts": []}

    def label_size(n):
        """(length, height) of a device's label before it is turned."""
        lines = info[n]["lines"]
        if not lines:
            return 0.0, 0.0
        return max(len(t) for t in lines) * char_w, len(lines) * lh

    def label_drop(n):
        """How far a device's turned label reaches below the riser line."""
        length, height = label_size(n)
        return (length + height) * diag + offset if length else 0.0

    def label_reach(n):
        """How far a device's turned label reaches left of the device centreline."""
        length, height = label_size(n)
        return length * diag if length else 0.0

    def root_depth():
        lines = info[root]["lines"]
        return info[root]["ext"][3] + ((text_gap + len(lines) * lh) if lines else 0.0)

    def place(n, x, y):
        l, r, u, d = info[n]["ext"]
        if info[n]["mapped"]:
            out["symbols"].append((x, y, n))
        else:
            out["boxes"].append((x, y, l, r, u, d))
        above = info[n].get("above")
        if above and n != root:
            out["texts"].append((x, y + above_up(n), above, "A"))
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
    x_back = x_first - back_gap     # where a wrapped line comes back to, and where a tap row starts
    cursor = None                   # bottom of what has been drawn so far

    for row in rows:
        nodes = row["nodes"]
        chunks = split_lines(nodes, per, cfg.get("wrap_rounding", 0))
        turn = None     # (x, y) where the previous line of this row ended, ready to turn down
        for ci, chunk in enumerate(chunks):
            last_chunk = ci == len(chunks) - 1
            up = max(above_up(n) for n in chunk)
            below = max(max(info[n]["ext"][3], label_drop(n)) for n in chunk)
            if ci == 0:
                if row["source"] is None:
                    up = max(up, info[root]["ext"][2])
                    if row.get("label"):
                        up = max(up, lh * 1.4)
                    below = max(below, root_depth())
                else:
                    up = max(up, lh * 1.2)
                    below = max(below, lh * 1.2)
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
                if row["source"] is None:
                    place(root, 0.0, y)
                    start = root_r
                    if row.get("label"):
                        out["texts"].append((root_r + sp * 0.08, y + lh * 1.25, row["label"], "L"))
                else:
                    src_lines = info[row["source"]]["lines"]
                    label = "T-TAP FROM\n%s" % (src_lines[0].rstrip("-") if src_lines else "DEVICE")
                    if row.get("label"):
                        label = "%s %s" % (row["label"], label)
                    out["texts"].append((x_back - sp * 0.05, y + lh, label, "R"))
                    start = x_back
            else:
                tx, ty = turn
                out["lines"].append(((tx, ty), (tx, cursor)))
                out["lines"].append(((tx, cursor), (x_back, cursor)))
                out["lines"].append(((x_back, cursor), (x_back, y)))
                start = x_back

            x = x_first
            for k, n in enumerate(chunk):
                x = x_first + k * sp
                place(n, x, y)
            end = x                                     # the last device's centre
            if not last_chunk:
                end = x + info[chunk[-1]]["ext"][1] + sp * 0.5
                turn = (end, y)
            elif nodes[-1] in returns:
                end = x + info[chunk[-1]]["ext"][1] + sp * 0.4
                out["texts"].append((end + sp * 0.05, y + lh * 0.6, "RETURNS TO PANEL", "L"))
            out["lines"].append(((start, y), (end, y)))   # one unbroken line through the devices
            cursor = y - below
    return out
