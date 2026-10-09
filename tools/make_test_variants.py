#!/usr/bin/env python3
"""
Build test variants of boot-courbet.img to find what the loader actually
accepts.

Variant A - minimal change from the image that hung: swap the gzipped kernel
            for the raw firmware volume. Everything else untouched.
Variant B - raw kernel plus the stock cmdline and stock ramdisk, in case the
            loader needs the androidboot.* environment to configure the MMU.

Both are padded to the real 128 MiB partition size.
"""

import gzip
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from repack import BootImage

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "work"
FD = WORK / "SM7150_UEFI.fd"
BUILT = WORK / "boot-courbet.img"
STOCK = Path.home() / "Desktop" / "boot" / "boot.img"
PARTITION = 0x8000000  # from fastboot: partition-size:boot = 0x8000000

raw_fd = FD.read_bytes()
gz_fd = gzip.compress(raw_fd)
print(f"raw FD          : {len(raw_fd)} bytes, first bytes {raw_fd[:8].hex()}")
print(f"gzip FD         : {len(gz_fd)} bytes")
print(f"partition target: {PARTITION} bytes (128 MiB, from fastboot getvar)")


def pad(img: BootImage, path: Path, keep_stock_cmdline: bool, keep_stock_ramdisk: bool):
    base = BootImage(BUILT.read_bytes())
    stock = BootImage(STOCK.read_bytes())

    base.kernel = raw_fd
    if keep_stock_cmdline:
        base.d = bytearray(base.d)
        base.d[64 : 64 + 512] = stock.cmdline.encode()[:511].ljust(512, b"\x00")
        base.cmdline = stock.cmdline
    if keep_stock_ramdisk:
        base.ramdisk = stock.ramdisk
        base.ramdisk_size = len(stock.ramdisk)

    out = base.build(total_size=PARTITION)
    path.write_bytes(out)
    check = BootImage(out)
    print(
        f"\n{path.name}"
        f"\n  kernel  : {len(check.kernel)} bytes, starts {check.kernel[:8].hex()}"
        f"\n  ramdisk : {check.ramdisk_size} bytes"
        f"\n  dtb     : {check.dtb_size} bytes (xiaomi_dtb={check.xiaomi_dtb})"
        f"\n  cmdline : {check.cmdline[:60]}{'...' if len(check.cmdline) > 60 else ''}"
        f"\n  total   : {len(out)} bytes"
    )
    assert check.kernel == raw_fd, "kernel mismatch"
    assert check.xiaomi_dtb, "DTB field lost"


pad(BootImage(BUILT.read_bytes()), WORK / "test-A-raw.img", False, False)
pad(BootImage(BUILT.read_bytes()), WORK / "test-B-raw-stock.img", True, True)
print("\nboth written")
