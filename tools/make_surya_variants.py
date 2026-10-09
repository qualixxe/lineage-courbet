#!/usr/bin/env python3
"""
Derive courbet test images from the known-working surya UEFI image.

Layout of a working xiaomi-surya_NOSB.img (SM7150 family, Snapdragon 732G):

    header (v0, 1 page)
    kernel = <gzip member: MBN(112) || ARM64 Image>  ||  <raw FDT>
                                                ^^^^^^^^^^^^^^^^^^^^^^^^
                                                the device tree is INSIDE the
                                                kernel payload, appended after
                                                the compressed stream - not in a
                                                header field, not after the
                                                ramdisk

Why this matters: after the bootloader inflates the kernel it looks for the
ARM64 magic "ARM\\x64" at offset 0x38 (56). SM7150_UEFI.fd from build.sh is a
plain EFI firmware volume with no ARM64 image header, which is why the device
hung on the Mi logo instead of booting anything.

surya and courbet are both SM7150 (Snapdragon 732G). The firmware is the same
family; the device tree is what differs per board. So the experiment is: take a
bootable UEFI image and swap only the device tree.

The original gzip member is reused byte for byte - only the FDT is replaced, so
nothing about the bootable payload is disturbed.

Read-only experiment: the outputs are meant for `fastboot boot`, which never
writes to flash.
"""

import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from repack import BootImage, FDT_MAGIC, align

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "work"
SURYA = WORK / "surya" / "xiaomi-surya"
PARTITION = 0x8000000

src = SURYA / "xiaomi-surya_NOSB.img"
img = BootImage(src.read_bytes())
k = img.kernel

# Split the kernel payload into the gzip member and the trailing FDT.
o = zlib.decompressobj(16 + zlib.MAX_WBITS)
inflated = o.decompress(k) + o.flush()
gz_len = len(k) - len(o.unused_data)
gz_member = k[:gz_len]
dtb = k[gz_len:]

print("source : %s (%d bytes)" % (src.name, len(src.read_bytes())))
print("header : version=%d page=%d cmdline=%r" % (img.header_version, img.page_size, img.cmdline))
print("kernel : %d bytes = gzip(%d) + dtb(%d)" % (len(k), gz_len, len(dtb)))
print("         gzip inflates to %d bytes" % len(inflated))
magic_at_56 = inflated[56:60]
print("         magic at 0x38: %r  %s" % (magic_at_56, "<- ARM64 image header" if magic_at_56 == b"ARM\x64" else "<- NOT an ARM64 image"))
if dtb[:4] == FDT_MAGIC:
    import struct
    print("         dtb totalsize: %d (matches tail: %s)"
          % (struct.unpack_from(">I", dtb, 4)[0], struct.unpack_from(">I", dtb, 4)[0] == len(dtb)))
else:
    print("         !! kernel tail is not an FDT")

courbet_dtb = Path(ROOT / "work" / "edk2-sm7150" / "qcom-courbet.dtb").read_bytes()
if courbet_dtb[:4] != FDT_MAGIC:
    raise SystemExit("qcom-courbet.dtb is not an FDT")
print("\ncourbet dtb: %d bytes" % len(courbet_dtb))


def emit(path: Path, new_dtb: bytes, label: str):
    base = BootImage(src.read_bytes())
    base.kernel = gz_member + new_dtb
    base.cmdline = ""
    out = base.build(total_size=None)
    if len(out) > PARTITION:
        raise SystemExit("image exceeds the boot partition")
    out = out + b"\x00" * (PARTITION - len(out))
    path.write_bytes(out)
    chk = BootImage(out)
    tail = chk.kernel[gz_len:]
    import struct
    tot = struct.unpack_from(">I", tail, 4)[0] if tail[:4] == FDT_MAGIC else -1
    print("\n%s -> %s" % (label, path.name))
    print("   kernel     : %d bytes = gzip(%d) + dtb(%d)" % (len(chk.kernel), gz_len, len(tail)))
    print("   dtb magic  : %s, totalsize %d (tail matches: %s)"
          % (tail[:4].hex(), tot, tot == len(tail)))
    print("   header     : version=%d page=%d cmdline=%r"
          % (chk.header_version, chk.page_size, chk.cmdline))
    print("   total      : %d bytes (%.0f MiB, padded to partition)" % (len(out), len(out) / 1048576))
    # Prove the compressed part is untouched, so the only variable is the DTB.
    same = chk.kernel[:gz_len] == gz_member
    print("   gzip member byte-identical to source: %s" % same)
    assert same
    assert tail == new_dtb
    assert tot == len(new_dtb)


# Control: the original image, rebuilt through our own toolchain.
emit(WORK / "test-0-surya-control.img", dtb, "CONTROL: surya UEFI + surya DTB (should boot)")
# The experiment: same firmware, courbet's device tree.
emit(WORK / "test-1-surya-courbet-dtb.img", courbet_dtb, "EXPERIMENT: surya UEFI + courbet DTB")

print("\nBoth are for `fastboot boot` only - nothing is written to the phone.")
