#!/bin/bash
set -Eeuo pipefail
umask 022

[[ $EUID -eq 0 ]] || { echo "Uruchom jako root: sudo $0" >&2; exit 1; }
ASSETS=/opt/assets
case $(uname -m) in
  armv7l) node_arch=armv7l; expected_process_arch=arm;;
  aarch64) node_arch=arm64; expected_process_arch=arm64;;
  x86_64) node_arch=x64; expected_process_arch=x64;;
  *) echo "Nieobsługiwana architektura Node: $(uname -m)" >&2; exit 1;;
esac
mapfile -t archives < <(find "$ASSETS" -maxdepth 1 -type f -name "node-v22.*-linux-${node_arch}.tar.xz" -print)
[[ ${#archives[@]} -eq 1 ]] || { echo "Wymagany dokładnie jeden $ASSETS/node-v22.*-linux-${node_arch}.tar.xz" >&2; exit 1; }
archive=${archives[0]}

if [[ -f "$ASSETS/SHA256SUMS" ]]; then
  expected=$(awk -v name="$(basename "$archive")" '$2 == name {print $1}' "$ASSETS/SHA256SUMS")
  [[ $expected =~ ^[0-9a-fA-F]{64}$ ]] || { echo "Brak hash Node w SHA256SUMS" >&2; exit 1; }
  actual=$(sha256sum "$archive" | awk '{print $1}')
  [[ $actual == "$expected" ]] || { echo "BŁĄD: SHA-256 archiwum Node nie zgadza się" >&2; exit 1; }
else
  echo "BŁĄD: brak $ASSETS/SHA256SUMS; instalacja bez weryfikacji jest zabroniona" >&2; exit 1
fi

rm -rf /opt/node-v22.new
install -d -m 0755 /opt/node-v22.new
tar -xJf "$archive" --strip-components=1 --no-same-owner -C /opt/node-v22.new
[[ $(/opt/node-v22.new/bin/node -p 'process.arch') == "$expected_process_arch" ]] || { echo "Nieprawidłowa architektura Node" >&2; exit 1; }
[[ $(/opt/node-v22.new/bin/node -p 'process.versions.node.split(`.`)[0]') == 22 ]] || { echo "To nie jest Node 22" >&2; exit 1; }
rm -rf /opt/node-v22
mv /opt/node-v22.new /opt/node-v22
ln -sfn /opt/node-v22/bin/node /usr/local/bin/node
ln -sfn /opt/node-v22/bin/npm /usr/local/bin/npm
ln -sfn /opt/node-v22/bin/npx /usr/local/bin/npx
/usr/local/bin/node -v
/usr/local/bin/npm -v
