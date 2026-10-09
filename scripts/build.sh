#!/usr/bin/env bash
#
# Builds the AArch64 UEFI payload for Xiaomi Mi 11 Lite 4G (courbet).
#
# Expects an edk2 working copy at $ROOT/edk2 (see .github/workflows/build.yml).
# Produces a single standalone EFI application in $ROOT/out/.
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EDK2="${EDK2:-$ROOT/edk2}"
OUT="$ROOT/out"

ARCH="${ARCH:-AARCH64}"
TARGET="${TARGET:-RELEASE}"
TOOLCHAIN="${TOOLCHAIN:-GCC5}"
JOBS="${JOBS:-$(nproc)}"

if [ ! -d "$EDK2/BaseTools" ]; then
    echo "error: edk2 not found at $EDK2" >&2
    exit 1
fi

# ---------------------------------------------------------------- environment
export WORKSPACE="$ROOT"
export PACKAGES_PATH="$EDK2"
export EDK_TOOLS_PATH="$EDK2/BaseTools"
export CONF_PATH="$EDK2/BaseTools/Conf"
export TOOL_CHAIN_TAG="$TOOLCHAIN"

# Cross toolchain. edk2 addresses GCC5_AARCH64_<tool>_PREFIX, the generic
# CROSS_COMPILE is kept in sync for tools that consult it directly.
if [ "$ARCH" = "AARCH64" ]; then
    export CROSS_COMPILE="aarch64-linux-gnu-"
    export GCC5_AARCH64_PREFIX="aarch64-linux-gnu-"
fi

if ! command -v "${CROSS_COMPILE}gcc" >/dev/null 2>&1; then
    echo "error: ${CROSS_COMPILE}gcc not found. Install gcc-aarch64-linux-gnu." >&2
    exit 1
fi

echo "==> toolchain: ${CROSS_COMPILE}gcc ($("${CROSS_COMPILE}gcc" --version | head -1))"
echo "==> arch=$ARCH target=$TARGET toolchain=$TOOLCHAIN jobs=$JOBS"

# `set -u` is disabled around the sourcing of edk2's own shell code: edksetup.sh
# and build_env.sh reference variables that are legitimately unset, and `-u`
# would abort the build on the first one of those.
set +u
# shellcheck disable=SC1091
source "$EDK2/edksetup.sh"
set -u

# ------------------------------------------------------------- BaseTools host
echo "==> building BaseTools"
make -C "$EDK2/BaseTools" -j"$JOBS" 2>&1 | tail -5

# shellcheck disable=SC1091
set +u
source "$EDK2/BaseTools/BinWrappers/PosixLike/build_env.sh"
set -u

# ----------------------------------------------------------------- firmware
# BOOT_MANAGER_ESCAPE=TRUE forces the graphical boot menu (UiApp) to appear,
# which is what gives us the front-end the user asked for.
echo "==> building UefiPayloadPkg"
build \
    -a "$ARCH" \
    -t "$TOOLCHAIN" \
    -b "$TARGET" \
    -p UefiPayloadPkg/UefiPayloadPkg.dsc \
    -n "$JOBS" \
    -D BOOTLOADER=SBL \
    -D BOOT_MANAGER_ESCAPE=TRUE \
    -D BOOTSPLASH_IMAGE=FALSE \
    -D PLATFORM_BOOT_TIMEOUT=10 \
    2>&1 | tee "$ROOT/build.log"

# --------------------------------------------------------------- collect
rm -rf "$OUT"
mkdir -p "$OUT"

# The output path encodes TARGET/TOOLCHAIN, so locate it rather than guessing.
EFI="$(find "$EDK2/Build" -name 'UefiPayloadPkg.efi' -type f | head -1 || true)"
if [ -z "$EFI" ]; then
    echo "error: UefiPayloadPkg.efi not produced; see $ROOT/build.log" >&2
    exit 1
fi

cp "$EFI" "$OUT/UefiPayloadPkg.efi"

echo
echo "==> done"
ls -la "$OUT"
file "$OUT/UefiPayloadPkg.efi" || true
