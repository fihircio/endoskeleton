#!/bin/sh
# Reset the Philips PSE0510 USB camera mic by re-enumerating its device.
# This mic wedges after one capture on Linux (works on Windows); only a USB
# re-enumeration reliably revives the audio endpoint.
# Re-enumeration also restores DEFAULT mixer settings (mic gain back to
# 95% = clipping), so we re-apply a sane capture level here too.
# Usage: usb-mic-reset [device]   (default 1-1.3)
set -e
DEV=${1:-1-1.3}
GAIN=${2:-35}

echo "$DEV" > /sys/bus/usb/drivers/usb/unbind
sleep 1.5
echo "$DEV" > /sys/bus/usb/drivers/usb/bind
sleep 1.5

# card index shifts after re-enumeration -> look it up by name
CARD=$(awk '/PSE0510/{print $1; exit}' /proc/asound/cards 2>/dev/null | tr -d ':')
if [ -n "$CARD" ]; then
  amixer -c "$CARD" set Mic "$GAIN%" >/dev/null 2>&1 || true
  echo "mic device $DEV re-enumerated, card $CARD, gain ${GAIN}%" >&2
else
  echo "mic device $DEV re-enumerated (card index not found yet)" >&2
fi
