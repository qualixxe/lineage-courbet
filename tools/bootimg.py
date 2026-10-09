#!/usr/bin/env python3
"""
Android boot image inspector (v0-v4).
Used to analyse boot.img before repacking a UEFI payload into it.

Layout reference: AOSP system/tools/mkbootimg/bootimg.py
"""

import gzip
import hashlib
import lzma
import struct
import sys

BOOT_MAGIC = b"ANDROID!"
BOOT_MAGIC_SIZE = 8
VENDOR_BOOT_MAGIC = b"VNDRBOOT"
BOOT_HEADER_V2_MAGIC = 0x2FFE6506

BOOT_NAME_SIZE = 16
BOOT_ARGS_SIZE = 512
BOOT_EXTRA_ARGS_SIZE = 1024
BOOT_HEADER_SIZE_V1 = 1648

U32 = lambda b, o: struct.unpack_from("<I", b, o)[0]
U64 = lambda b, o: struct.unpack_from("<Q", b, o)[0]

PAYLOAD_KINDS = {
    1: "RAW",
    2: "GZIP",
    3: "LZMA",
    4: "LZ4",
    5: "ZSTD",
    6: "LZ4_LEGACY",
}


def sha1(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


class BootImage:
    def __init__(self, data: bytes):
        self.d = data
        self.parse()

    def parse(self):
        d = self.d
        if d[:BOOT_MAGIC_SIZE] != BOOT_MAGIC:
            raise ValueError("not an ANDROID! boot image")

        self.kernel_size = U32(d, 8)
        self.kernel_addr = U32(d, 12)
        self.ramdisk_size = U32(d, 16)
        self.ramdisk_addr = U32(d, 20)
        self.second_size = U32(d, 24)
        self.second_addr = U32(d, 28)
        self.tags_addr = U32(d, 32)
        self.page_size = U32(d, 36)
        self.header_version = U32(d, 40)
        self.os_version = U32(d, 44)

        self.name = d[48 : 48 + BOOT_NAME_SIZE].split(b"\x00")[0].decode("utf-8", "replace")
        self.cmdline = d[64 : 64 + BOOT_ARGS_SIZE].split(b"\x00")[0].decode("utf-8", "replace")

        if self.header_version >= 1:
            self.extra_cmdline = (
                d[BOOT_HEADER_SIZE_V1 - BOOT_EXTRA_ARGS_SIZE : BOOT_HEADER_SIZE_V1]
                .split(b"\x00")[0]
                .decode("utf-8", "replace")
            )
        else:
            self.extra_cmdline = ""

        self.vendor_ramdisk_size = 0
        self.dtb_size = 0

        if self.header_version >= 3:
            # header_version field holds the offset of the vendor fields table
            voff = self.header_version
            self.vendor_ramdisk_size = U32(d, voff)
            self.dtb_size = U32(d, voff + 4)

        self.payloads = []
        page = self.page_size or 2048
        off = page  # skip header page(s) -> use total header size properly
        off = self._header_end(page)

        self.payloads.append(("kernel", off, self.kernel_size))
        off += align(self.kernel_size, page)
        if self.ramdisk_size:
            self.payloads.append(("ramdisk", off, self.ramdisk_size))
            off += align(self.ramdisk_size, page)
        if self.header_version >= 3 and self.vendor_ramdisk_size:
            self.payloads.append(("vendor_ramdisk", off, self.vendor_ramdisk_size))
            off += align(self.vendor_ramdisk_size, page)
        if self.second_size:
            self.payloads.append(("second", off, self.second_size))
            off += align(self.second_size, page)
        if self.dtb_size:
            self.payloads.append(("dtb", off, self.dtb_size))
            off += align(self.dtb_size, page)

        self.payload_end = off

    def _header_end(self, page):
        if self.header_version >= 3:
            voff = self.header_version
            num = U32(d, voff + 12)
            # each vendor table entry is 8 bytes (size,type), chain ends at 0
            total = page * (1 if self.header_version < 3 else 1)
            end = voff + 16 + num * 8
            if end % page:
                end += page - (end % page)
            return end
        return page

    def get(self, name):
        for n, off, size in self.payloads:
            if n == name:
                return self.d[off : off + size]
        return b""

    def describe(self):
        L = []
        a = L.append
        page = self.page_size or 2048
        a("=== BOOT IMAGE HEADER ===")
        a(f"name            : {self.name}")
        a(f"header_version  : {self.header_version}")
        a(f"os_version      : 0x{self.os_version:08x}")
        a(f"page_size       : {page}")
        a(f"cmdline         : {self.cmdline}")
        if self.extra_cmdline:
            a(f"extra_cmdline   : {self.extra_cmdline}")
        a("")
        a("=== PAYLOADS ===")
        a(f"{'name':<16}{'offset':>12}{'size':>12}{'sha1':>42}")
        for n, off, size in self.payloads:
            d = self.get(n)
            a(f"{n:<16}{off:>12}{size:>12}{sha1(d):>42}")
        a("")
        a("=== LOAD ADDRESSES ===")
        a(f"kernel_addr     : 0x{self.kernel_addr:08x}")
        a(f"ramdisk_addr    : 0x{self.ramdisk_addr:08x}")
        a(f"second_addr     : 0x{self.second_addr:08x}")
        a(f"tags_addr       : 0x{self.tags_addr:08x}")
        a("")
        a("=== IMAGE ===")
        a(f"total size      : {len(self.d)} ({len(self.d)/1048576:.2f} MiB)")
        a(f"payload end     : {self.payload_end} ({self.payload_end/1048576:.2f} MiB)")
        slack = len(self.d) - self.payload_end
        a(f"slack           : {slack} ({slack/1048576:.2f} MiB)")
        return "\n".join(L)

    def probe(self):
        L = []
        a = L.append
        a("=== PAYLOAD PROBE ===")
        for n, off, size in self.payloads:
            d = self.get(n)
            if not d:
                continue
            a(f"-- {n} --")
            if d[:4] == b"\x1f\x8b\x08\x00" or d[:2] == b"\x1f\x8b":
                a("  format   : gzip")
                try:
                    dec = gzip.decompress(d)
                    a(f"  inflated : {len(dec)} bytes")
                    a(f"  sha1     : {sha1(dec)}")
                    a(f"  head     : {dec[:48]!r}")
                except Exception as e:
                    a(f"  inflate failed: {e}")
            elif d[:6] == b"\x5d\x00\x00" or d[:2] == b"\xfd\x37":
                a("  format   : xz/lzma")
            elif d[:4] == b"\x28\xb5\x2f\xfd":
                a("  format   : zstd")
            elif d[:4] == b"\xd0\xcf\x11\xe0":
                a("  format   : MZ (PE/COFF UEFI application!)")
            elif d[:4] == b"\x7fELF":
                a("  format   : ELF")
                a(f"  class={d[4]} (1=32,2=64)  machine=0x{struct.unpack_from('<H', d, 18)[0]:04x} (183=AARCH64)")
            elif d[:4] == b"\xd0\x0d\xfe\xed":
                a("  format   : FDT (device tree blob)")
            elif d[257:262] == b"070701":
                a("  format   : Android boot image (cpio?)")
            elif d[:2] == b"\xc7\x71" or b"070701" in d[:64]:
                a("  format   : newc cpio")
            else:
                a(f"  format   : unknown, head={d[:32]!r}")
            # search for cpio '070701' magic anywhere in first 512 bytes
            idx = d[:4096].find(b"070701")
            if idx >= 0:
                a(f"  cpio magic found at offset {idx} within payload")
        return "\n".join(L)


def align(x, p):
    return (x + p - 1) // p * p


def main():
    path = sys.argv[1]
    with open(path, "rb") as f:
        data = f.read()
    b = BootImage(data)
    print(b.describe())
    print()
    print(b.probe())


if __name__ == "__main__":
    main()
