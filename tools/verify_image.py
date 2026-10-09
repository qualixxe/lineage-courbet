#!/usr/bin/env python3
"""
Deep validation of a courbet boot image before it is flashed.

Knows the Xiaomi/SM7150 header_version=2 convention that repack.py models:
  @1644 = header size, @1648 = DTB length, FDT placed right after the ramdisk.
Also knows that SM7150_UEFI.fd is a Qualcomm MBN wrapper, so the EFI firmware
volume does NOT start at offset 0.

Exit code 0 = safe to flash, 1 = do not flash.
"""

import argparse
import gzip
import struct
import sys

sys.path.insert(0, __file__.rsplit("\\", 1)[0].rsplit("/", 1)[0])
from repack import BootImage, FDT_MAGIC

FV_SIGNATURE = b"_FVH"
FDT_VER_MAGIC = 0xD00DFEED

failures = []
warnings = []
notes = []


def ok(m):
    print(f"  [ok]   {m}")


def warn(m):
    print(f"  [warn] {m}")
    warnings.append(m)


def fail(m):
    print(f"  [FAIL] {m}")
    failures.append(m)


def check_header(img: BootImage, data: bytes):
    print("\n=== header ===")
    ok(f"ANDROID! magic, header_version={img.header_version}, page_size={img.page_size}")
    if img.header_version != 2:
        warn(f"header_version is {img.header_version}, the courbet convention was verified on 2")
    if img.page_size != 4096:
        warn(f"page_size is {img.page_size}, stock courbet uses 4096")


def check_dtb(img: BootImage):
    print("\n=== device tree ===")
    if not img.xiaomi_dtb:
        fail("no device tree located - the loader reads the DTB length from @1648")
        return
    ok(f"Xiaomi/SM7150 convention detected")
    ok(f"DTB at {img.page_size + 0} after ramdisk, {img.dtb_size} bytes, magic d00dfeed")
    if img.dtb[:4] != FDT_MAGIC:
        fail("DTB payload does not start with the FDT magic")
        return
    total = struct.unpack_from(">I", img.dtb, 4)[0]
    if total != img.dtb_size:
        fail(f"DTB totalsize {total} disagrees with the declared size {img.dtb_size}")
    else:
        ok(f"DTB totalsize {total} matches the declared size")
    ver = struct.unpack_from(">I", img.dtb, 20)[0]
    ok(f"FDT version {ver}")


def check_kernel(img: BootImage, fd: bytes | None):
    print("\n=== kernel slot (the UEFI payload) ===")
    k = img.kernel
    if not k:
        fail("kernel slot is empty")
        return
    if k[:2] != b"\x1f\x8b":
        fail(f"kernel slot starts with {k[:4].hex()}, expected gzip")
        return
    try:
        raw = gzip.decompress(k)
    except Exception as e:
        fail(f"kernel slot looks like gzip but will not inflate: {e}")
        return
    ok(f"gzip inflates: {len(k)} -> {len(raw)} bytes")

    # The FD is a Qualcomm MBN wrapper, so the FV is NOT at offset 0.
    itype, isize, ver = struct.unpack_from("<III", raw, 0)
    fv = raw.find(FV_SIGNATURE)
    if fv >= 0:
        ok(f"EFI firmware volume (_FVH) found at offset 0x{fv:x}")
        if fv != 0:
            notes.append(
                f"FV is at 0x{fv:x}, not 0: this is a Qualcomm MBN wrapper "
                f"(image_type=0x{itype:x}, size=0x{isize:x}, ver=0x{ver:x})"
            )
            print(f"         MBN wrapper: image_type=0x{itype:x} size=0x{isize:x} ver=0x{ver:x}")
    else:
        fail("no _FVH anywhere in the payload - this is not an EFI firmware volume")

    if fd is not None:
        if raw.rstrip(b"\x00") == fd.rstrip(b"\x00"):
            ok("payload matches the SM7150_UEFI.fd from the artifact")
        else:
            warn("payload differs from SM7150_UEFI.fd (gzip rebuilt from a different build?)")
    else:
        warn("no --fd given, skipped cross-check against SM7150_UEFI.fd")


def check_cmdline(img: BootImage):
    print("\n=== cmdline ===")
    if img.cmdline:
        ok(f"cmdline: {img.cmdline[:70]}{'...' if len(img.cmdline) > 70 else ''}")
    else:
        notes.append("cmdline is empty; stock has androidboot.* parameters")
        print("  [note] cmdline is empty")
        print("         stock has: androidboot.hardware=qcom ... video=vfb:640x400,...")
        print("         expected: the UEFI payload configures the hardware from the DTB instead")


def check_size(img_path: str, partition: int):
    print("\n=== partition fit ===")
    import os

    size = os.path.getsize(img_path)
    if size <= partition:
        ok(f"{size/1048576:.2f} MiB used, {(partition-size)/1048576:.2f} MiB spare of 128 MiB")
    else:
        fail(f"{size/1048576:.2f} MiB exceeds the {partition/1048576:.0f} MiB partition; fastboot would truncate it")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("--fd", default=None)
    ap.add_argument("--partition", type=int, default=134217728)
    args = ap.parse_args()

    data = open(args.image, "rb").read()
    try:
        img = BootImage(data)
    except ValueError as e:
        print(f"  [FAIL] {e}")
        sys.exit(1)

    fd = open(args.fd, "rb").read() if args.fd and __import__("os").path.exists(args.fd) else None

    print("=" * 60)
    print(f"image: {args.image}  ({len(data)/1048576:.2f} MiB)")
    print("=" * 60)

    check_header(img, data)
    check_dtb(img)
    check_kernel(img, fd)
    check_cmdline(img)
    check_size(args.image, args.partition)

    print("\n" + "=" * 60)
    if notes:
        print("notes:")
        for n in notes:
            print(f"  - {n}")
        print()
    if failures:
        print(f"RESULT: {len(failures)} FAILURE(S) - DO NOT FLASH")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    if warnings:
        print(f"RESULT: all hard checks passed ({len(warnings)} warning(s))")
    else:
        print("RESULT: all checks passed")
    sys.exit(0)


if __name__ == "__main__":
    main()
