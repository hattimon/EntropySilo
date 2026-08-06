#!/bin/bash
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo "Run as root" >&2; exit 1; }
IMAGE=${1:?image path required}
[[ -f $IMAGE ]] || { echo "Missing image: $IMAGE" >&2; exit 1; }
loop=$(losetup --find --show --partscan "$IMAGE")
cleanup() { losetup -d "$loop" 2>/dev/null || true; }
trap cleanup EXIT
file -s "${loop}p1" "${loop}p2"
e2fsck -fn "${loop}p2"
