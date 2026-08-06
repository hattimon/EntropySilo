#!/bin/bash
set -Eeuo pipefail
umask 022
[[ $EUID -eq 0 ]] || { echo "Uruchom jako root" >&2; exit 1; }

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
SOURCE_IMAGE=${1:-"$ROOT/output/EntropySilo-Pi2-Bookworm-0.3.0.img"}
IMAGE=${2:-"$ROOT/output/EntropySilo-Pi2-Bookworm-0.3.1.img"}
COMPRESSED="$IMAGE.xz"
[[ -f $SOURCE_IMAGE ]] || { echo "Brak obrazu bazowego: $SOURCE_IMAGE" >&2; exit 1; }
if [[ ! -f $IMAGE ]]; then cp --reflink=auto --sparse=always "$SOURCE_IMAGE" "$IMAGE"; fi

loop=$(losetup --find --show --partscan "$IMAGE")
mount_root=$(mktemp -d)
boot_mount=""
cleanup() {
  set +e
  [[ -n $boot_mount ]] && mountpoint -q "$boot_mount" && umount "$boot_mount"
  mountpoint -q "$mount_root" && umount "$mount_root"
  losetup -d "$loop" 2>/dev/null || true
  rmdir "$mount_root" 2>/dev/null || true
}
trap cleanup EXIT
mount "${loop}p2" "$mount_root"
if [[ -d "$mount_root/boot/firmware" ]]; then boot_mount="$mount_root/boot/firmware"; else boot_mount="$mount_root/boot"; fi
mount "${loop}p1" "$boot_mount"
for app in wallet_gui.py entropysilo-privileged.py wait-hardware.sh wallet-cli.js wallet-core.js card-entropy.js qr-decode.js; do
  install -m 0755 -o root -g root "$ROOT/apps/$app" "$mount_root/opt/entropysilo/apps/$app"
done
install -m 0755 -o root -g root "$ROOT/apps/entropysilo-usb" "$mount_root/usr/local/sbin/entropysilo-usb"
rm -f "$mount_root/etc/sudoers.d/entropysilo-power"
install -m 0644 -o root -g root "$ROOT/systemd/wallet-ui.service" "$mount_root/etc/systemd/system/wallet-ui.service"
install -m 0644 -o root -g root "$ROOT/systemd/entropysilo-privileged.socket" "$mount_root/etc/systemd/system/entropysilo-privileged.socket"
install -m 0644 -o root -g root "$ROOT/systemd/entropysilo-privileged@.service" "$mount_root/etc/systemd/system/entropysilo-privileged@.service"
install -d -m 0755 "$mount_root/etc/systemd/system/sockets.target.wants"
ln -sfn ../entropysilo-privileged.socket "$mount_root/etc/systemd/system/sockets.target.wants/entropysilo-privileged.socket"
install -m 0644 -o root -g root "$ROOT/package.json" "$mount_root/opt/entropysilo/package.json"
install -m 0644 -o root -g root "$ROOT/package-lock.json" "$mount_root/opt/entropysilo/package-lock.json"
for module in jsqr pngjs jpeg-js; do
  rm -rf "$mount_root/opt/entropysilo/node_modules/$module"
  cp -a "$ROOT/node_modules/$module" "$mount_root/opt/entropysilo/node_modules/$module"
  chown -R root:root "$mount_root/opt/entropysilo/node_modules/$module"
  chmod -R go-w "$mount_root/opt/entropysilo/node_modules/$module"
done
sed -i 's/^dtoverlay=waveshare35a:rotate=0$/dtoverlay=waveshare35a/' "$boot_mount/config.txt"
sed -i '/^display_rotate=1$/d' "$boot_mount/config.txt"
for unit in systemd-firstboot.service userconfig.service userconf.service sshswitch.service \
  regenerate_ssh_host_keys.service triggerhappy.service triggerhappy.socket ModemManager.service \
  udisks2.service systemd-timesyncd.service; do
  find "$mount_root/etc/systemd/system" -mindepth 2 -type l -name "$unit" -delete
  ln -sfn /dev/null "$mount_root/etc/systemd/system/$unit"
done
rm -rf "$mount_root/opt/entropysilo/apps/__pycache__"
sync
cleanup
trap - EXIT

# Cel jest stały i zweryfikowany powyżej; surowy obraz pozostaje kopią odzyskiwalną.
rm -f "$COMPRESSED" "$ROOT/output/SHA256SUMS"
xz --threads=0 --compress --keep -9 "$IMAGE"
(cd "$ROOT/output" && sha256sum "$(basename "$COMPRESSED")" > SHA256SUMS)
echo "Odświeżono GUI i sumę obrazu: $COMPRESSED"
