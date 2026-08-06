#!/bin/bash
set -Eeuo pipefail
umask 022
[[ $EUID -eq 0 ]] || { echo "Uruchom jako root: sudo $0" >&2; exit 1; }
archive=/opt/assets/LCD-show.tar.gz
[[ -f $archive ]] || { echo "Brak $archive" >&2; exit 1; }
[[ -f /opt/assets/SHA256SUMS ]] || { echo "Brak SHA256SUMS" >&2; exit 1; }
expected=$(awk -v name="$(basename "$archive")" '$2 == name {print $1}' /opt/assets/SHA256SUMS)
actual=$(sha256sum "$archive" | awk '{print $1}')
[[ $expected =~ ^[0-9a-fA-F]{64}$ && $actual == "$expected" ]] || { echo "Błędny SHA-256 LCD-show" >&2; exit 1; }

rm -rf /opt/LCD-show.new
install -d -m 0755 /opt/LCD-show.new
tar -xzf "$archive" --strip-components=1 --no-same-owner -C /opt/LCD-show.new
[[ -f /opt/LCD-show.new/waveshare35a-overlay.dtb ]] || { echo "Brak overlay waveshare35a" >&2; exit 1; }
rm -rf /opt/LCD-show
mv /opt/LCD-show.new /opt/LCD-show

boot=/boot
[[ -d /boot/firmware/overlays ]] && boot=/boot/firmware
install -m 0644 /opt/LCD-show/waveshare35a-overlay.dtb "$boot/overlays/waveshare35a.dtbo"
config="$boot/config.txt"
if ! grep -q '^# BEGIN ENTROPYSILO LCD35A$' "$config"; then
  printf '\n' >> "$config"
  cat /opt/entropysilo/config/config-txt-snippet.txt >> "$config"
fi
cmdline="$boot/cmdline.txt"
grep -qw 'fbcon=map:10' "$cmdline" || sed -i '1 s/$/ fbcon=map:10 fbcon=font:ProFont6x11/' "$cmdline"
install -m 0644 /opt/entropysilo/config/99-waveshare-touch.rules /etc/udev/rules.d/99-waveshare-touch.rules
udevadm control --reload-rules
echo "LCD skonfigurowany bez uruchamiania skryptu producenta, który nadpisuje całe config.txt. Uruchom ponownie Pi."
