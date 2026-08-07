#!/bin/bash
set -Eeuo pipefail
umask 027

PROJECT=/opt/entropysilo
ASSETS=/opt/assets
[[ $EUID -eq 0 && -d $PROJECT && -f $ASSETS/SHA256SUMS ]] || { echo "Nieprawidłowe środowisko instalatora Live." >&2; exit 1; }
(cd "$ASSETS" && sha256sum -c SHA256SUMS)

if ! id wallet >/dev/null 2>&1; then
  useradd --system --create-home --home-dir /var/lib/entropysilo --shell /usr/sbin/nologin wallet
fi
for group in video input render; do getent group "$group" >/dev/null && usermod -a -G "$group" wallet; done
passwd -l wallet >/dev/null 2>&1 || true
install -d -m 0700 -o wallet -g wallet /var/lib/entropysilo /var/lib/entropysilo/vaults
chown -R root:root "$PROJECT"
find "$PROJECT" -type d -exec chmod 0755 {} +
find "$PROJECT" -type f -exec chmod 0644 {} +
chmod 0755 "$PROJECT"/apps/*.py "$PROJECT"/apps/*.js "$PROJECT"/apps/*.sh \
  "$PROJECT"/scripts/*.sh "$PROJECT"/wrappers/*

"$PROJECT/scripts/install_node_offline.sh"
"$PROJECT/scripts/install_swd_offline.sh"
/usr/local/bin/npm --prefix "$PROJECT" test
python3 -m py_compile "$PROJECT/apps/wallet_gui.py" "$PROJECT/apps/entropysilo-privileged.py"
python3 "$PROJECT/tests/test_touch_calibration.py"
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy python3 "$PROJECT/scripts/test_gui_navigation.py"

install -m 0755 "$PROJECT/apps/entropysilo-usb" /usr/local/sbin/entropysilo-usb
install -m 0644 "$PROJECT/systemd/entropysilo-privileged.socket" /etc/systemd/system/
install -m 0644 "$PROJECT/systemd/entropysilo-privileged@.service" /etc/systemd/system/
install -m 0644 "$PROJECT/systemd/network-lockdown.service" /etc/systemd/system/
install -m 0644 "$PROJECT/systemd/xserver-entropysilo.service" /etc/systemd/system/
install -m 0644 "$PROJECT/systemd/wallet-ui-live.service" /etc/systemd/system/

install -m 0644 "$PROJECT/config/blacklist-wifi-bt.conf" /etc/modprobe.d/blacklist-wifi-bt.conf
install -m 0644 "$PROJECT/config/99-entropysilo-network.rules" /etc/udev/rules.d/99-entropysilo-network.rules
install -m 0644 "$PROJECT/config/99-entropysilo-sysctl.conf" /etc/sysctl.d/99-entropysilo.conf
install -d -m 0755 /etc/systemd/journald.conf.d
install -m 0644 "$PROJECT/config/entropysilo-journald-volatile.conf" /etc/systemd/journald.conf.d/99-entropysilo.conf
install -m 0755 "$PROJECT/config/nftables.conf" /etc/nftables.conf

for unit in ssh.service ssh.socket NetworkManager.service NetworkManager-wait-online.service \
  networking.service wpa_supplicant.service avahi-daemon.service avahi-daemon.socket \
  bluetooth.service ModemManager.service udisks2.service systemd-timesyncd.service \
  getty@tty1.service; do
  systemctl disable "$unit" >/dev/null 2>&1 || true
  systemctl mask "$unit" >/dev/null 2>&1 || true
done
systemctl enable nftables.service network-lockdown.service entropysilo-privileged.socket \
  xserver-entropysilo.service wallet-ui-live.service

grep -q '^tmpfs /tmp ' /etc/fstab || printf 'tmpfs /tmp tmpfs rw,nosuid,nodev,noexec,mode=1777,size=25%% 0 0\n' >> /etc/fstab
grep -q '^tmpfs /var/tmp ' /etc/fstab || printf 'tmpfs /var/tmp tmpfs rw,nosuid,nodev,noexec,mode=1777,size=64M 0 0\n' >> /etc/fstab
cat >/etc/security/limits.d/99-entropysilo.conf <<'EOF'
wallet hard core 0
wallet soft core 0
EOF
cat >/etc/profile.d/entropysilo-no-history.sh <<'EOF'
if [ "${USER:-}" = wallet ]; then unset HISTFILE; export HISTSIZE=0 SAVEHIST=0; fi
EOF
chmod 0644 /etc/profile.d/entropysilo-no-history.sh
printf 'entropy-silo-live\n' >/etc/hostname
printf '127.0.0.1 localhost\n127.0.1.1 entropy-silo-live\n::1 localhost ip6-localhost ip6-loopback\n' >/etc/hosts
rm -f /etc/ssh/ssh_host_* /root/.bash_history
echo "EntropySilo Live provisioned. Vault data lives only in the non-persistent Live overlay."
