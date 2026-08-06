#!/bin/bash
set -Eeuo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
IMAGE=${1:-"$ROOT/output/EntropySilo-Pi2-Bookworm-0.3.0.img"}
COMPRESSED="${IMAGE}.xz"

[[ $EUID -eq 0 ]] || { echo "Uruchom jako root" >&2; exit 1; }
CHECKSUM="${COMPRESSED}.sha256"
[[ -f $IMAGE && -f $COMPRESSED && -f $CHECKSUM ]] || {
  echo "Brak obrazu, obrazu XZ albo pliku kontrolnego .sha256" >&2; exit 1;
}

(cd "$(dirname "$COMPRESSED")" && sha256sum -c "$(basename "$CHECKSUM")")
xz --test "$COMPRESSED"

loop=$(losetup --find --show --read-only --partscan "$IMAGE")
mount_root=$(mktemp -d)
cleanup() {
  set +e
  mountpoint -q "$mount_root/boot/firmware" && umount "$mount_root/boot/firmware"
  mountpoint -q "$mount_root/boot" && umount "$mount_root/boot"
  mountpoint -q "$mount_root" && umount "$mount_root"
  losetup -d "$loop" 2>/dev/null || true
  rmdir "$mount_root" 2>/dev/null || true
}
trap cleanup EXIT

mount -o ro "${loop}p2" "$mount_root"
if [[ -d "$mount_root/boot/firmware" ]]; then boot="$mount_root/boot/firmware"; else boot="$mount_root/boot"; fi
mount -o ro "${loop}p1" "$boot"

required=(
  "$boot/config.txt"
  "$boot/cmdline.txt"
  "$boot/overlays/waveshare35a.dtbo"
  "$mount_root/opt/entropysilo/apps/wallet_gui.py"
  "$mount_root/opt/entropysilo/apps/wait-hardware.sh"
  "$mount_root/opt/entropysilo/apps/wallet-cli.js"
  "$mount_root/opt/entropysilo/apps/bip85.js"
  "$mount_root/opt/entropysilo/apps/qr-decode.js"
  "$mount_root/opt/entropysilo/apps/entropysilo-privileged.py"
  "$mount_root/usr/local/sbin/entropysilo-usb"
  "$mount_root/etc/systemd/system/entropysilo-privileged.socket"
  "$mount_root/etc/systemd/system/entropysilo-privileged@.service"
  "$mount_root/opt/Seed-Generator-Wallet-Decoder/package.json"
  "$mount_root/etc/systemd/system/wallet-ui.service"
  "$mount_root/etc/systemd/system/network-lockdown.service"
  "$mount_root/etc/nftables.conf"
  "$mount_root/etc/modprobe.d/blacklist-wifi-bt.conf"
  "$mount_root/etc/udev/rules.d/99-entropysilo-network.rules"
)
for path in "${required[@]}"; do [[ -f $path ]] || { echo "Brak: $path" >&2; exit 1; }; done
[[ -x "$mount_root/opt/entropysilo/apps/wait-hardware.sh" ]]

