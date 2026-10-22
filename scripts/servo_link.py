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
import json
import threading
import time

try:
    import serial
except ImportError:  # pragma: no cover
    serial = None


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
        self.ser = serial.Serial(self.port, self.baud, timeout=0.2)
        time.sleep(reset_wait)  # ESP8266 reboots when the port opens
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
