#!/usr/bin/env python3
"""Voice loop for humanoid-pi1: mic (USB camera) -> Vosk STT -> Qwen LLM -> espeak.

Listens in 6s windows (blip announces each window), decodes with Vosk,
asks llama.cpp (Qwen2.5-0.5B), speaks the reply, and steers the face
(/tmp/face_mood read by emo_eyes.py --mood-file).

  python3 voice_loop.py
  python3 voice_loop.py --once "hello robot"   # text-only round trip (no mic)

Files (all under ~/brain): models/qwen25-05b-q4km.gguf,
  models/vosk-model-small-en-us-0.15, voice_loop.py. LLM binary from llama.app.
"""
import argparse
import datetime
import json
import os
import struct
import subprocess
import sys
import time

HOME = os.path.expanduser("~")
BRAIN = os.path.join(HOME, "brain")
MODEL = os.path.join(BRAIN, "models", "qwen25-05b-q4km.gguf")
VOSK_DIR = os.path.join(BRAIN, "models", "vosk-model-small-en-us-0.15")
LLAMA = os.path.join(HOME, ".llama-app", "llama")
MOOD_FILE = "/tmp/face_mood"
LOG = os.path.join(BRAIN, "chats.log")

MIC = "hw:3"       # PSE0510 camera mic (stereo muss -> downmix)
SPK = "plughw:4"   # DS09 speaker via plug (mono/stereo + rate convert)
RATE = 16000
LISTEN_S = 6


def set_mood(mood):
    try:
        open(MOOD_FILE, "w").write(mood + "\n")
    except OSError:
        pass


def log(who, text):
    line = f"{datetime.datetime.now():%H:%M:%S} {who}: {text}"
    print(line, flush=True)
    try:
        open(LOG, "a").write(line + "\n")
    except OSError:
        pass


def blip(freq=880, ms=120):
    tone = os.path.join("/tmp", "blip.wav")
    subprocess.run(
        ["python3", "-c",
         f"import wave,struct,math;w=wave.open('{tone}','wb');"
         "w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);"
         f"w.writeframes(b''.join(struct.pack('<h',int(9000*math.sin(2*math.pi*{freq}*i/16000))) for i in range(int(16000*{ms}/1000))))"],
        check=True)
    subprocess.run(["aplay", "-q", "-D", SPK, tone],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


_ARECORD = None  # current recorder, so signals never orphan it


def listen():
    """Record one window, return mono int16 bytes (downmixed)."""
    global _ARECORD
    _ARECORD = subprocess.Popen(
        ["arecord", "-q", "-D", MIC, "-f", "S16_LE", "-r", str(RATE),
         "-c", "2", "-d", str(LISTEN_S), "-t", "raw"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        raw, _ = _ARECORD.communicate(timeout=LISTEN_S + 10)
    except subprocess.TimeoutExpired:
        _ARECORD.kill()
        raw, _ = _ARECORD.communicate()
    finally:
        _ARECORD = None
    n = len(raw) // 2
    if n == 0:
        return b""
    stereo = struct.unpack(f"<{n}h", raw[:n * 2])
    mono = [(a + b) // 2 for a, b in zip(stereo[0::2], stereo[1::2])]
    return struct.pack(f"<{len(mono)}h", *mono)


def _cleanup(signum=None, frame=None):
    if _ARECORD is not None:
        try:
            _ARECORD.kill()
        except OSError:
            pass
    raise SystemExit(0)


def stt(pcm):
    from vosk import KaldiRecognizer, Model
    if not hasattr(stt, "rec"):
        stt.rec = KaldiRecognizer(Model(VOSK_DIR), RATE)
        stt.rec.SetWords(False)
    stt.rec.AcceptWaveform(pcm)
    return json.loads(stt.rec.FinalResult()).get("text", "").strip()


def ask_llm(user_text):
    prompt = ("<|im_start|>system\nYou are Emo, a tiny cute desk robot Hand-built "
              "by your human on a Raspberry Pi. You see through a small camera "
              "and show your feelings with big cyan eyes. Keep every reply to "
              "one short plain sentence, no lists, no quotes.<|im_end|>\n"
              f"<|im_start|>user\n{user_text}<|im_end|>\n<|im_start|>assistant\n")
    p = subprocess.run(
        [LLAMA, "cli", "-m", MODEL, "-p", prompt, "-n", "30",
         "--temp", "0.7", "--no-display-prompt"],
        capture_output=True, text=True, timeout=180)
    out = (p.stdout or "").strip().splitlines()
    # strip prompt echo + chat template artifacts, keep the reply proper
    lines = [ln for ln in out
             if ln.strip() and "im_start" not in ln and "im_end" not in ln
             and ln.strip() != user_text.strip()]
    reply = (lines[-1] if lines else "Hmm.").strip()
    reply = reply.split("assistant")[-1].strip(" :")
    return " ".join(reply.split())[:280] or "Hmm."


def speak(text):
    p1 = subprocess.Popen(["espeak-ng", "--stdout", "-s", "135", "-v", "en", text],
                          stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    subprocess.run(["aplay", "-q", "-D", SPK], stdin=p1.stdout,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def round_trip(user_text):
    log("YOU", user_text)
    set_mood("happy")
    reply = ask_llm(user_text)
    log("EMO", reply)
    speak(reply)
    set_mood("normal")
    return reply


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", default=None, help="text-only round trip, no mic")
    args = ap.parse_args()
    if args.once:
        round_trip(args.once)
        return
    set_mood("normal")
    log("EMO", "voice loop online. Speak after the blip.")
    import math as _math
    import signal as _signal
    # clear any recorder orphaned by a previous killed loop
    subprocess.run(["pkill", "-f", "arecord.*hw:3"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    _signal.signal(_signal.SIGTERM, _cleanup)
    while True:
        try:
            blip()
            pcm = listen()
            n = len(pcm) // 2
            if n == 0:
                log("EMO", "mic gave no bytes.")
                continue
            samp = struct.unpack(f"<{n}h", pcm)
            rms = _math.sqrt(sum(s * s for s in samp) / n)
            peak = max(abs(s) for s in samp)
            text = stt(pcm)
            if not text:
                log("EMO", f"heard nothing (rms={rms:.0f} peak={peak}).")
                continue
            log("EMO", f"mic level rms={rms:.0f} peak={peak}.")
            round_trip(text)
        except KeyboardInterrupt:
            log("EMO", "going to sleep.")
            set_mood("sleep")
            _cleanup()
            break


if __name__ == "__main__":
    sys.exit(main())
