#!/usr/bin/env python3
"""
Repack an Android boot image (v0-v3) replacing the kernel with a UEFI payload.

Why this works on courbet (Mi 11 Lite 4G, Snapdragon 732G / SM7325):
the vendor bootloader hands the "kernel" slot to the UEFI image loader.
A PE32+ EFI application placed there is started as a UEFI application,
so a full EDK2 firmware (ACPI + GOP + BDS + boot manager) takes over
the machine and can boot Windows ARM64.

Usage:
  repack.py inspect  boot.img
  repack.py extract  boot.img kernel.bin
  repack.py inject   boot.img payload.efi out.img
  repack.py verify   out.img payload.efi
"""

import argparse
import hashlib
import struct
import sys

BOOT_MAGIC = b"ANDROID!"
FDT_MAGIC = b"\xd0\x0d\xfe\xed"
BOOT_HEADER_V2_MAGIC = 0x2FFE6506
BOOT_HEADER_SIZE_V1 = 1648

# offsets inside the v0/v1 header
OFF_MAGIC = 0
OFF_KERNEL_SIZE = 8
OFF_KERNEL_ADDR = 12
OFF_RAMDISK_SIZE = 16
OFF_RAMDISK_ADDR = 20
OFF_SECOND_SIZE = 24
OFF_SECOND_ADDR = 28
OFF_TAGS_ADDR = 32
OFF_PAGE_SIZE = 36
OFF_HEADER_VERSION = 40
OFF_OS_VERSION = 44
OFF_NAME = 48
OFF_CMDLINE = 64
OFF_ID = 576
OFF_EXTRA_CMDLINE = 584
OFF_V2_MAGIC = 1636
OFF_HEADER_SIZE = 1648

# Xiaomi/SM7150 convention for header_version 2: the v2 header has no DTB size
# field, so these devices store it in the slots standard mkbootimg would leave
# unused, and physically place the FDT right after the ramdisk. Verified against
# a working courbet boot.img: @1644 = 1660 (header size), @1648 = 398043 (DTB
# size, matching totalsize of the FDT that follows the ramdisk).
OFF_XIAOMI_HEADER_SIZE = 1644
OFF_XIAOMI_DTB_SIZE = 1648

PE_MAGIC = b"PE\x00\x00"
MZ_MAGIC = b"MZ"


def u32(b, o):
    return struct.unpack_from("<I", b, o)[0]


def align(x, p):
    return (x + p - 1) // p * p


