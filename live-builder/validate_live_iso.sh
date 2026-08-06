#!/bin/bash
set -Eeuo pipefail

ISO=${1:?Podaj plik ISO}
[[ -f $ISO && -s $ISO ]] || { echo "Brak lub pusty plik ISO: $ISO" >&2; exit 1; }
CHECKSUM="${ISO}.sha256"
[[ -f $CHECKSUM ]] || { echo "Brak pliku kontrolnego: $CHECKSUM" >&2; exit 1; }
(cd "$(dirname "$ISO")" && sha256sum -c "$(basename "$CHECKSUM")")
command -v xorriso >/dev/null || { echo "Brak xorriso." >&2; exit 1; }
command -v unsquashfs >/dev/null || { echo "Brak unsquashfs." >&2; exit 1; }
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
xorriso -indev "$ISO" -report_el_torito plain >"$work/el-torito.txt" 2>&1
grep -qi 'BIOS' "$work/el-torito.txt"
grep -qi 'UEFI' "$work/el-torito.txt"
xorriso -osirrox on -indev "$ISO" -extract /EFI/boot/bootx64.efi "$work/bootx64.efi" >/dev/null 2>&1
[[ -s $work/bootx64.efi ]]
xorriso -osirrox on -indev "$ISO" -extract /live/filesystem.squashfs "$work/filesystem.squashfs" >/dev/null 2>&1
for path in \
  opt/entropysilo/apps/wallet_gui.py \
  opt/entropysilo/apps/wallet-cli.js \
  opt/Seed-Generator-Wallet-Decoder/package.json \
  etc/systemd/system/wallet-ui-live.service \
  etc/systemd/system/xserver-entropysilo.service \
  etc/systemd/system/entropysilo-privileged.socket \
  usr/local/sbin/entropysilo-usb \
  usr/lib/xorg/Xorg \
  usr/local/bin/node; do
  unsquashfs -ll "$work/filesystem.squashfs" "$path" | grep -Fq "squashfs-root/$path"
done
for link in \
  etc/systemd/system/multi-user.target.wants/network-lockdown.service \
  etc/systemd/system/multi-user.target.wants/xserver-entropysilo.service \
  etc/systemd/system/multi-user.target.wants/wallet-ui-live.service \
  etc/systemd/system/sockets.target.wants/entropysilo-privileged.socket; do
  unsquashfs -ll "$work/filesystem.squashfs" "$link" | grep -Fq "squashfs-root/$link"
done
unsquashfs -cat "$work/filesystem.squashfs" etc/nftables.conf | grep -Fq 'policy drop'
unsquashfs -cat "$work/filesystem.squashfs" etc/udev/rules.d/99-entropysilo-network.rules | grep -Fq 'SUBSYSTEM=="net"'
if unsquashfs -ll "$work/filesystem.squashfs" usr/bin/sudo | grep -Fq 'squashfs-root/usr/bin/sudo'; then
  echo "Niedozwolony program sudo jest obecny w obrazie." >&2
  exit 1
fi
echo "LIVE_ISO_STRUCTURE_OK"
