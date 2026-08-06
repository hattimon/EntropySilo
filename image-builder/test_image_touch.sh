#!/bin/bash
set -Eeuo pipefail

[[ $EUID -eq 0 ]] || { echo "Uruchom jako root" >&2; exit 1; }
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
IMAGE=${1:-"$ROOT/output/EntropySilo-Pi2-Bookworm-0.3.0.img"}
[[ -f $IMAGE ]] || { echo "Brak obrazu: $IMAGE" >&2; exit 1; }

loop=$(losetup --find --show --read-only --partscan "$IMAGE")
lower=$(mktemp -d)
upper=$(mktemp -d)
work=$(mktemp -d)
merged=$(mktemp -d)
cleanup() {
  set +e
  mountpoint -q "$merged/mnt/project" && umount "$merged/mnt/project"
  mountpoint -q "$merged" && umount "$merged"
  mountpoint -q "$lower" && umount "$lower"
  losetup -d "$loop" 2>/dev/null || true
  rm -rf -- "$lower" "$upper" "$work" "$merged"
}
trap cleanup EXIT

mount -o ro "${loop}p2" "$lower"
mount -t overlay overlay -o "lowerdir=$lower,upperdir=$upper,workdir=$work" "$merged"
install -m 0755 "$(command -v qemu-arm-static)" "$merged/usr/bin/qemu-arm-static"
mkdir -p "$merged/mnt/project"
mount --bind "$ROOT" "$merged/mnt/project"
chroot "$merged" /usr/bin/qemu-arm-static /usr/bin/python3 \
  /opt/entropysilo/apps/wallet_gui.py --self-test-touch
chroot "$merged" /usr/bin/env ENTROPYSILO_TEST_APP_DIR=/opt/entropysilo/apps \
  /usr/bin/qemu-arm-static /usr/bin/python3 /mnt/project/scripts/test_gui_navigation.py
