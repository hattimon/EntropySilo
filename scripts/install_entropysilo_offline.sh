#!/bin/bash
set -Eeuo pipefail
umask 022
[[ $EUID -eq 0 ]] || { echo "Uruchom jako root: sudo $0" >&2; exit 1; }
archive=/opt/assets/EntropySilo.tar.gz
[[ -f $archive && -f /opt/assets/SHA256SUMS ]] || { echo "Brak paczki lub SHA256SUMS" >&2; exit 1; }
expected=$(awk -v name="$(basename "$archive")" '$2 == name {print $1}' /opt/assets/SHA256SUMS)
actual=$(sha256sum "$archive" | awk '{print $1}')
[[ $expected =~ ^[0-9a-fA-F]{64}$ && $actual == "$expected" ]] || { echo "Błędny SHA-256 EntropySilo" >&2; exit 1; }
rm -rf /opt/entropysilo.new
install -d -m 0755 /opt/entropysilo.new
tar -xzf "$archive" --strip-components=1 --no-same-owner -C /opt/entropysilo.new
[[ -d /opt/entropysilo.new/node_modules ]] || { echo "Brak node_modules w paczce" >&2; exit 1; }
/usr/local/bin/npm --prefix /opt/entropysilo.new test
rm -rf /opt/entropysilo
mv /opt/entropysilo.new /opt/entropysilo
chown -R root:root /opt/entropysilo
chmod -R go-w /opt/entropysilo
install -d -m 0700 -o wallet -g wallet /var/lib/entropysilo/vaults
install -m 0644 /opt/entropysilo/systemd/wallet-ui.service /etc/systemd/system/wallet-ui.service
install -m 0644 /opt/entropysilo/systemd/network-lockdown.service /etc/systemd/system/network-lockdown.service
install -m 0644 /opt/entropysilo/systemd/entropysilo-privileged.socket /etc/systemd/system/entropysilo-privileged.socket
install -m 0644 /opt/entropysilo/systemd/entropysilo-privileged@.service /etc/systemd/system/entropysilo-privileged@.service
install -m 0755 /opt/entropysilo/apps/entropysilo-usb /usr/local/sbin/entropysilo-usb
rm -f /etc/sudoers.d/entropysilo-power
if [[ -d /run/systemd/system ]]; then systemctl daemon-reload; fi
systemctl enable wallet-ui.service network-lockdown.service entropysilo-privileged.socket
echo "EntropySilo zainstalowany."
