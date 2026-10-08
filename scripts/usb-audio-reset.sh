#!/bin/sh
# Self-healing for the Philips PSE0510 mic: its audio endpoint wedges until
# USB re-enumeration (works on Windows, grumpy snd-usb-audio teardown on
# Linux). Finds the mic's parent hub dynamically and power-cycles it.
# Installed (once) as root:
#   sudo cp usb-audio-reset.sh /usr/local/bin/usb-audio-reset
#   sudo chmod 755 /usr/local/bin/usb-audio-reset
#   echo 'pi ALL=(ALL) NOPASSWD: /usr/local/bin/usb-audio-reset' \
#     | sudo tee /etc/sudoers.d/usb-audio-reset
#   sudo chmod 440 /etc/sudoers.d/usb-audio-reset
set -e
DEV=$(grep -l 0c45 /sys/bus/usb/devices/*/idVendor 2>/dev/null | head -1)
if [ -z "$DEV" ]; then
  echo "mic not on USB bus" >&2
  exit 1
fi
D=$(basename "$(dirname "$DEV")")
HUB=${D%.*}
echo "resetting hub $HUB (mic at $D)" >&2
echo "$HUB" > /sys/bus/usb/drivers/usb/unbind
sleep 3
echo "$HUB" > /sys/bus/usb/drivers/usb/bind
