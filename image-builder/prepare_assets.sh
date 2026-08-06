#!/bin/bash
set -Eeuo pipefail
umask 022

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
OUT=${1:-"$ROOT/build/assets"}
NODE_VERSION=22.23.1
SWD_REF=c115e6ce66bc410a50e5f9d13ed121fb7692ab68
mkdir -p "$OUT"
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

curl --fail --location --proto '=https' --tlsv1.2 \
  "https://nodejs.org/download/release/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-armv7l.tar.xz" \
  -o "$OUT/node-v${NODE_VERSION}-linux-armv7l.tar.xz"
curl --fail --location --proto '=https' --tlsv1.2 \
  "https://nodejs.org/download/release/v${NODE_VERSION}/SHASUMS256.txt" -o "$work/NODE-SHASUMS256.txt"
(cd "$OUT" && grep " node-v${NODE_VERSION}-linux-armv7l.tar.xz$" "$work/NODE-SHASUMS256.txt" | sha256sum -c -)

git clone --filter=blob:none https://github.com/hattimon/Seed-Generator-Wallet-Decoder.git "$work/swd"
git -C "$work/swd" checkout --detach "$SWD_REF"
npm --prefix "$work/swd" ci --ignore-scripts
npm --prefix "$work/swd" run check
tar --sort=name --mtime='UTC 2026-08-03' --owner=0 --group=0 --numeric-owner \
  -czf "$OUT/Seed-Generator-Wallet-Decoder.tar.gz" -C "$work" swd

git clone --depth 1 https://github.com/waveshareteam/LCD-show.git "$work/LCD-show"
git -C "$work/LCD-show" rev-parse HEAD > "$OUT/LCD-show.commit.txt"
tar --sort=name --owner=0 --group=0 --numeric-owner -czf "$OUT/LCD-show.tar.gz" -C "$work" LCD-show

mkdir -p "$work/EntropySilo"
# Package only reviewed runtime sources.  A broad workspace archive could silently
# include editor files, previous images or an accidentally dropped secret.
tar --exclude='apps/__pycache__' --exclude='*.pyc' -cf - -C "$ROOT" \
  apps config scripts systemd wrappers tests \
  package.json package-lock.json README.md README.pl.md SECURITY.md SECURITY.pl.md \
  | tar -xf - -C "$work/EntropySilo"
npm --prefix "$work/EntropySilo" ci --ignore-scripts
npm --prefix "$work/EntropySilo" test
npm --prefix "$work/EntropySilo" audit --omit=dev
chmod 0755 "$work/EntropySilo"/scripts/*.sh "$work/EntropySilo"/wrappers/* "$work/EntropySilo"/apps/*.js \
  "$work/EntropySilo"/apps/*.sh "$work/EntropySilo"/apps/*.py
tar --sort=name --owner=0 --group=0 --numeric-owner -czf "$OUT/EntropySilo.tar.gz" -C "$work" EntropySilo

(cd "$OUT" && sha256sum node-v*-linux-armv7l.tar.xz Seed-Generator-Wallet-Decoder.tar.gz LCD-show.tar.gz EntropySilo.tar.gz > SHA256SUMS)
echo "Gotowe zasoby: $OUT"
