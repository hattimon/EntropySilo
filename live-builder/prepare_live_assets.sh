#!/bin/bash
set -Eeuo pipefail
umask 022

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
OUT=${1:?Podaj katalog wyjściowy zasobów Live}
NODE_VERSION=22.23.1
mkdir -p "$OUT"
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

curl --fail --location --proto '=https' --tlsv1.2 \
  "https://nodejs.org/download/release/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-x64.tar.xz" \
  -o "$OUT/node-v${NODE_VERSION}-linux-x64.tar.xz"
curl --fail --location --proto '=https' --tlsv1.2 \
  "https://nodejs.org/download/release/v${NODE_VERSION}/SHASUMS256.txt" -o "$work/NODE-SHASUMS256.txt"
(cd "$OUT" && grep " node-v${NODE_VERSION}-linux-x64.tar.xz$" "$work/NODE-SHASUMS256.txt" | sha256sum -c -)
mkdir -p "$work/node"
tar -xJf "$OUT/node-v${NODE_VERSION}-linux-x64.tar.xz" --strip-components=1 -C "$work/node"
NPM="$work/node/bin/npm"

swd="$ROOT/build/assets/Seed-Generator-Wallet-Decoder.tar.gz"
[[ -f $swd ]] || { echo "Brak $swd. Najpierw przygotuj przypięty pakiet SWD." >&2; exit 1; }
cp -- "$swd" "$OUT/"

mkdir -p "$work/entropysilo"
tar --exclude='apps/__pycache__' --exclude='*.pyc' -cf - -C "$ROOT" \
  apps config scripts systemd wrappers tests \
  package.json package-lock.json README.md README.pl.md SECURITY.md SECURITY.pl.md \
  | tar -xf - -C "$work/entropysilo"
"$NPM" --prefix "$work/entropysilo" ci --ignore-scripts
"$NPM" --prefix "$work/entropysilo" test
"$NPM" --prefix "$work/entropysilo" audit --omit=dev
bash "$work/entropysilo/tests/test_usb_boot_exclusion.sh"
chmod 0755 "$work/entropysilo"/scripts/*.sh "$work/entropysilo"/wrappers/* \
  "$work/entropysilo"/apps/*.js "$work/entropysilo"/apps/*.sh "$work/entropysilo"/apps/*.py
tar --sort=name --mtime='UTC 2026-08-06' --owner=0 --group=0 --numeric-owner \
  -czf "$OUT/EntropySilo-runtime.tar.gz" -C "$work" entropysilo

(cd "$OUT" && sha256sum node-v*-linux-x64.tar.xz Seed-Generator-Wallet-Decoder.tar.gz EntropySilo-runtime.tar.gz > SHA256SUMS)
echo "Gotowe zasoby Live: $OUT"
