#!/usr/bin/env python3
"""Arducam Mini 5MP Plus (OV5642) capture for Raspberry Pi — no wiringPi needed.

Faithful port of ArduCAM/Arduino's arducam_ov5642_capture.cpp + the
RASPBERRY_PI arch layer, using spidev + smbus + lgpio (all stock on Pi OS).

Wiring (spec hardware/wiring.md):
  VCC->3V3, GND->GND, SCL->GPIO3, SDA->GPIO2,
  SCK->GPIO11, MOSI->GPIO10, MISO->GPIO9, CS->GPIO17 (default, configurable)

Register tables are parsed at runtime from ArduCAM's ov5642_regs.h
(clone https://github.com/ArduCAM/Arduino once; no transcription errors).

Usage:
  python3 arducam_mini.py -c /tmp/img.jpg 640x480
  python3 arducam_mini.py -c /tmp/img.jpg 320x240 --regs ~/ArduCAM/ArduCAM/ov5642_regs.h
"""
import argparse
import os
import re
import sys
import time

import lgpio
import smbus
import spidev

# --- ArduCAM protocol constants (ArduCAM.h) ---
TEST1 = 0x00
MODE = 0x02
TIM = 0x03
FIFO = 0x04
FIFO_CLEAR_MASK = 0x01
FIFO_START_MASK = 0x02
BURST_FIFO_READ = 0x3C
TRIG = 0x41
CAP_DONE_MASK = 0x08
FIFO_SIZE1 = 0x42
FIFO_SIZE2 = 0x43
FIFO_SIZE3 = 0x44
MAX_FIFO_SIZE = 0x7FFFFF
SENSOR_ADDR = 0x3C  # OV5642 SCCB (0x78>>1) — matches i2cdetect 0x3C
CHIPID_HIGH = 0x300A
CHIPID_LOW = 0x300B

TABLES = [
    "OV5642_QVGA_Preview",
    "OV5642_JPEG_Capture_QSXGA",
    "ov5642_320x240",
    "ov5642_640x480",
    "ov5642_1024x768",
    "ov5642_1280x960",
    "ov5642_1600x1200",
    "ov5642_2048x1536",
    "ov5642_2592x1944",
]
SIZE_TO_TABLE = {
    "320x240": "ov5642_320x240",
    "640x480": "ov5642_640x480",
    "1024x768": "ov5642_1024x768",
    "1280x960": "ov5642_1280x960",
    "1600x1200": "ov5642_1600x1200",
    "2048x1536": "ov5642_2048x1536",
    "2592x1944": "ov5642_2592x1944",
}


def load_tables(path):
    """Parse {0xREG, 0xVAL} C arrays out of ov5642_regs.h."""
    src = open(path).read()
    tables = {}
    for name in TABLES:
        m = re.search(
            r"sensor_reg\s+" + re.escape(name) + r"\[\].*?\{(.*?)\};",
            src,
            re.S,
        )
        if not m:
            raise RuntimeError(f"table {name} not found in {path}")
        regs = []
        for reg, val in re.findall(r"\{\s*(0[xX][0-9a-fA-F]+)\s*,\s*(0[xX][0-9a-fA-F]+)\s*\}", m.group(1)):
            reg, val = int(reg, 16), int(val, 16)
            if reg == 0xFFFF and val == 0xFF:
                break
            regs.append((reg, val))
        tables[name] = regs
        print(f"table {name}: {len(regs)} regs", file=sys.stderr)
    return tables


