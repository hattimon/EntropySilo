#!/bin/bash
set -Eeuo pipefail
export DEBIAN_FRONTEND=noninteractive
export LANG=C.UTF-8

/opt/entropysilo/scripts/install_node_offline.sh
/opt/entropysilo/scripts/os_hardening.sh
/opt/entropysilo/scripts/install_entropysilo_offline.sh
/opt/entropysilo/scripts/install_swd_offline.sh
/opt/entropysilo/scripts/install_lcd_driver_offline.sh

# Runtime code uses the narrow Unix-socket broker and never sudo.  Remove sudo
# from the finished appliance image to reduce unnecessary privileged surface.
SUDO_FORCE_REMOVE=yes apt-get purge -y raspi-config sudo
apt-get clean
rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/*.deb /root/.npm /tmp/* /var/tmp/*
rm -f /etc/ssh/ssh_host_* 2>/dev/null || true
truncate -s 0 /etc/machine-id
rm -f /var/lib/dbus/machine-id
ln -s /etc/machine-id /var/lib/dbus/machine-id
for unit in systemd-firstboot.service userconfig.service userconf.service sshswitch.service \
  regenerate_ssh_host_keys.service triggerhappy.service triggerhappy.socket ModemManager.service \
  udisks2.service systemd-timesyncd.service; do
  systemctl disable "$unit" >/dev/null 2>&1 || true
  systemctl mask "$unit" >/dev/null 2>&1 || true
done
echo "Obraz EntropySilo został przygotowany."
