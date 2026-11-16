# -*- coding: utf-8 -*-
# riser_layout module - version v2
"""The parts of the riser tools that don't touch Revit: following the conduit from the panel to find the
order of connection, splitting the result into rows, and working out where everything is drawn.

Elements are plain ids here; the SLC Riser script supplies the connections and does the drawing."""


def trace(root, ports, is_node):
    """Follow the connections outward from root.

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


def layout(rows, root, info, returns, cfg):
    """Positions for the whole diagram, in the same length unit as cfg and the extents.

    info[id] = {"mapped": bool, "ext": (left, right, up, down) from the insertion point, "lines": [text]}
    A row may carry "label" (its loop, e.g. "L2"), written above the start of the row.
    cfg      = spacing, per_line, pad, text_gap, line_h, row_gap
    Returns {"symbols": [(x, y, id)], "boxes": [(x, y, left, right, up, down)],
             "lines": [((x1, y1), (x2, y2))], "texts": [(x, y, text, "L" | "C" | "R")]}"""
    sp = cfg["spacing"]
    per = max(1, int(cfg["per_line"]))
    pad, text_gap, lh, row_gap = cfg["pad"], cfg["text_gap"], cfg["line_h"], cfg["row_gap"]
    out = {"symbols": [], "boxes": [], "lines": [], "texts": []}

    def text_depth(n):
        lines = info[n]["lines"]
        return info[n]["ext"][3] + ((text_gap + len(lines) * lh) if lines else 0.0)

    def place(n, x, y):
        l, r, u, d = info[n]["ext"]
        if info[n]["mapped"]:
            out["symbols"].append((x, y, n))
        else:
            out["boxes"].append((x, y, l, r, u, d))
        if info[n]["lines"]:
            out["texts"].append((x, y - d - text_gap, "\n".join(info[n]["lines"]), "C"))

    root_r = info[root]["ext"][1]
    x_first = root_r + sp           # first device of every line
    x_back = x_first - sp * 0.5     # where a wrapped line comes back to, and where a tap row starts
    cursor = None                   # bottom of what has been drawn so far

    for row in rows:
        nodes = row["nodes"]
        chunks = [nodes[i:i + per] for i in range(0, len(nodes), per)]
        wrap = None     # (x of the last device's right edge, its y, x of the turn)
        for ci, chunk in enumerate(chunks):
            last_chunk = ci == len(chunks) - 1
            up = max(info[n]["ext"][2] for n in chunk)
            below = max(text_depth(n) for n in chunk)
            if ci == 0:
                if row["source"] is None:
                    up = max(up, info[root]["ext"][2])
                    if row.get("label"):
                        up = max(up, lh * 1.4)
                    below = max(below, text_depth(root))
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
                    edge = root_r
                    if row.get("label"):
                        out["texts"].append((root_r + sp * 0.08, y + lh * 1.25, row["label"], "L"))
                else:
                    src_lines = info[row["source"]]["lines"]
                    label = "T-TAP FROM\n%s" % (src_lines[0] if src_lines else "DEVICE")
                    if row.get("label"):
                        label = "%s %s" % (row["label"], label)
                    out["texts"].append((x_back - sp * 0.05, y + lh, label, "R"))
                    edge = x_back
            else:
                ex, ey, tx = wrap
                out["lines"].append(((ex, ey), (tx, ey)))
                out["lines"].append(((tx, ey), (tx, cursor)))
                out["lines"].append(((tx, cursor), (x_back, cursor)))
                out["lines"].append(((x_back, cursor), (x_back, y)))
                edge = x_back

            for k, n in enumerate(chunk):
                x = x_first + k * sp
                l, r = info[n]["ext"][0], info[n]["ext"][1]
                out["lines"].append(((edge, y), (x - l, y)))
                place(n, x, y)
                edge = x + r

            if not last_chunk:
                wrap = (edge, y, edge + sp * 0.5)
            elif nodes[-1] in returns:
                out["lines"].append(((edge, y), (edge + sp * 0.4, y)))
                out["texts"].append((edge + sp * 0.45, y + lh * 0.6, "RETURNS TO PANEL", "L"))
            cursor = y - below
    return out