class BootImage:
    def __init__(self, data: bytes):
        self.d = bytearray(data)
        if self.d[:8] != BOOT_MAGIC:
            raise ValueError("not an ANDROID! boot image")
        self.parse()

    def parse(self):
        d = self.d
        self.page_size = u32(d, OFF_PAGE_SIZE) or 2048
        self.header_version = u32(d, OFF_HEADER_VERSION)
        self.kernel_addr = u32(d, OFF_KERNEL_ADDR)
        self.ramdisk_addr = u32(d, OFF_RAMDISK_ADDR)
        self.second_addr = u32(d, OFF_SECOND_ADDR)
        self.tags_addr = u32(d, OFF_TAGS_ADDR)
        self.os_version = u32(d, OFF_OS_VERSION)
        self.cmdline = d[OFF_CMDLINE : OFF_CMDLINE + 512].split(b"\x00")[0].decode("utf-8", "replace")
        self.extra_cmdline = (
            d[BOOT_HEADER_SIZE_V1 - 1024 : BOOT_HEADER_SIZE_V1].split(b"\x00")[0].decode("utf-8", "replace")
            if self.header_version >= 1
            else ""
        )
        # Some vendor tools (observed on courbet boot.img) stamp header_version=2
        # while emitting a plain v0/v1 header: no V2 magic at 1636 and garbage in
        # the header_size slot. Trust header_size only when the v2 magic is real.
        self.has_v2_magic = u32(d, OFF_V2_MAGIC) == BOOT_HEADER_V2_MAGIC
        hdr = u32(d, OFF_HEADER_SIZE) if (self.header_version >= 2 and self.has_v2_magic) else BOOT_HEADER_SIZE_V1
        self.header_size = hdr if BOOT_HEADER_SIZE_V1 <= hdr <= 32768 else BOOT_HEADER_SIZE_V1

        self.vendor_ramdisk_size = 0
        self.dtb_size = 0
        self.vendor_tbl_off = 0
        self.xiaomi_dtb = False
        self.xiaomi_header_size = 0
        if self.header_version >= 3:
            self.vendor_tbl_off = self.header_version
            self.vendor_ramdisk_size = u32(d, self.vendor_tbl_off)
            self.dtb_size = u32(d, self.vendor_tbl_off + 4)
        # header_version 2 is handled after the payload offsets are known.

        # split into header pages + payloads
        self.header_pages = align(self.header_size, self.page_size) if self.header_version >= 2 else self.page_size
        off = self.header_pages

        self.kernel_size = u32(d, OFF_KERNEL_SIZE)
        self.kernel = bytes(d[off : off + self.kernel_size])
        off += align(self.kernel_size, self.page_size)

        self.ramdisk_size = u32(d, OFF_RAMDISK_SIZE)
        self.ramdisk = bytes(d[off : off + self.ramdisk_size]) if self.ramdisk_size else b""
        off += align(self.ramdisk_size, self.page_size)

        # Probe the Xiaomi/SM7150 layout instead of trusting the field: only
        # accept it when an FDT of exactly that declared length sits right
        # after the ramdisk. Independent of header_version - the stock courbet
        # image is version 2 while the images this project produces are
        # version 0, and both carry the tree the same way.
        # This runs here because it needs the payload offsets computed above.
        candidate = u32(d, OFF_XIAOMI_DTB_SIZE)
        if 0 < candidate < len(d) - off and d[off : off + 4] == FDT_MAGIC:
            if int.from_bytes(d[off + 4 : off + 8], "big") == candidate:
                self.xiaomi_dtb = True
                self.dtb_size = candidate
                self.xiaomi_header_size = u32(d, OFF_XIAOMI_HEADER_SIZE)

        self.vendor_ramdisk = b""
        if self.vendor_ramdisk_size:
            self.vendor_ramdisk = bytes(d[off : off + self.vendor_ramdisk_size])
            off += align(self.vendor_ramdisk_size, self.page_size)

        self.second_size = u32(d, OFF_SECOND_SIZE)
        self.second = bytes(d[off : off + self.second_size]) if self.second_size else b""
        off += align(self.second_size, self.page_size)

        self.dtb = b""
        if self.dtb_size:
            self.dtb = bytes(d[off : off + self.dtb_size])
            off += align(self.dtb_size, self.page_size)

        self.used = off
        self.slack = len(self.d) - self.used

    # -- reporting -------------------------------------------------------
    def payloads(self):
        yield "kernel", self.kernel, OFF_KERNEL_SIZE
        if self.ramdisk_size:
            yield "ramdisk", self.ramdisk, OFF_RAMDISK_SIZE
        if self.vendor_ramdisk_size:
            yield "vendor_ramdisk", self.vendor_ramdisk, None
        if self.second_size:
            yield "second", self.second, OFF_SECOND_SIZE
        if self.dtb_size:
            yield "dtb", self.dtb, None

    def describe(self):
        L = []
        a = L.append
        a(f"header_version : {self.header_version}")
        a(f"page_size      : {self.page_size}")
        a(f"header_size    : {self.header_size}")
        a(f"cmdline        : {self.cmdline}")
        if self.extra_cmdline:
            a(f"extra_cmdline  : {self.extra_cmdline}")
        a("")
        for name, data, _ in self.payloads():
            kind = classify(data)
            a(f"{name:<15} {len(data):>10} bytes  {kind}")
        a("")
        a(f"used           : {self.used} ({self.used/1048576:.2f} MiB)")
        a(f"slack          : {self.slack} ({self.slack/1048576:.2f} MiB)")
        return "\n".join(L)

    # -- rebuild ---------------------------------------------------------
    def build(self, total_size: int | None = None, recompute_id: bool = True) -> bytes:
        page = self.page_size
        head = bytearray(self.d[: align(self.header_size, page)])

        struct.pack_into("<I", head, OFF_KERNEL_SIZE, len(self.kernel))
        struct.pack_into("<I", head, OFF_RAMDISK_SIZE, len(self.ramdisk))
        struct.pack_into("<I", head, OFF_SECOND_SIZE, len(self.second))
        if self.header_version >= 3:
            struct.pack_into("<I", head, self.vendor_tbl_off, len(self.vendor_ramdisk))
            struct.pack_into("<I", head, self.vendor_tbl_off + 4, len(self.dtb))
        if self.header_version >= 2:
            if self.has_v2_magic:
                struct.pack_into("<I", head, OFF_V2_MAGIC, BOOT_HEADER_V2_MAGIC)
                struct.pack_into("<I", head, OFF_HEADER_SIZE, self.header_size)
            elif self.xiaomi_dtb:
                # Preserve the vendor convention: the loader reads the DTB
                # length from this slot, not from a v2 header field.
                struct.pack_into("<I", head, OFF_XIAOMI_HEADER_SIZE, self.xiaomi_header_size)
                struct.pack_into("<I", head, OFF_XIAOMI_DTB_SIZE, len(self.dtb))

        out = bytearray(head)
        for blob in (self.kernel, self.ramdisk, self.vendor_ramdisk, self.second, self.dtb):
            if not blob:
                continue
            out += blob
            pad = (-len(out)) % page
            out += b"\x00" * pad

        if recompute_id:
            h = hashlib.sha1()
            for blob in (self.kernel, self.ramdisk, self.vendor_ramdisk, self.second, self.dtb):
                h.update(blob)
                h.update(struct.pack("<I", len(blob)))
            struct.pack_into("8s", out, OFF_ID, h.digest())

        if total_size is None:
            total_size = max(len(out), align(len(self.d), page))
        if len(out) > total_size:
            raise ValueError(
                f"payload {len(out)} exceeds target size {total_size}; "
                f"need {len(out)/1048576:.2f} MiB"
            )
        out += b"\x00" * (total_size - len(out))
        return bytes(out)


