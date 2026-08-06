#!/bin/bash
set -Eeuo pipefail
umask 077
[[ $EUID -eq 0 ]] || { echo "Uruchom jako root: sudo $0" >&2; exit 1; }
id wallet >/dev/null 2>&1 || { echo "Najpierw uruchom os_hardening.sh" >&2; exit 1; }
archive=/opt/assets/Seed-Generator-Wallet-Decoder.tar.gz
[[ -f $archive ]] || { echo "Brak $archive" >&2; exit 1; }
[[ -f /opt/assets/SHA256SUMS ]] || { echo "Brak /opt/assets/SHA256SUMS" >&2; exit 1; }
expected=$(awk -v name="$(basename "$archive")" '$2 == name {print $1}' /opt/assets/SHA256SUMS)
actual=$(sha256sum "$archive" | awk '{print $1}')
[[ $expected =~ ^[0-9a-fA-F]{64}$ && $actual == "$expected" ]] || { echo "Błędny SHA-256 SWD" >&2; exit 1; }

rm -rf /opt/Seed-Generator-Wallet-Decoder.new
install -d -m 0700 -o wallet -g wallet /opt/Seed-Generator-Wallet-Decoder.new
tar -xzf "$archive" --strip-components=1 --no-same-owner -C /opt/Seed-Generator-Wallet-Decoder.new
[[ -d /opt/Seed-Generator-Wallet-Decoder.new/node_modules ]] || { echo "Archiwum nie zawiera node_modules" >&2; exit 1; }
grep -q 'seed-generator-wallet-decoder' /opt/Seed-Generator-Wallet-Decoder.new/package.json || { echo "To nie jest oczekiwany projekt SWD" >&2; exit 1; }
chown -R wallet:wallet /opt/Seed-Generator-Wallet-Decoder.new
chmod -R go-rwx /opt/Seed-Generator-Wallet-Decoder.new
runuser -u wallet -- /usr/local/bin/npm --prefix /opt/Seed-Generator-Wallet-Decoder.new run check
rm -rf /opt/Seed-Generator-Wallet-Decoder
mv /opt/Seed-Generator-Wallet-Decoder.new /opt/Seed-Generator-Wallet-Decoder
for wrapper in /opt/entropysilo/wrappers/swd-*; do install -m 0755 -o root -g root "$wrapper" "/usr/local/bin/$(basename "$wrapper")"; done
echo "SWD zainstalowany i sprawdzony offline."
