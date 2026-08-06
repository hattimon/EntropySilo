#!/bin/bash
set -Eeuo pipefail
IMAGE=${1:?Podaj obraz IMG}
[[ $EUID -eq 0 && -f $IMAGE ]] || exit 1
loop=$(losetup --find --show --read-only --partscan "$IMAGE")
mount_root=$(mktemp -d)
cleanup() {
  set +e
  mountpoint -q "$mount_root" && umount "$mount_root"
  losetup -d "$loop" 2>/dev/null || true
  rmdir "$mount_root" 2>/dev/null || true
}
trap cleanup EXIT
mount -o ro "${loop}p2" "$mount_root"
echo "--- enabled/masked units ---"
find "$mount_root/etc/systemd/system" -maxdepth 3 -type l -printf '%P -> %l\n' \
  | grep -Ei 'first|userconf|userconfig|ssh|wallet|network' || true
echo "--- installed candidate units ---"
find "$mount_root/lib/systemd/system" -maxdepth 1 -type f -printf '%f\n' \
  | grep -Ei 'first|userconf|userconfig|raspi' || true
echo "--- textual prompt owners ---"
grep -RIl --binary-files=without-match 'Enter new username' "$mount_root/usr" "$mount_root/lib" 2>/dev/null \
  | sed "s#^$mount_root##" | head -20 || true
