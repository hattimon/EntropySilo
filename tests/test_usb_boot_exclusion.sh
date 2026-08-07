#!/bin/bash
set -Eeuo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

cat >"$work/findmnt" <<'EOF'
#!/bin/sh
last=
for value do last=$value; done
case "$last" in
  /) printf 'overlay\n';;
  /run/live/medium) printf '/dev/sda1\n';;
esac
EOF
cat >"$work/lsblk" <<'EOF'
#!/bin/sh
case "$*" in
  *"-s -nro NAME /dev/sda1"*) printf 'sda1\nsda\n'; exit 0;;
  *"-dnro RM /dev/sda"*) printf '1\n'; exit 0;;
  *"-dnro RM /dev/sdb"*) printf '0\n'; exit 0;;
  *"-dnro TRAN /dev/sda"*) printf 'usb\n'; exit 0;;
  *"-dnro TRAN /dev/sdb"*) printf 'usb\n'; exit 0;;
esac
last=
for value do last=$value; done
if [ "$last" = "NAME,TYPE,FSTYPE,RM" ]; then
  printf 'sda1 part vfat 1\nsdb1 part exfat 0\n'
elif [ "$last" = /dev/sda1 ]; then
  printf 'sda\n'
elif [ "$last" = /dev/sdb1 ]; then
  printf 'sdb\n'
fi
EOF
chmod 0755 "$work/findmnt" "$work/lsblk"

PATH="$work:$PATH"
ENTROPYSILO_USB_LIBRARY_ONLY=1
ENTROPYSILO_USB_MOUNT_DIR="$work/mount"
ENTROPYSILO_USB_WALLET_UID=$(id -u)
ENTROPYSILO_USB_WALLET_GID=$(id -g)
export PATH ENTROPYSILO_USB_LIBRARY_ONLY ENTROPYSILO_USB_MOUNT_DIR ENTROPYSILO_USB_WALLET_UID ENTROPYSILO_USB_WALLET_GID
source "$ROOT/apps/entropysilo-usb"

[[ $(find_usb_partition) == /dev/sdb1:exfat ]]
mkdir -p "$ENTROPYSILO_USB_MOUNT_DIR/RPiWallet"
touch "$ENTROPYSILO_USB_MOUNT_DIR/RPiWallet/backup.rpwb"
[[ $(backup_directory) == RPiWallet ]]
mkdir -p "$ENTROPYSILO_USB_MOUNT_DIR/EntropySilo"
touch "$ENTROPYSILO_USB_MOUNT_DIR/EntropySilo/backup1.eswb"
[[ $(backup_directory) == EntropySilo ]]
echo "USB_BOOT_MEDIA_EXCLUSION_OK"
