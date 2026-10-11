#!/usr/bin/env python3
"""Walk a flattened device tree and report what is in it.

Used to settle questions about the courbet stock tree: which SoC it claims,
whether /memory is empty, and whether any touch controller is described.

Usage:
    fdt.py <dtb> [--grep substr]
    fdt.py <dtb> --node <path>
"""

import struct
import sys


def cstr(buf, off):
    end = buf.find(b"\0", off)
    if end < 0:
        return ""
    return buf[off:end].decode("utf-8", "replace")


def walk(dtb):
    """Return (nodes, props). props are (path, name, length, value bytes)."""
    off_struct, off_strings = struct.unpack_from(">II", dtb, 8)
    strings = dtb[off_strings:]
    nodes, props = [], []

    def node(off, path):
        while True:
            tok = struct.unpack_from(">I", dtb, off)[0]
            off += 4
            if tok == 1:                                   # FDT_BEGIN_NODE
                name = cstr(dtb, off)
                off = (off + len(name.encode()) + 1 + 3) & ~3
                # The child path is derived from this frame's path. Mutating
                # `path` here would make every later sibling a child of the
                # previous sibling, which is how a flat list of nodes turns
                # into a nonsense deep path.
                child = path + "/" + name
                nodes.append(child)
                off = node(off, child)
                continue
            if tok == 2:                                   # FDT_END_NODE
                return off
            if tok == 3:                                   # FDT_PROP
                plen, noff = struct.unpack_from(">II", dtb, off)
                off += 8
                pname = cstr(strings, noff)
                props.append((path, pname, plen, dtb[off:off + plen]))
                off = (off + plen + 3) & ~3
                continue
            if tok == 4:                                   # FDT_NOP
                continue
            if tok == 9:                                   # FDT_END
                return off
            raise ValueError("bad token %d at 0x%x" % (tok, off - 4))

    node(off_struct, "")
    return nodes, props


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dtb = open(args[0], "rb").read()
    nodes, props = walk(dtb)

    if "--node" in sys.argv:
        want = sys.argv[sys.argv.index("--node") + 1]
        for p, name, plen, val in props:
            if p == want:
                print("%-24s %6d  %s" % (name, plen, fmt(val)))
        return

    needle = None
    if "--grep" in sys.argv:
        needle = sys.argv[sys.argv.index("--grep") + 1].lower()

    print("nodes %d  properties %d" % (len(nodes), len(props)))
    for p, name, plen, val in props:
        line = "%s:%s = %s" % (p, name, fmt(val))
        if needle and needle not in line.lower():
            continue
        print(line)


def fmt(val):
    if len(val) and all(b == 0 or 32 <= b < 127 for b in val) and b"\0" in val:
        return '"%s"' % val.rstrip(b"\0").decode("utf-8", "replace")
    if len(val) and val[-1] == 0:
        return fmt(val[:-1])
    if len(val) % 4 == 0 and len(val) <= 64:
        cells = struct.unpack(">%dI" % (len(val) // 4), val)
        return "<" + " ".join("0x%x" % c for c in cells) + ">"
    if len(val) <= 64:
        return " ".join("%02x" % b for b in val)
    return "%d bytes" % len(val)


if __name__ == "__main__":
    main()