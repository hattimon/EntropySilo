#!/bin/bash
set -Eeuo pipefail
umask 022
[[ $EUID -eq 0 ]] || { echo "Uruchom jako root w Linux/WSL2" >&2; exit 1; }

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
ASSETS=${ASSETS:-"$ROOT/build/assets"}
OUTPUT=${OUTPUT:-"$ROOT/output"}
BASE_NAME=2025-05-13-raspios-bookworm-armhf-lite.img
BASE_URL="https://downloads.raspberrypi.com/raspios_lite_armhf/images/raspios_lite_armhf-2025-05-13/${BASE_NAME}.xz"
mkdir -p "$OUTPUT" "$ROOT/build"
for file in SHA256SUMS EntropySilo.tar.gz Seed-Generator-Wallet-Decoder.tar.gz LCD-show.tar.gz; do
  [[ -f "$ASSETS/$file" ]] || { echo "Brak $ASSETS/$file. Uruchom prepare_assets.sh" >&2; exit 1; }
done

if ! command -v qemu-arm-static >/dev/null || ! command -v parted >/dev/null; then
  apt-get update
  apt-get install -y qemu-user-static binfmt-support curl xz-utils parted e2fsprogs
fi
base_xz="$ROOT/build/${BASE_NAME}.xz"
base_img="$ROOT/build/${BASE_NAME}"
if [[ ! -f $base_xz ]]; then curl --fail --location --proto '=https' --tlsv1.2 "$BASE_URL" -o "$base_xz"; fi
if [[ ! -f ${base_xz}.sha256 ]]; then curl --fail --location --proto '=https' --tlsv1.2 "${BASE_URL}.sha256" -o "${base_xz}.sha256"; fi
(cd "$(dirname "$base_xz")" && sha256sum -c "$(basename "${base_xz}.sha256")")
rm -f "$base_img"
xz --decompress --keep --threads=0 "$base_xz"

# Obraz Lite jest celowo mały; provisioning potrzebuje miejsca na cache APT i paczki offline.
truncate -s 6G "$base_img"
parted -s "$base_img" resizepart 2 100%

loop=$(losetup --find --show --partscan "$base_img")
e2fsck -fy "${loop}p2"
resize2fs "${loop}p2"
root_mount=$(mktemp -d)
boot_mount=""
cleanup() {
  set +e
  mountpoint -q "$root_mount/dev" && umount -R -l "$root_mount/dev"
  mountpoint -q "$root_mount/proc" && umount -l "$root_mount/proc"
  mountpoint -q "$root_mount/sys" && umount -R -l "$root_mount/sys"
  [[ -n $boot_mount ]] && mountpoint -q "$boot_mount" && umount -l "$boot_mount"
  mountpoint -q "$root_mount" && umount -l "$root_mount"
  losetup -d "$loop" 2>/dev/null || true
  if ! mountpoint -q "$root_mount"; then rm -rf "$root_mount"; fi
}
trap cleanup EXIT
mount "${loop}p2" "$root_mount"
if [[ -d "$root_mount/boot/firmware" ]]; then
  boot_mount="$root_mount/boot/firmware"
else
  boot_mount="$root_mount/boot"
fi
mount "${loop}p1" "$boot_mount"

mkdir -p "$root_mount/opt/assets" "$root_mount/opt/entropysilo" "$root_mount/root"
cp -a "$ASSETS/." "$root_mount/opt/assets/"
tar -xzf "$ASSETS/EntropySilo.tar.gz" --strip-components=1 -C "$root_mount/opt/entropysilo"
install -m 0755 "$ROOT/image-builder/provision_image.sh" "$root_mount/root/provision-entropysilo.sh"
install -m 0755 "$(command -v qemu-arm-static)" "$root_mount/usr/bin/qemu-arm-static"
cp -L /etc/resolv.conf "$root_mount/etc/resolv.conf"
mount -t proc proc "$root_mount/proc"
mount --rbind /sys "$root_mount/sys"
mount --rbind /dev "$root_mount/dev"

chroot "$root_mount" /usr/bin/qemu-arm-static /bin/bash /root/provision-entropysilo.sh
rm -f "$root_mount/usr/bin/qemu-arm-static" "$root_mount/root/provision-entropysilo.sh"
rm -rf "$root_mount/opt/assets"
sync
cleanup
trap - EXIT

final_img="$OUTPUT/EntropySilo-Pi2-Bookworm-0.3.0.img"
mv "$base_img" "$final_img"
"$ROOT/image-builder/test_image_touch.sh" "$final_img"
compressed="${final_img}.xz"
rm -f -- "$compressed" "${compressed}.sha256" "${compressed}.txt"
xz --threads=0 --compress --keep -9 "$final_img"
(cd "$OUTPUT" && sha256sum "$(basename "$compressed")" >"$(basename "$compressed").sha256")
"$ROOT/image-builder/validate_image.sh" "$final_img"
cat >"${compressed}.txt" <<'EOF'
EntropySilo Raspberry Pi 2 image 0.3.0
Target: Raspberry Pi 2 Model B (ARMv7, 32-bit)
Display: Waveshare 3.5inch RPi LCD (A), 480x320 landscape
Input: resistive touch plus USB keyboard
USB exchange directory: /EntropySilo
Application paths: /opt/entropysilo, /var/lib/entropysilo, /run/entropysilo
Network: disabled by udev, nftables, module blacklist and service policy
Validation: application tests, image structure, touch/navigation self-tests and SHA-256
Hardware status: physical recheck of this exact 0.3.0 image is required before substantial funds
Legacy image RPiWallet-Pi2-Bookworm-0.2.3.img.xz was not modified.
EOF
echo "GOTOWY OBRAZ: ${final_img}.xz"
