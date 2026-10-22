#!/bin/sh
# Reset the Philips PSE0510 USB camera mic.
#
# IMPORTANT: the *device* must be re-enumerated (1-1.3), NOT the parent hub.
# A hub reset brings the ALSA card back but the audio endpoint stays dead
# (arecord returns 0 bytes). Device-level unbind/bind revives the stream.
# Re-enumeration also restores DEFAULT mixer settings (mic gain back to 95%
# = clipping), so we re-apply a sane capture level here too.
#
# Install:
#   sudo cp usb-audio-reset.sh /usr/local/bin/usb-audio-reset
#   sudo chmod 755 /usr/local/bin/usb-audio-reset
#   echo 'pi ALL=(ALL) NOPASSWD: /usr/local/bin/usb-audio-reset' \
#     | sudo tee /etc/sudoers.d/usb-audio-reset
#   sudo chmod 440 /etc/sudoers.d/usb-audio-reset
set -e
DEV=${1:-1-1.3}
GAIN=${2:-50}

# find the mic's device node (VID 0c45) - it can change after re-enumeration
if [ "$DEV" = "auto" ]; then
  for d in /sys/bus/usb/devices/*/idVendor; do
    if [ "$(cat "$d" 2>/dev/null)" = "0c45" ]; then
      DEV=$(basename "$(dirname "$d")")
      break
    fi
  done
fi

# Release the device first: an open arecord handle blocks the unbind and
# leaves the endpoint dead even though the card comes back. Give the kernel
# time to actually release the interface (tested: <1s is not enough).
pkill -x arecord 2>/dev/null || true
sleep 3

echo "$DEV" > /sys/bus/usb/drivers/usb/unbind
sleep 2
echo "$DEV" > /sys/bus/usb/drivers/usb/bind
sleep 3

# card index shifts after re-enumeration -> look it up by name
CARD=$(awk '/PSE0510/{print $1; exit}' /proc/asound/cards 2>/dev/null | tr -d ':')
if [ -n "$CARD" ]; then
  amixer -c "$CARD" set Mic "$GAIN%" >/dev/null 2>&1 || true
  echo "mic device $DEV re-enumerated, card $CARD, gain ${GAIN}%" >&2
else
  echo "mic device $DEV re-enumerated (PSE0510 card not found yet)" >&2
fi