def classify(d: bytes) -> str:
    if not d:
        return "-"
    if d[:2] == MZ_MAGIC:
        if len(d) > 0x40 and d[0x3C] != 0:
            pe_off = struct.unpack_from("<I", d, 0x3C)[0]
            if d[pe_off : pe_off + 4] == PE_MAGIC:
                mach = struct.unpack_from("<H", d, pe_off + 4)[0]
                sub = struct.unpack_from("<H", d, pe_off + 24)[0]
                opt_magic = struct.unpack_from("<H", d, pe_off + 24)[0]
                return (
                    f"PE/COFF EFI app  machine=0x{mach:04x}"
                    f"{' (AARCH64)' if mach == 0xAA64 else ''}"
                    f"{'  PE32+' if opt_magic == 0x20B else ''}"
                    f"  subsystem={sub}"
                )
        return "MZ"
    if d[:2] == b"\x1f\x8b":
        return "gzip"
    if d[:4] == b"\x1f\x8b\x08\x00":
        return "gzip"
    if d[:6] == b"\xfd7zXZ\x00":
        return "xz"
    if d[:4] == b"\x28\xb5\x2f\xfd":
        return "zstd"
    if d[:4] == b"\x7fELF":
        return "ELF"
    if d[:4] == b"\xd0\x0d\xfe\xed":
        return "FDT (device tree)"
    if b"070701" in d[:64]:
        return "cpio (newc)"
    return "unknown"


