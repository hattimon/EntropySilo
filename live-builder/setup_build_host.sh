#!/bin/bash
set -Eeuo pipefail
umask 022

[[ $EUID -eq 0 ]] || { echo "Uruchom jako root." >&2; exit 1; }
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y debootstrap xorriso squashfs-tools curl ca-certificates xz-utils

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
download_verified() {
  local url=$1 hash=$2 target=$3
  curl --fail --location --proto '=https' --tlsv1.2 "$url" -o "$target"
  printf '%s  %s\n' "$hash" "$target" | sha256sum -c -
}

download_verified \
  https://deb.debian.org/debian/pool/main/d/debian-archive-keyring/debian-archive-keyring_2023.3+deb12u2_all.deb \
  f699e2f88dca05212f2a452b58475f2993cb6993dfbafb1d0205a3291eb8b4b8 \
  "$work/debian-archive-keyring.deb"
download_verified \
  https://deb.debian.org/debian/pool/main/l/live-build/live-build_20230502_all.deb \
  a863905724e7b69d45066ebab113cb6de12a11984349847ad49f6151c10f017d \
  "$work/live-build.deb"
dpkg -i "$work/debian-archive-keyring.deb" "$work/live-build.deb"
[[ $(lb --version) == 20230502 ]] || { echo "Nieprawidłowa wersja live-build." >&2; exit 1; }
echo "LIVE_BUILD_HOST_READY"
