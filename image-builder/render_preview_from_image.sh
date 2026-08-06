#!/bin/bash
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo "Uruchom jako root" >&2; exit 1; }
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
IMAGE="$ROOT/output/EntropySilo-Pi2-Bookworm-0.3.0.img"
[[ -f $IMAGE ]] || exit 1

loop=$(losetup --find --show --read-only --partscan "$IMAGE")
lower=$(mktemp -d); upper=$(mktemp -d); work=$(mktemp -d); merged=$(mktemp -d)
cleanup() {
  set +e
  mountpoint -q "$merged/mnt/project" && umount "$merged/mnt/project"
  mountpoint -q "$merged" && umount "$merged"
  mountpoint -q "$lower" && umount "$lower"
  losetup -d "$loop" 2>/dev/null || true
  rm -rf "$lower" "$upper" "$work" "$merged"
}
trap cleanup EXIT
mount -o ro "${loop}p2" "$lower"
mount -t overlay overlay -o "lowerdir=$lower,upperdir=$upper,workdir=$work" "$merged"
install -m 0755 "$(command -v qemu-arm-static)" "$merged/usr/bin/qemu-arm-static"
mkdir -p "$merged/mnt/project"
mount --bind "$ROOT" "$merged/mnt/project"
chroot "$merged" /usr/bin/qemu-arm-static /usr/bin/python3 /mnt/project/scripts/render_gui_preview.py
chroot "$merged" /usr/bin/qemu-arm-static /usr/bin/python3 /mnt/project/scripts/test_gui_navigation.py
