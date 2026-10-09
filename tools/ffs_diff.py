#!/usr/bin/env python3
"""
Enumerate the EFI firmware files in a firmware volume and diff two volumes.

Used to find out what a locally built SM7150 volume contains that the working
surya volume does not, or the other way round.
"""

import struct
import sys
import uuid
from pathlib import Path

FFS_TOLERANCE = 0x10

FILE_TYPES = {
    0x01: "RAW", 0x02: "FREEFORM", 0x03: "SEC_CORE", 0x04: "PEI_CORE",
    0x05: "DXE_CORE", 0x06: "PEIM", 0x07: "DRIVER", 0x08: "COMBO_PEIM_DRV",
    0x09: "APPLICATION", 0x0A: "SMM", 0x0B: "FV_IMAGE", 0x0C: "COMBO_SMM_DXE",
    0x0D: "SMM_CORE", 0xF0: "FFS_PAD",
}

SECTIONS = {
    0x01: "COMPRESSION", 0x02: "GUID_DEFINED", 0x03: "DISPOSABLE",
    0x10: "PE32", 0x11: "PIC", 0x12: "TE", 0x13: "DXE_DEPEX",
    0x14: "VERSION", 0x15: "USER_INTERFACE", 0x16: "COMPATIBILITY16",
    0x17: "FIRMWARE_VOLUME_IMAGE", 0x18: "FREEFORM_SUBTYPE_GUID",
    0x19: "RAW", 0x1B: "PEI_DEPEX", 0x1C: "SMM_DEPEX",
}


def extract_volume(fd: bytes) -> bytes:
    sig = fd.find(b"_FVH")
    if sig < 40:
        raise SystemExit("no firmware volume")
    start = sig - 40
    length = int.from_bytes(fd[start + 32 : start + 40], "little")
    return fd[start : start + length]


def parse(fv: bytes):
    header_len = struct.unpack_from("<H", fv, 48)[0]
    files = {}
    off = header_len
    guard = 0
    while off + 24 <= len(fv) and guard < 20000:
        guard += 1
        # EFI_FFS_FILE_HEADER: Name[16], IntegrityCheck[2], Type[1],
        # Attributes[1], Size[3], State[1]
        name = str(uuid.UUID(bytes_le=fv[off : off + 16])).upper()
        ftype = fv[off + 18]
        attrs = fv[off + 19]
        size = int.from_bytes(fv[off + 20 : off + 23], "little")
        state = fv[off + 23]

        if size < 24 or size == 0xFFFFFF:
            # not aligned to 8, resync to the next 8-byte boundary
            nxt = (off + 8) & ~7
            if nxt <= off:
                break
            off = nxt
            continue

        valid = (state & 0xFC) in (0xFC, 0xF8, 0xE8, 0xF0) or (state & 0x80) == 0
        body = fv[off : off + size]
        sections = []
        if not valid:
            sections = ["(header state 0x%02x - not valid)" % state]
        else:
            # walk sections
            soff = 24
            if attrs & 0x01:  # FFS_ATTRIB_LARGE_FILE
                soff += 8
            while soff + 4 <= len(body):
                s_size = int.from_bytes(body[soff : soff + 3], "little")
                s_type = body[soff + 3]
                if s_size < 4 or soff + s_size > len(body):
                    break
                sections.append(SECTIONS.get(s_type, "0x%02x" % s_type))
                if s_type in (0x17,):  # FIRMWARE_VOLUME_IMAGE
                    sections.append("FV_IMAGE(%d)" % s_size)
                    break
                soff = (soff + s_size + 3) & ~3

        files[name] = (FILE_TYPES.get(ftype, "0x%02x" % ftype), size, tuple(sections), valid)
        off = (off + size + 7) & ~7
    return files


def main():
    a_path, b_path = sys.argv[1], sys.argv[2]
    a = parse(extract_volume(Path(a_path).read_bytes()))
    b = parse(extract_volume(Path(b_path).read_bytes()))
    print("%s : %d files" % (a_path, len(a)))
    print("%s : %d files" % (b_path, len(b)))
    print()

    print("--- only in %s ---" % Path(a_path).name)
    for k in sorted(set(a) - set(b)):
        t, s, sec, v = a[k]
        print("  %s %-16s %7d  %s" % (t, k[:8], s, ",".join(sec)[:40]))
    print()
    print("--- only in %s ---" % Path(b_path).name)
    for k in sorted(set(b) - set(a)):
        t, s, sec, v = b[k]
        print("  %s %-16s %7d  %s" % (t, k[:8], s, ",".join(sec)[:40]))
    print()
    print("--- in both but differing type/size ---")
    n = 0
    for k in sorted(set(a) & set(b)):
        ta, sa, _, va = a[k]
        tb, sb, _, vb = b[k]
        if ta != tb or (va != vb):
            print("  %s: %s/%d vs %s/%d" % (k[:8], ta, sa, tb, sb))
            n += 1
    if not n:
        print("  (none)")


if __name__ == "__main__":
    main()
