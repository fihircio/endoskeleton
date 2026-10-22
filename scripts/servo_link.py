#!/usr/bin/env python3
"""Serial link to the Wemos servo bridge (spec section 26/47 shape).

The bridge owns PWM, limits, speed and e-stop; this client only sends
joint targets in radians. Commands are re-sent at a fixed rate so the
bridge's command timeout never expires mid-gesture.

  from servo_link import ServoLink
  link = ServoLink(port="/dev/ttyUSB0")
  link.connect()
  link.set({"left_neck_pan": 0.9})     # look left
  link.estop()                          # kill outputs (latched on the bridge)
"""
import glob
import json
import os
import threading
import time

try:
    import serial
except ImportError:  # pragma: no cover
    serial = None

# Wemos D1 R2 = CH340 (VID 1a86, PID 7523). We look it up by USB ID because
# the ttyUSB number shifts whenever another USB device re-enumerates (e.g.
# the camera mic being reset).
WEMOS_VID = "1a86"
WEMOS_PID = "7523"


def find_wemos_port():
    """Return /dev/ttyUSB* for the Wemos, or None."""
    for tty in sorted(glob.glob("/sys/class/tty/ttyUSB*")):
        try:
            iface = os.path.dirname(os.path.realpath(os.path.join(tty, "device")))
            parent = os.path.dirname(iface)
            vid = open(os.path.join(parent, "idVendor")).read().strip()
            pid = open(os.path.join(parent, "idProduct")).read().strip()
        except OSError:
            continue
        if vid.lower() == WEMOS_VID and pid.lower() == WEMOS_PID:
            return "/dev/" + os.path.basename(tty)
    return None


class ServoLink:
    def __init__(self, port="/dev/ttyUSB0", baud=115200, rate_hz=5.0):
        self.port = port
        self.baud = baud
        self.interval = 1.0 / rate_hz
        self.ser = None
        self.target = {}
        self.enabled = False
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self.last_error = None

    # -- connection ----------------------------------------------------
    def connect(self, reset_wait=2.0):
        if serial is None:
            raise RuntimeError("python3-serial not installed")
        port = self.port or find_wemos_port()
        if port and not os.path.exists(port):
            found = find_wemos_port()
            if found:
                port = found
        if not port:
            raise RuntimeError("Wemos (1a86:7523) not found on USB")
        self.port = port
        # DTR/RTS must be asserted HIGH (dtr=True, rts=True): on the Wemos
        # CH340, RTS low pulls EN low and DTR low pulls GPIO0 low, which
        # RESETS the ESP8266. That reset disturbs the USB hub the camera mic
        # shares, and the mic's audio endpoint dies ("read error").
        # Keeping both lines high leaves the board running untouched.
        self.ser = serial.Serial(port, self.baud, timeout=0.2, dsrdtr=False)
        try:
            self.ser.dtr = True
            self.ser.rts = True
        except Exception:
            pass
        time.sleep(0.3)  # board is already running: no reboot to wait for
        self.ser.reset_input_buffer()
        self.enabled = False
        self._stop.clear()
        self._thread = threading.Thread(target=self._keepalive, daemon=True)
        self._thread.start()
        return True

    def close(self):
        self._stop.set()
        if self.ser:
            try:
                self.ser.close()
            except Exception:
                pass
            self.ser = None

    # -- commands ------------------------------------------------------
    def _write(self, obj):
        if not self.ser:
            return False
        try:
            with self._lock:
                self.ser.write((json.dumps(obj) + "\n").encode())
            return True
        except Exception as e:
            self.last_error = e
            return False

    def enable(self):
        self._write({"enable": True})
        self.enabled = True
        time.sleep(0.05)
        return True

    def disable(self):
        self._write({"enable": False})
        self.enabled = False
        self.target = {}

    def estop(self):
        self._write({"estop": True})
        self.enabled = False
        self.target = {}

    def reset(self):
        self._write({"reset": True})
        self.enabled = False
        self.target = {}

    def set(self, joints):
        """Set joint targets (radians). Keeps sending them in the background."""
        if not self.enabled:
            self.enable()
        self.target.update(joints)
        self._write({"joints": dict(self.target)})

    def release(self, joint=None):
        """Stop commanding a joint (it keeps its last position)."""
        if joint is None:
            self.target = {}
        else:
            self.target.pop(joint, None)
        if self.target:
            self._write({"joints": dict(self.target)})

    # -- background keep-alive ----------------------------------------
    def _keepalive(self):
        """Re-send the current target so the bridge's timeout never fires."""
        while not self._stop.is_set():
            try:
                if self.target and self.enabled:
                    self._write({"joints": dict(self.target)})
            except Exception:
                pass
            self._stop.wait(self.interval)


if __name__ == "__main__":
    import sys
    link = ServoLink()
    link.connect()
    if len(sys.argv) > 1 and sys.argv[1] == "estop":
        link.estop()
        print("estop sent")
    else:
        link.set({"left_neck_pan": 0.9})
        print("looking left; ctrl-c to stop")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            link.close()