class ArducamMini:
    def __init__(self, cs_gpio=17, spi_bus=0, spi_dev=0, spi_speed=1000000,
                 i2c_bus=1, i2c_addr=SENSOR_ADDR, regs_path=None):
        self.tables = load_tables(regs_path)
        self.i2c_addr = i2c_addr
        self.bus = smbus.SMBus(i2c_bus)
        self.spi = spidev.SpiDev()
        self.spi.open(spi_bus, spi_dev)
        self.spi.max_speed_hz = spi_speed
        self.spi.mode = 0
        self.gpio = lgpio.gpiochip_open(0)
        self.cs = cs_gpio
        lgpio.gpio_claim_output(self.gpio, self.cs, 1)

    def close(self):
        try:
            lgpio.gpiochip_close(self.gpio)
        except Exception:
            pass
        try:
            self.spi.close()
        except Exception:
            pass

    # --- low level: ArduChip SPI ---
    def _cs(self, level):
        lgpio.gpio_write(self.gpio, self.cs, level)

    def write_reg(self, addr, data):
        self._cs(0)
        self.spi.xfer2([addr | 0x80, data])
        self._cs(1)

    def read_reg(self, addr):
        self._cs(0)
        val = self.spi.xfer2([addr & 0x7F, 0x00])[1]
        self._cs(1)
        return val

    def transfer(self, data):
        return self.spi.xfer([data])[0]  # CS managed by caller (burst mode)

    # --- low level: sensor SCCB (16-bit reg addr, 8-bit val) ---
    def wr_sensor(self, reg, val):
        reg_h, reg_l = (reg >> 8) & 0xFF, reg & 0xFF
        self.bus.write_word_data(self.i2c_addr, reg_h, (val << 8) | reg_l)

    def rd_sensor(self, reg):
        reg_h, reg_l = (reg >> 8) & 0xFF, reg & 0xFF
        self.bus.write_byte_data(self.i2c_addr, reg_h, reg_l)
        return self.bus.read_byte(self.i2c_addr)

    def wr_sensor_table(self, name):
        for reg, val in self.tables[name]:
            self.wr_sensor(reg, val)
            time.sleep(0.001)

    # --- high level: port of setup()/InitCAM(JPEG) for MINI_5MP_PLUS ---
    def init(self, size="320x240"):
        # CPLD reset (current ArduCAM flow; the old Pi port omits it and the
        # FIFO then returns fixed-length garbage instead of JPEG frames)
        self.write_reg(0x07, 0x80)
        time.sleep(0.1)
        self.write_reg(0x07, 0x00)
        time.sleep(0.1)
        self.write_reg(TEST1, 0x55)
        if self.read_reg(TEST1) != 0x55:
            raise RuntimeError("SPI interface error (TEST1 mismatch)")
        self.write_reg(MODE, 0x00)
        self.wr_sensor(0xFF, 0x01)
        time.sleep(0.01)
        vid, pid = self.rd_sensor(CHIPID_HIGH), self.rd_sensor(CHIPID_LOW)
        print(f"sensor VID={vid:#04x} PID={pid:#04x}", file=sys.stderr)
        if (vid, pid) != (0x56, 0x42):
            raise RuntimeError("can't find OV5642 module")
        self.wr_sensor(0x3008, 0x80)  # reset
        self.wr_sensor_table("OV5642_QVGA_Preview")
        time.sleep(0.1)
        self.wr_sensor_table("OV5642_JPEG_Capture_QSXGA")
        self.set_size(size)
        time.sleep(0.1)
        for reg, val in [(0x3818, 0xA8), (0x3621, 0x10), (0x3801, 0xB0),
                         (0x4407, 0x08), (0x5888, 0x00), (0x5000, 0xFF)]:
            self.wr_sensor(reg, val)
        self.write_reg(FIFO, FIFO_CLEAR_MASK)  # clear_fifo_flag
        self.write_reg(0x01, 0x00)  # ARDUCHIP_FRAMES: single-shot mode

    def set_size(self, size):
        self.wr_sensor_table(SIZE_TO_TABLE[size])

    def read_fifo_length(self):
        l1 = self.read_reg(FIFO_SIZE1)
        l2 = self.read_reg(FIFO_SIZE2)
        l3 = self.read_reg(FIFO_SIZE3) & 0x7F
        return ((l3 << 16) | (l2 << 8) | l1) & MAX_FIFO_SIZE

    def capture(self, timeout_s=8, dump_first=0, raw_dump_path=None):
        self.write_reg(TIM, 0x02)  # VSYNC active HIGH
        self.write_reg(FIFO, FIFO_CLEAR_MASK)  # flush
        self.write_reg(FIFO, FIFO_CLEAR_MASK)  # clear done flag
        self.write_reg(FIFO, FIFO_START_MASK)  # start
        t0 = time.time()
        while not (self.read_reg(TRIG) & CAP_DONE_MASK):
            if time.time() - t0 > timeout_s:
                raise RuntimeError("capture timeout (no CAP_DONE)")
            time.sleep(0.005)
        length = self.read_fifo_length()
        print(f"fifo length={length}", file=sys.stderr)
        if length >= MAX_FIFO_SIZE or length == 0:
            raise RuntimeError(f"bad fifo length {length}")
        self._cs(0)
        self.transfer(BURST_FIFO_READ)
        raw = bytearray(self.transfer(0x00) for _ in range(length))
        self._cs(1)
        if raw_dump_path:
            open(raw_dump_path, "wb").write(bytes(raw))
            print(f"raw dump saved {raw_dump_path} ({len(raw)} bytes)", file=sys.stderr)
        raw_head = list(raw[:64])
        out = bytearray()
        started = False
        prev = 0
        for cur in raw:
            if not started:
                if prev == 0xFF and cur == 0xD8:
                    started = True
                    out += bytes((prev, cur))
            else:
                out.append(cur)
                if prev == 0xFF and cur == 0xD9:
                    break
            prev = cur
        if dump_first or not out:
            print("first bytes: " + " ".join(f"{b:02x}" for b in raw_head), file=sys.stderr)
        if not out:
            raise RuntimeError("no JPEG data (SOI not found)")
        return bytes(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-c", "--capture", required=True, help="output JPEG path")
    ap.add_argument("res", nargs="?", default="320x240", choices=list(SIZE_TO_TABLE))
    ap.add_argument("--regs", default=os.path.expanduser("~/ArduCAM/ArduCAM/ov5642_regs.h"))
    ap.add_argument("--cs", type=int, default=17)
    ap.add_argument("--spi-speed", type=int, default=1000000)
    ap.add_argument("--tries", type=int, default=3,
                    help="capture attempts; first frame is often stale")
    ap.add_argument("--dump-first", action="store_true",
                    help="print first 64 FIFO bytes (debug)")
    ap.add_argument("--raw-dump", metavar="FILE",
                    help="save full raw FIFO bytes without SOI search (debug)")
    args = ap.parse_args()

    cam = ArducamMini(cs_gpio=args.cs, spi_speed=args.spi_speed, regs_path=args.regs)
    try:
        cam.init(args.res)
        time.sleep(1)  # let auto-exposure settle
        img = None
        for attempt in range(1, args.tries + 1):
            try:
                img = cam.capture(dump_first=args.dump_first,
                                  raw_dump_path=args.raw_dump if attempt == 1 else None)
                break
            except RuntimeError as e:
                print(f"attempt {attempt}: {e}", file=sys.stderr)
        if img is None:
            raise SystemExit("all capture attempts failed")
        open(args.capture, "wb").write(img)
        print(f"saved {args.capture} ({len(img)} bytes)")
    finally:
        cam.close()


if __name__ == "__main__":
    main()
