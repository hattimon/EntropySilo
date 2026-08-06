#!/bin/bash
set -Eeuo pipefail
umask 027
[[ $EUID -eq 0 ]] || { echo "Uruchom jako root: sudo $0" >&2; exit 1; }
export DEBIAN_FRONTEND=noninteractive

apt-get update
APT_DPKG_OPTIONS=(
  -o Dpkg::Options::="--force-confdef"
  -o Dpkg::Options::="--force-confold"
)
apt-get "${APT_DPKG_OPTIONS[@]}" -y full-upgrade
apt-get "${APT_DPKG_OPTIONS[@]}" install -y --no-install-recommends python3 python3-pygame python3-evdev python3-pil \
  qrencode fbset fbi nftables iproute2 xz-utils ca-certificates git evtest v4l-utils
apt-get "${APT_DPKG_OPTIONS[@]}" install -y --no-install-recommends exfatprogs
apt-get clean

if ! id wallet >/dev/null 2>&1; then
  useradd --system --create-home --home-dir /var/lib/entropysilo --shell /usr/sbin/nologin wallet
fi
usermod -a -G video,input,render wallet
passwd -l wallet >/dev/null 2>&1 || true

for unit in ssh.service ssh.socket sshswitch.service regenerate_ssh_host_keys.service \
  systemd-firstboot.service userconfig.service userconf.service dhcpcd.service \
  NetworkManager.service NetworkManager-wait-online.service avahi-daemon.service avahi-daemon.socket \
  wpa_supplicant.service hciuart.service bluetooth.service triggerhappy.service triggerhappy.socket \
  ModemManager.service udisks2.service systemd-timesyncd.service; do
  systemctl disable --now "$unit" >/dev/null 2>&1 || true
  systemctl mask "$unit" >/dev/null 2>&1 || true
done
systemctl disable --now dphys-swapfile.service >/dev/null 2>&1 || true
swapoff -a
sed -ri '/^[^#].*\sswap\s/s/^/# ENTROPYSILO disabled: /' /etc/fstab

install -m 0644 /opt/entropysilo/config/blacklist-wifi-bt.conf /etc/modprobe.d/blacklist-wifi-bt.conf
install -m 0644 /opt/entropysilo/config/99-entropysilo-network.rules /etc/udev/rules.d/99-entropysilo-network.rules
install -m 0644 /opt/entropysilo/config/99-entropysilo-sysctl.conf /etc/sysctl.d/99-entropysilo.conf
install -d -m 0755 /etc/systemd/journald.conf.d
install -m 0644 /opt/entropysilo/config/entropysilo-journald-volatile.conf /etc/systemd/journald.conf.d/99-entropysilo.conf
install -m 0755 /opt/entropysilo/config/nftables.conf /etc/nftables.conf
if [[ -d /run/systemd/system ]]; then sysctl --system; fi
systemctl enable nftables.service
if [[ -d /run/systemd/system ]]; then systemctl start nftables.service; fi

grep -q '^tmpfs /tmp ' /etc/fstab || printf 'tmpfs /tmp tmpfs rw,nosuid,nodev,noexec,mode=1777,size=96M 0 0\n' >> /etc/fstab
grep -q '^tmpfs /var/tmp ' /etc/fstab || printf 'tmpfs /var/tmp tmpfs rw,nosuid,nodev,noexec,mode=1777,size=32M 0 0\n' >> /etc/fstab
cat >/etc/security/limits.d/99-entropysilo.conf <<'EOF'
wallet hard core 0
wallet soft core 0
EOF
cat >/etc/profile.d/entropysilo-no-history.sh <<'EOF'
if [ "${USER:-}" = wallet ]; then unset HISTFILE; export HISTSIZE=0 SAVEHIST=0; fi
EOF
chmod 0644 /etc/profile.d/entropysilo-no-history.sh
systemctl disable --now getty@tty1.service >/dev/null 2>&1 || true
systemctl mask getty@tty1.service >/dev/null 2>&1 || true
echo "Hardening ukończony. Przed odłączeniem sieci zainstaluj pozostałe paczki offline i zrestartuj."