grep -q '^dtoverlay=waveshare35a$' "$boot/config.txt"
! grep -q '^display_rotate=' "$boot/config.txt"
grep -q 'fbcon=map:10' "$boot/cmdline.txt"
grep -q '^IPAddressDeny=any' "$mount_root/etc/systemd/system/wallet-ui.service"
grep -q '^RestrictAddressFamilies=AF_UNIX' "$mount_root/etc/systemd/system/wallet-ui.service"
grep -q '^NoNewPrivileges=yes' "$mount_root/etc/systemd/system/wallet-ui.service"
grep -q '^Environment=ENTROPYSILO_DIRECT_FB=1' "$mount_root/etc/systemd/system/wallet-ui.service"
grep -q '^ExecStartPre=/opt/entropysilo/apps/wait-hardware.sh' "$mount_root/etc/systemd/system/wallet-ui.service"
! grep -q 'systemd-udev-settle' "$mount_root/etc/systemd/system/wallet-ui.service"
! grep -q '^Environment=SDL_FBDEV=' "$mount_root/etc/systemd/system/wallet-ui.service"
grep -q '/dev/fb0' "$mount_root/opt/entropysilo/apps/wait-hardware.sh"
grep -q 'candidate_bpp in (16, 24, 32)' "$mount_root/opt/entropysilo/apps/wallet_gui.py"
grep -q '^Environment=ENTROPYSILO_TOUCH_SWAP=1' "$mount_root/etc/systemd/system/wallet-ui.service"
grep -q '^Environment=ENTROPYSILO_TOUCH_INVERT_Y=1' "$mount_root/etc/systemd/system/wallet-ui.service"
grep -q '^class DirectFramebuffer:' "$mount_root/opt/entropysilo/apps/wallet_gui.py"
grep -q '^class LinuxInputBridge:' "$mount_root/opt/entropysilo/apps/wallet_gui.py"
grep -q '^def solve_touch_calibration' "$mount_root/opt/entropysilo/apps/wallet_gui.py"
grep -q 'ESC / ENTER = SKIP' "$mount_root/opt/entropysilo/apps/wallet_gui.py"
grep -q '^FONT_SIZE, SMALL_FONT_SIZE, LARGE_FONT_SIZE = 32, 24, 40$' "$mount_root/opt/entropysilo/apps/wallet_gui.py"
grep -q 'name == "KEY_CAPSLOCK"' "$mount_root/opt/entropysilo/apps/wallet_gui.py"
grep -q 'pressed = keys\[selected\]' "$mount_root/opt/entropysilo/apps/wallet_gui.py"
grep -q '^WIDTH, HEIGHT = 480, 320$' "$mount_root/opt/entropysilo/apps/wallet_gui.py"
grep -q 'DESCRIPTOR + FINGERPRINT (ZALECANY)' "$mount_root/opt/entropysilo/apps/wallet_gui.py"
grep -q 'WYBIERZ PORTFEL PODPISUJĄCY' "$mount_root/opt/entropysilo/apps/wallet_gui.py"
grep -q '^    def ask_hd_account' "$mount_root/opt/entropysilo/apps/wallet_gui.py"
grep -q 'fingerprintMissing = missingFingerprint' "$mount_root/opt/entropysilo/apps/wallet-core.js"
grep -q 'standardSigningPath(derivation.path, network, account)' "$mount_root/opt/entropysilo/apps/wallet-core.js"
grep -q '"version": "0.3.0"' "$mount_root/opt/entropysilo/package.json"
grep -q 'write-backup' "$mount_root/opt/entropysilo/apps/entropysilo-privileged.py"
grep -q 'noexec' "$mount_root/usr/local/sbin/entropysilo-usb"
[[ ! -e "$mount_root/etc/sudoers.d/entropysilo-power" ]]
[[ ! -e "$mount_root/usr/bin/sudo" ]]
[[ -x "$mount_root/usr/bin/v4l2-ctl" ]]
grep -q 'list-psbts' "$mount_root/opt/entropysilo/apps/entropysilo-privileged.py"
grep -q 'write-selected-signed-psbt' "$mount_root/usr/local/sbin/entropysilo-usb"
grep -q '^DirectoryMode=0755$' "$mount_root/etc/systemd/system/entropysilo-privileged.socket"
grep -q 'broker accessible' "$mount_root/opt/entropysilo/apps/wait-hardware.sh"
[[ -L "$mount_root/etc/systemd/system/sockets.target.wants/entropysilo-privileged.socket" ]]
[[ -d "$mount_root/opt/entropysilo/node_modules/jsqr" ]]
[[ -d "$mount_root/opt/entropysilo/node_modules/pngjs" ]]
[[ -d "$mount_root/opt/entropysilo/node_modules/jpeg-js" ]]
grep -q 'policy drop' "$mount_root/etc/nftables.conf"
[[ $(readlink "$mount_root/etc/systemd/system/ssh.service") == /dev/null ]]
[[ $(readlink "$mount_root/etc/systemd/system/NetworkManager.service") == /dev/null ]]
[[ $(readlink "$mount_root/etc/systemd/system/systemd-firstboot.service") == /dev/null ]]
[[ $(readlink "$mount_root/etc/systemd/system/userconfig.service") == /dev/null ]]
[[ $(readlink "$mount_root/etc/systemd/system/triggerhappy.socket") == /dev/null ]]
[[ $(readlink "$mount_root/etc/systemd/system/ModemManager.service") == /dev/null ]]
[[ $(readlink "$mount_root/etc/systemd/system/udisks2.service") == /dev/null ]]
[[ -z $(find "$mount_root/etc/systemd/system" -mindepth 2 -type l -name 'userconfig.service' -print -quit) ]]
[[ -L "$mount_root/etc/systemd/system/multi-user.target.wants/wallet-ui.service" ]]
[[ -L "$mount_root/etc/systemd/system/multi-user.target.wants/network-lockdown.service" ]]
[[ ! -e "$mount_root/usr/bin/qemu-arm-static" ]]
[[ -z $(find "$mount_root/var/lib/entropysilo/vaults" -mindepth 1 -maxdepth 1 -print -quit) ]]

node_version=$(qemu-arm-static -L "$mount_root" "$mount_root/opt/node-v22/bin/node" -v)
[[ $node_version == v22.23.1 ]]
echo "VALIDACJA OK: Node $node_version, LCD35A, GUI, blokada sieci, pusty skarbiec, SHA-256 i XZ."
