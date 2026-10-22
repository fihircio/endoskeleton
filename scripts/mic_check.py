#!/usr/bin/env python3
"""Mic + STT diagnostic for Elberr.

Run this on the Pi, speak during the capture, and it tells you exactly
what the recogniser heard and how good the signal was:

  python3 ~/mic_check.py 10

Output:
  * level profile (raw vs high-passed, per 0.5 s)
  * speech-band energy vs noise floor (the SNR that decides everything)
  * what Vosk hears, free-form and with the wake grammar
"""
import json
import math
import struct
import subprocess
import sys
import time

sys.path.insert(0, '/home/pi')
from vosk import Model, KaldiRecognizer, SetLogLevel
SetLogLevel(-1)

RATE = 16000
WAKE = ["hey dude", "hey man", "hey buddy", "hey", "hello elberr"]
MIC = "hw:CARD=Device"
MODEL = '/home/pi/brain/models/vosk-model-small-en-us-0.15'


def hp_coeffs(fc=250.0, fs=16000.0, Q=0.7071):
    w0 = 2 * math.pi * fc / fs
    alpha = math.sin(w0) / (2 * Q)
    c = math.cos(w0)
    a0 = 1 + alpha
    return (((1 + c) / 2) / a0, (-(1 + c)) / a0, ((1 + c) / 2) / a0,
            (-2 * c) / a0, (1 - alpha) / a0)


B0, B1, B2, A1, A2 = hp_coeffs()


def highpass(samples):
    x1 = x2 = y1 = y2 = 0.0
    out = []
    for x in samples:
        y = B0 * x + B1 * x1 + B2 * x2 - A1 * y1 - A2 * y2
        x2, x1 = x1, x
        y2, y1 = y1, y
        out.append(y)
    return out


def rms(v):
    return (sum(x * x for x in v) / max(len(v), 1)) ** 0.5


def band_energy(samples, lo, hi):
    """Crude Goertzel-free band energy via DFT on a window."""
    n = len(samples)
    if n < 16:
        return 0.0
    win = samples[:4096]
    total = 0.0
    f = lo
    while f < hi:
        wr = 2 * math.cos(2 * math.pi * f / RATE)
        s1 = s2 = 0.0
        for x in win:
            s0 = x + wr * s1 - s2
            s2, s1 = s1, s0
        total += (s1 * s1 + s2 * s2) ** 0.5
        f += 50
    return total


def main():
    secs = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    subprocess.run(["pkill", "-x", "arecord"])
    time.sleep(1)
    print(f"RECORDING {secs}s - SPEAK NOW (say: 'hey dude' then a question)")
    p = subprocess.Popen(
        ["arecord", "-q", "-D", MIC, "-f", "S16_LE", "-r", str(RATE),
         "-c", "1", "-d", str(secs), "-t", "raw"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    raw = p.stdout.read()
    p.wait()
    n = len(raw) // 2
    s = list(struct.unpack(f'<{n}h', raw[:n * 2]))
    f = highpass(s)

    print("\nLEVEL PROFILE (0.5 s windows)")
    print("  t(s)   raw_rms  hp_rms")
    step = RATE // 2
    for i in range(0, n - step + 1, step):
        t = i / RATE
        print("  %5.1f  %7.0f  %6.0f" % (t, rms(s[i:i + step]),
                                           rms(f[i:i + step])))

    speech = band_energy(f, 300, 3400)
    rumble = band_energy(f, 5, 100)
    print("\nSPECTRUM (high-passed)")
    print("  speech band 300-3400 Hz : %10.0f" % speech)
    print("  rumble band    5-100 Hz : %10.0f" % rumble)
    if speech > 0:
        print("  speech/rumble ratio      : %10.1f" % (speech / max(rumble, 1)))

    m = Model(MODEL)
    r = KaldiRecognizer(m, RATE)
    r.AcceptWaveform(raw)
    print("\nFREE-FORM :", r.Result().strip().replace("\n", " "))
    r2 = KaldiRecognizer(m, RATE)
    r2.SetGrammar(json.dumps(WAKE + ["[unk]"]))
    r2.AcceptWaveform(raw)
    print("WAKE GRAM :", r2.Result().strip().replace("\n", " "))
    hp_raw = struct.pack(f'<{len(f)}h', *[max(-32000, min(32000, int(x)))
                                           for x in f])
    r3 = KaldiRecognizer(m, RATE)
    r3.AcceptWaveform(hp_raw)
    print("HP + FREE :", r3.Result().strip().replace("\n", " "))


if __name__ == '__main__':
    main()