def check_efi(path: str):
    with open(path, "rb") as f:
        d = f.read()
    if d[:2] != MZ_MAGIC:
        print(f"ERROR: {path} is not a PE image (no MZ magic)", file=sys.stderr)
        return False
    pe_off = struct.unpack_from("<I", d, 0x3C)[0]
    if d[pe_off : pe_off + 4] != PE_MAGIC:
        print(f"ERROR: {path} has no PE signature", file=sys.stderr)
        return False
    machine = struct.unpack_from("<H", d, pe_off + 4)[0]
    magic = struct.unpack_from("<H", d, pe_off + 24)[0]
    subsys = struct.unpack_from("<H", d, pe_off + 92)[0]
    if machine != 0xAA64:
        print(f"ERROR: {path} machine=0x{machine:04x}, expected 0xAA64 (AArch64)", file=sys.stderr)
        return False
    if magic != 0x20B:
        print(f"ERROR: {path} optional header magic 0x{magic:04x}, expected 0x20B (PE32+)", file=sys.stderr)
        return False
    if subsys != 10:
        print(
            f"WARNING: subsystem={subsys}, expected 10 (EFI_APPLICATION)",
            file=sys.stderr,
        )
    print(f"OK: valid AArch64 PE32+ EFI image, {len(d)} bytes")
    return True


def cmd_inspect(args):
    with open(args.image, "rb") as f:
        b = BootImage(f.read())
    print(f"file: {args.image}")
    print(b.describe())


def cmd_extract(args):
    with open(args.image, "rb") as f:
        b = BootImage(f.read())
    data = {"kernel": b.kernel, "ramdisk": b.ramdisk, "dtb": b.dtb, "second": b.second}[args.what]
    with open(args.out, "wb") as f:
        f.write(data)
    print(f"wrote {len(data)} bytes -> {args.out} ({classify(data)})")


def cmd_inject(args):
    if not args.no_check and not check_efi(args.payload):
        sys.exit(2)
    with open(args.payload, "rb") as f:
        payload = f.read()
    with open(args.image, "rb") as f:
        original = f.read()
    b = BootImage(original)
    target = args.size if args.size else len(original)

    print("before:")
    print(b.describe())

    b.kernel = payload
    out = b.build(total_size=target, recompute_id=not args.no_fix_id)

    with open(args.out, "wb") as f:
        f.write(out)
    print(f"\nwrote {len(out)} bytes ({len(out)/1048576:.2f} MiB) -> {args.out}")

    c = BootImage(out)
    print("\nafter:")
    print(c.describe())
    if c.kernel != payload:
        print("ERROR: kernel payload mismatch", file=sys.stderr)
        sys.exit(3)
    if c.ramdisk != b.ramdisk:
        print("ERROR: ramdisk was altered", file=sys.stderr)
        sys.exit(3)
    print("\nverified: kernel replaced, ramdisk intact")


def cmd_verify(args):
    with open(args.image, "rb") as f:
        b = BootImage(f.read())
    with open(args.payload, "rb") as f:
        p = f.read()
    ok = b.kernel == p
    print(f"image  : {args.image}")
    print(f"payload: {args.payload}")
    print(f"match  : {ok}")
    sys.exit(0 if ok else 1)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("inspect")
    p.add_argument("image")
    p.set_defaults(func=cmd_inspect)

    p = sub.add_parser("extract")
    p.add_argument("image")
    p.add_argument("what", choices=["kernel", "ramdisk", "dtb", "second"])
    p.add_argument("out")
    p.set_defaults(func=cmd_extract)

    p = sub.add_parser("inject")
    p.add_argument("image")
    p.add_argument("payload")
    p.add_argument("out")
    p.add_argument("--size", type=int, default=0, help="target image size in bytes (default: same as input)")
    p.add_argument("--no-fix-id", action="store_true", help="do not recompute the boot image SHA1 id")
    p.add_argument("--no-check", action="store_true", help="skip PE/EFI validation of the payload")
    p.set_defaults(func=cmd_inject)

    p = sub.add_parser("verify")
    p.add_argument("image")
    p.add_argument("payload")
    p.set_defaults(func=cmd_verify)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
