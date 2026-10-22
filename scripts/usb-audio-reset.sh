#!/bin/sh
# Reset the Philips PSE0510 USB camera mic.
#
# IMPORTANT: the *device* must be re-enumerated (1-1.3), NOT the parent hub.
# A hub reset brings the ALSA card back but the audio endpoint stays dead
# (arecord returns 0 bytes). Device-level unbind/bind revives the stream.
# Re-enumeration also restores DEFAULT mixer settings (mic gain back to 95%
# = clipping), so we re-apply a sane capture level here too.
#
# The USB stack can refuse the unbind ("echo: I/O error") when the device
# is in a bad state, so we retry and fall back to resetting the parent hub.
#
# Install:
#   sudo cp usb-audio-reset.sh /usr/local/bin/usb-audio-reset
#   sudo chmod 755 /usr/local/bin/usb-audio-reset
#   echo 'pi ALL=(ALL) NOPASSWD: /usr/local/bin/usb-audio-reset' \
#     | sudo tee /etc/sudoers.d/usb-audio-reset
#   sudo chmod 440 /etc/sudoers.d/usb-audio-reset
set -e
DEV=${1:-auto}
GAIN=${2:-70}
HUB_FALLBACK=1-1

find_dev() {
  for d in /sys/bus/usb/devices/*/idVendor; do
    if [ "$(cat "$d" 2>/dev/null)" = "0c45" ]; then
      basename "$(dirname "$d")"
      return 0
    fi
  done
  return 1
}

if [ "$DEV" = "auto" ]; then
  DEV=$(find_dev || true)
  [ -n "$DEV" ] || { echo "mic device not found on USB" >&2; exit 1; }
fi

# Release the device first: an open arecord handle blocks the unbind and
# leaves the endpoint dead even though the card comes back.
pkill -x arecord 2>/dev/null || true
sleep 2

# Unbind (with retries). The write can fail with I/O error while the USB
# stack is confused about the device.
ok=0
for i in 1 2 3; do
  if echo "$DEV" > /sys/bus/usb/drivers/usb/unbind 2>/dev/null; then
    ok=1
    break
  fi
  echo "unbind attempt $i failed" >&2
  sleep 2
done

if [ "$ok" != "1" ]; then
  # fallback: cycle the parent hub
  echo "falling back to hub reset" >&2
  echo "$HUB_FALLBACK" > /sys/bus/usb/drivers/usb/unbind 2>/dev/null || true
  sleep 3
  echo "$HUB_FALLBACK" > /sys/bus/usb/drivers/usb/bind 2>/dev/null || true
  sleep 4
else
  sleep 2
  echo "$DEV" > /sys/bus/usb/drivers/usb/bind 2>/dev/null || true
  sleep 3
fi

# card index shifts after re-enumeration -> look it up by name
CARD=$(awk '/PSE0510/{print $1; exit}' /proc/asound/cards 2>/dev/null | tr -d ':')
if [ -n "$CARD" ]; then
  amixer -c "$CARD" set Mic "$GAIN%" >/dev/null 2>&1 || true
  echo "mic device $DEV re-enumerated, card $CARD, gain ${GAIN}%" >&2
else
  echo "mic device $DEV re-enumerated (PSE0510 card not found yet)" >&2
fi
exit 0
