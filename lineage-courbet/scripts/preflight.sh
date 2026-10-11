#!/bin/bash
# Pre-build diagnostics + workarounds for courbet unofficial trees.
# Runs INSIDE the Lineage source root, after `repo sync`.
set -e
echo "=== courbet preflight ==="

fix_deps() {
  f="device/xiaomi/courbet/lineage.dependencies"
  if [ -f "$f" ]; then
    echo "--- $f (raw) ---"
    cat "$f"
    # upstream file has a trailing comma -> invalid JSON, breaks breakfast
    python3 - "$f" <<'PY'
import re, json, sys
p = sys.argv[1]
s = open(p, encoding='utf-8').read()
s2 = re.sub(r',\s*([\}\]])', r'\1', s)
json.loads(s2)  # validate
open(p, 'w', encoding='utf-8').write(s2)
print("lineage.dependencies: trailing commas fixed, JSON OK")
PY
  fi
}

check_kernel() {
  echo "--- kernel check ---"
  ls kernel/xiaomi/courbet/arch/arm64/configs/ 2>/dev/null | head -50 || true
  ls kernel/xiaomi/courbet/arch/arm64/configs/vendor/ 2>/dev/null | head -80 || true
  if [ ! -f "kernel/xiaomi/courbet/arch/arm64/configs/courbet_defconfig" ]; then
    echo "WARNING: courbet_defconfig missing in kernel/xiaomi/courbet"
    if [ -f "kernel/xiaomi/courbet/arch/arm64/configs/vendor/sdmsteppe_defconfig" ]; then
      echo "WORKAROUND: symlink courbet_defconfig -> vendor/sdmsteppe_defconfig"
      ln -sf vendor/sdmsteppe_defconfig kernel/xiaomi/courbet/arch/arm64/configs/courbet_defconfig
    else
      echo "ERROR: no sdmsteppe_defconfig fallback either, build will fail at kernel step"
      return 1
    fi
  else
    echo "courbet_defconfig present"
  fi
  echo "--- BoardConfig kernel lines ---"
  grep -n "TARGET_KERNEL" device/xiaomi/courbet/BoardConfig.mk || true
}

check_vendor() {
  echo "--- vendor check ---"
  for d in vendor/xiaomi/courbet vendor/xiaomi/sm6150-common; do
    if [ -d "$d" ]; then echo "OK $d"; else echo "MISSING $d"; fi
  done
  ls vendor/xiaomi/courbet/ 2>/dev/null | head -20 || true
}

fix_deps
check_vendor
check_kernel
echo "=== preflight done ==="
