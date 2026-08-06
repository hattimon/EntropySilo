#!/bin/bash
set -u

# Nie czekamy na wszystkie urządzenia udev. Wystarczy działający framebuffer LCD;
# evdev wykrywa dotyk i klawiatury także po uruchomieniu GUI.
for _attempt in $(seq 1 80); do
  framebuffer=""
  [[ -c /dev/fb1 ]] && framebuffer=/dev/fb1
  [[ -z $framebuffer && -c /dev/fb0 ]] && framebuffer=/dev/fb0
  broker=/run/entropysilo-privileged/control.sock
  if [[ -n $framebuffer && -S $broker && -w $broker ]]; then
    if [[ -d /dev/input ]]; then input_status=/dev/input; else input_status="input pending"; fi
    echo "EntropySilo hardware ready: using $framebuffer; $input_status; broker accessible"
    exit 0
  fi
  sleep 0.25
done
echo "EntropySilo: timeout waiting for framebuffer or accessible privileged broker" >&2
exit 1
