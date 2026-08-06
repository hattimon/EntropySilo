#!/bin/bash
set -Eeuo pipefail
umask 022

[[ $EUID -eq 0 ]] || { echo "Uruchom jako root." >&2; exit 1; }
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
VERSION=${ENTROPYSILO_LIVE_VERSION:-0.3.0}
WORK=${ENTROPYSILO_LIVE_WORK:-/tmp/entropy-silo-live-build}
OUT="$ROOT/output"
ISO_NAME="EntropySilo-Live-x86_64-${VERSION}.iso"
case $WORK in /tmp/entropy-silo-live-*) ;; *) echo "Katalog roboczy musi być bezpieczną ścieżką /tmp/entropy-silo-live-*" >&2; exit 1;; esac
command -v lb >/dev/null || { echo "Brak live-build. Zainstaluj: apt-get install live-build" >&2; exit 1; }

rm -rf -- "$WORK"
install -d -m 0755 "$WORK" "$OUT"
"$ROOT/live-builder/prepare_live_assets.sh" "$WORK/assets"
cd "$WORK"
lb config \
  --mode debian \
  --distribution bookworm \
  --architecture amd64 \
  --archive-areas 'main contrib non-free-firmware' \
  --binary-image iso-hybrid \
  --bootloaders 'syslinux,grub-efi' \
  --uefi-secure-boot enable \
  --debian-installer none \
  --apt-recommends false \
  --memtest none \
  --iso-application 'EntropySilo Offline Bitcoin Workstation' \
  --iso-publisher 'hattimon/EntropySilo' \
  --iso-volume 'ENTROPYSILO' \
  --bootappend-live 'boot=live components quiet loglevel=3 systemd.show_status=auto rd.systemd.show_status=auto ip=none noeject'

install -d config/package-lists config/includes.chroot/opt/assets config/includes.chroot/opt/live-bootstrap config/hooks/normal
install -m 0644 "$ROOT/live-builder/packages.list.chroot" config/package-lists/entropy-silo.list.chroot
cp -a "$WORK/assets/." config/includes.chroot/opt/assets/
install -m 0755 "$ROOT/live-builder/provision_live.sh" config/includes.chroot/opt/live-bootstrap/provision_live.sh
cat >config/hooks/normal/0100-entropy-silo.hook.chroot <<'EOF'
#!/bin/sh
set -eu
expected=$(awk '$2 == "EntropySilo-runtime.tar.gz" {print $1}' /opt/assets/SHA256SUMS)
actual=$(sha256sum /opt/assets/EntropySilo-runtime.tar.gz | awk '{print $1}')
[ -n "$expected" ] && [ "$actual" = "$expected" ]
tar -xzf /opt/assets/EntropySilo-runtime.tar.gz --no-same-owner -C /opt
/opt/live-bootstrap/provision_live.sh
rm -rf /opt/live-bootstrap /opt/assets/EntropySilo-runtime.tar.gz
EOF
chmod 0755 config/hooks/normal/0100-entropy-silo.hook.chroot

lb build
[[ -f live-image-amd64.hybrid.iso ]] || { echo "live-build nie utworzył ISO." >&2; exit 1; }
install -m 0644 live-image-amd64.hybrid.iso "$OUT/$ISO_NAME"
(cd "$OUT" && sha256sum "$ISO_NAME" >"$ISO_NAME.sha256")
cat >"$OUT/$ISO_NAME.txt" <<EOF
EntropySilo Live USB ${VERSION}
Architecture: x86-64 (amd64 laptops/PCs)
Boot: BIOS and UEFI hybrid ISO
Network: disabled by udev, nftables and service policy
Vault storage: ephemeral Live overlay in RAM; erased at shutdown
Exchange media: a separate FAT32/exFAT USB with /EntropySilo
Validation: deterministic application tests, ISO structure and SHA-256
Hardware status: physical laptop/camera/touch matrix still requires real-device confirmation
The Raspberry Pi 2 image was not modified by this build.
EOF
"$ROOT/live-builder/validate_live_iso.sh" "$OUT/$ISO_NAME"
echo "Gotowe: $OUT/$ISO_NAME"
