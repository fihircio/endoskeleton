#!/bin/sh
# Reset the Philips PSE0510 USB camera mic by re-enumerating its parent hub.
# This mic's audio endpoint wedges after prolonged use on Linux (works on
# Windows); only a USB re-enumeration revives it.
# Re-enumeration restores DEFAULT mixer settings (mic gain back to 95% =
# clipping), so we re-apply a sane capture level here too.
# Install:
#   sudo cp usb-audio-reset.sh /usr/local/bin/usb-audio-reset
#   sudo chmod 755 /usr/local/bin/usb-audio-reset
#   echo 'pi ALL=(ALL) NOPASSWD: /usr/local/bin/usb-audio-reset' \
#     | sudo tee /etc/sudoers.d/usb-audio-reset
#   sudo chmod 440 /etc/sudoers.d/usb-audio-reset
set -e
HUB=${1:-1-1}
GAIN=${2:-50}

echo "$HUB" > /sys/bus/usb/drivers/usb/unbind
sleep 3
echo "$HUB" > /sys/bus/usb/drivers/usb/bind
sleep 4

# card index shifts after re-enumeration -> look it up by name
CARD=$(awk '/PSE0510/{print $1; exit}' /proc/asound/cards 2>/dev/null | tr -d ':')
if [ -n "$CARD" ]; then
  amixer -c "$CARD" set Mic "$GAIN%" >/dev/null 2>&1 || true
  echo "hub $HUB re-enumerated, card $CARD, mic gain ${GAIN}%" >&2
else
  echo "hub $HUB re-enumerated (PSE0510 card not found yet)" >&2
fi
