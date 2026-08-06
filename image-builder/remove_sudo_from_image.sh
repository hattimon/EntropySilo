#!/bin/bash
set -Eeuo pipefail
umask 022

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
IMAGE=${1:-"$ROOT/output/EntropySilo-Pi2-Bookworm-0.3.0.img"}
COMPRESSED="${IMAGE}.xz"
[[ $EUID -eq 0 ]] || { echo "Uruchom jako root" >&2; exit 1; }
[[ -f $IMAGE && $(basename "$IMAGE") == EntropySilo-Pi2-Bookworm-0.3.0.img ]] || {
  echo "Brak oczekiwanego obrazu EntropySilo 0.3.0" >&2; exit 1;
}

loop=$(losetup --find --show --partscan "$IMAGE")
mount_root=$(mktemp -d)
qemu_installed=0
cleanup() {
  set +e
  mountpoint -q "$mount_root/dev" && umount -R -l "$mount_root/dev"
  mountpoint -q "$mount_root/proc" && umount -l "$mount_root/proc"
  mountpoint -q "$mount_root/sys" && umount -R -l "$mount_root/sys"
  mountpoint -q "$mount_root" && umount -l "$mount_root"
  losetup -d "$loop" 2>/dev/null || true
  rmdir "$mount_root" 2>/dev/null || true
}
trap cleanup EXIT

mount "${loop}p2" "$mount_root"
[[ -f "$mount_root/opt/entropysilo/package.json" ]] || { echo "To nie jest obraz EntropySilo" >&2; exit 1; }
install -m 0755 "$(command -v qemu-arm-static)" "$mount_root/usr/bin/qemu-arm-static"
qemu_installed=1
mount -t proc proc "$mount_root/proc"
mount --rbind /sys "$mount_root/sys"
mount --rbind /dev "$mount_root/dev"
chroot "$mount_root" /usr/bin/qemu-arm-static /usr/bin/env SUDO_FORCE_REMOVE=yes /usr/bin/apt-get purge -y raspi-config sudo
chroot "$mount_root" /usr/bin/qemu-arm-static /usr/bin/apt-get clean
rm -f "$mount_root/usr/bin/qemu-arm-static"
qemu_installed=0
sync
cleanup
trap - EXIT

# Recompression intentionally replaces only the validated EntropySilo 0.3.0 artifact.
rm -f "$COMPRESSED" "${COMPRESSED}.sha256"
xz --threads=0 --compress --keep -9 "$IMAGE"
(cd "$ROOT/output" && sha256sum "$(basename "$COMPRESSED")" >"$(basename "$COMPRESSED").sha256")
"$ROOT/image-builder/validate_image.sh" "$IMAGE"
echo "Usunięto raspi-config/sudo i odtworzono: $COMPRESSED"
