#!/usr/bin/env bash
# First-boot setup for humanoid Pi #1 (control computer).
# Flashed with: Raspberry Pi OS Lite 64-bit (Trixie). Run ONCE on the Pi over SSH.
# Covers: 3.5" screen notes, Pi camera (flex), PCA9685 (I2C), project static IP.
set -e

echo "== whoami =="
whoami; hostname

echo "== 1. system update =="
sudo apt-get update && sudo apt-get full-upgrade -y

echo "== 2. base tools =="
sudo apt-get install -y --no-install-recommends \
  git vim i2c-tools python3-pip python3-venv python3-dev \
  libcamera-apps rpicam-apps alsa-utils fswebcam 2>/dev/null || \
sudo apt-get install -y --no-install-recommends \
  git vim i2c-tools python3-pip python3-venv python3-dev libcamera-apps \
  alsa-utils fswebcam
# Cheap USB-audio gadgets wedge when the kernel auto-suspends their ports.
# Keep USB audio devices awake (prevents "cannot get freq" mic death).
sudo tee /etc/udev/rules.d/99-usb-audio.rules >/dev/null <<'EOF'
ACTION=="add", SUBSYSTEM=="usb", ATTR{idVendor}=="0c45", ATTR{power/control}=="*", ATTR{power/control}="on"
ACTION=="add", SUBSYSTEM=="usb", ATTR{idVendor}=="8087", ATTR{power/control}=="*", ATTR{power/control}="on"
EOF

echo "== 3. hostname -> humanoid-pi1 (spec section 4: .11) =="
sudo hostnamectl set-hostname humanoid-pi1 || true
# keep sudo warning-free: hostnamectl does not rewrite the 127.0.1.1 line
sudo sed -i 's/127.0.1.1.*/127.0.1.1\thumanoid-pi1/' /etc/hosts || true

echo "== 4. I2C + SPI + camera (needs reboot to take effect) =="
sudo raspi-config nonint do_i2c 0
sudo raspi-config nonint do_spi 0
# Modern stack auto-detects the flex camera (camera_auto_detect=1 default).
# NOTE: do NOT run LCD-show/LCD35-show on Trixie — it overwrites boot files and
# breaks modern kernels. SpotPear 3.5" (A) V3 uses the waveshare35a overlay instead.

echo "== 4b. SpotPear 3.5inch RPi LCD (A) V3 driver (Waveshare wiki, Trixie path) =="
sudo apt-get install -y unzip cmake
cd /tmp
rm -rf Waveshare35a Waveshare35a.zip
wget https://files.waveshare.com/wiki/common/Waveshare35a.zip
unzip ./Waveshare35a.zip
# Trixie/Bookworm moved firmware to /boot/firmware; fall back to /boot on older layouts
OVERLAY_DIR=/boot/firmware/overlays
[ -d "$OVERLAY_DIR" ] || OVERLAY_DIR=/boot/overlays
CFG=/boot/firmware/config.txt
[ -f "$CFG" ] || CFG=/boot/config.txt
sudo cp waveshare35a.dtbo "$OVERLAY_DIR"/
for line in "dtparam=spi=on" "dtoverlay=waveshare35a" "hdmi_force_hotplug=1" \
  "hdmi_group=2" "hdmi_mode=87" "hdmi_cvt 480 320 60 6 0 0 0" "hdmi_drive=2"; do
  grep -qxF "$line" "$CFG" || echo "$line" | sudo tee -a "$CFG" >/dev/null
done
# Lite has no desktop: console stays on HDMI unless mirrored to the SPI panel.
# After reboot, mirror it with fbcp (build once, autostart):
#   git clone https://github.com/waveshareteam/waveshare_fbcp.git ~/waveshare_fbcp
#   mkdir -p ~/waveshare_fbcp/build && cd ~/waveshare_fbcp/build
#   cmake .. && make -j4 && sudo ./fbcp &
# Touch (ADS7846) comes up via the overlay; calibrate later with xinput if needed.
# WIRING WARNING: the screen covers GPIO 1-26 incl. I2C SDA/SCL (pins 3/5).
# The PCA9685 needs those same pins -> use a 2x20 stacking header (preferred)
# or tap SDA/SCL/5V/GND with Dupont wires. I2C and SPI buses coexist fine.

echo "== 5. PCA9685 python libs (spec section 2.4) =="
python3 -m venv --system-site-packages ~/servo-venv 2>/dev/null || python3 -m venv ~/servo-venv
~/servo-venv/bin/pip install --upgrade pip
~/servo-venv/bin/pip install adafruit-circuitpython-pca9685 adafruit-circuitpython-servokit RPi.GPIO
echo "gpio group:"; sudo usermod -a -G gpio,i2c,spi "$USER" || true

echo "== 6. verify (after reboot) =="
cat <<'NEXT'
After reboot, on the Pi run:
  i2cdetect -y 1            # expect 0x40 (PCA9685 #1), 0x41 (#2), 0x4A (IMU later)
  rpicam-hello --timeout 5s # flex camera preview test
  ip addr                   # note address; set static 192.168.0.11 per hardware/wiring.md
NEXT
echo "DONE. Reboot now: sudo reboot"
