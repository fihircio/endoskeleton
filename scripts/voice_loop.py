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

MIC = "hw:CARD=PSE0510"  # Philips camera mic, by name (card numbers move)
SPK = "plughw:CARD=DS09"  # USB speaker via plug (mono/stereo + rate convert)
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
_STREAM = None    # persistent mic stream: this camera's endpoint wedges on
                  # close/reopen under Linux (works on Windows), so we open
                  # once and read windows from the endless stream instead.


def _open_stream():
    global _STREAM
    _close_stream()
    _STREAM = subprocess.Popen(
        ["arecord", "-q", "-D", MIC, "-f", "S16_LE", "-r", str(RATE),
         "-c", "2", "-d", "3600", "-t", "raw"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    return _STREAM


def _close_stream():
    global _STREAM
    if _STREAM is not None:
        try:
            _STREAM.kill()
            _STREAM.wait(timeout=3)
        except OSError:
            pass
        _STREAM = None


def _read_exact(proc, nbytes, timeout_s=LISTEN_S + 8):
    """Blocking read of exactly nbytes (or b'' on EOF/timeout)."""
    import select as _select
    out, deadline = bytearray(), time.time() + timeout_s
    fd = proc.stdout.fileno()
    while len(out) < nbytes:
        remaining = deadline - time.time()
        if remaining <= 0:
            break
        r, _, _ = _select.select([fd], [], [], remaining)
        if not r:
            break
        chunk = proc.stdout.read(nbytes - len(out))
        if not chunk:
            break
        out += chunk
    return bytes(out)


def _rms(samples):
    import math as _math
    return _math.sqrt(sum(s * s for s in samples) / max(len(samples), 1))


def listen():
    """VAD-gated window from the persistent mic stream.

    Records until 0.8s of trailing silence after speech (or 6s of
    silence / 8s total cap), so typical turns take ~2s, not 6s.
    """
    for _ in ("stream", "reopen"):
        proc = _STREAM or _open_stream()
        if proc.poll() is not None:  # died -> reopen once
            proc = _open_stream()
        chunk_bytes = RATE * 2 * 2 // 5  # 0.2s stereo S16
        buf, speech, quiet, elapsed = bytearray(), False, 0, 0.0
        while elapsed < 8.0:
            raw = _read_exact(proc, chunk_bytes, timeout_s=3.0)
            if len(raw) < chunk_bytes // 2:
                break  # stream dead; outer retry reopens
            buf += raw
            elapsed += 0.2
            n = len(raw) // 2
            mono = struct.unpack(f"<{n}h", raw[:n * 2])[0::2]
            level = _rms(mono)
            if not speech:
                if level > 1500:
                    speech = True
                    quiet = 0
                elif elapsed >= 6.0:
                    break  # nobody home
            else:
                quiet = quiet + 1 if level < 700 else 0
                if quiet >= 4 and elapsed >= 1.0:
                    break  # 0.8s trailing silence
        if len(buf) >= RATE * 2 * 2 // 2:  # >=0.5s audio
            break
        _close_stream()  # wedge suspected: fresh handle, one retry
    else:
        return b""
    n = len(buf) // 2
    stereo = struct.unpack(f"<{n}h", bytes(buf[:n * 2]))
    mono = [(a + b) // 2 for a, b in zip(stereo[0::2], stereo[1::2])]
    return struct.pack(f"<{len(mono)}h", *mono)


def _cleanup(signum=None, frame=None):
    if _ARECORD is not None:
        try:
            _ARECORD.kill()
        except OSError:
            pass
    _close_stream()
    raise SystemExit(0)


def stt(pcm):
    from vosk import KaldiRecognizer, Model
    if not hasattr(stt, "rec"):
        stt.rec = KaldiRecognizer(Model(VOSK_DIR), RATE)
        stt.rec.SetWords(False)
    stt.rec.AcceptWaveform(pcm)
    return json.loads(stt.rec.FinalResult()).get("text", "").strip()


def ask_llm(user_text):
    """Chat via local llama-server (needs: llama serve -m MODEL --port 8080).

    Server keeps the model resident, so turns take ~3s instead of ~20s.
    """
    import json as _json
    import urllib.request as _url
    body = _json.dumps({
        "messages": [
            {"role": "system",
             "content": "You are Emo, a tiny cute desk robot hand-built by your "
                        "human on a Raspberry Pi. One short plain sentence, no lists."},
            {"role": "user", "content": user_text},
        ],
        "max_tokens": 25,
        "temperature": 0.7,
    }).encode()
    try:
        req = _url.Request("http://localhost:8080/v1/chat/completions",
                           data=body, headers={"Content-Type": "application/json"})
        with _url.urlopen(req, timeout=120) as r:
            choices = _json.load(r)["choices"]
    except Exception as e:  # server down? log and stay charming
        log("EMO", f"brain unreachable: {e}")
        return "Hmm."
    if not choices:
        return "Hmm."
    reply = choices[0]["message"]["content"]
    return " ".join(reply.split())[:280] or "Hmm."


def speak(text):
    p1 = subprocess.Popen(["espeak-ng", "--stdout", "-s", "135", "-v", "en", text],
                          stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    subprocess.run(["aplay", "-q", "-D", SPK], stdin=p1.stdout,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def round_trip(user_text):
    log("YOU", user_text)
    set_mood("sleepy")  # small thinking eyes
    reply = ask_llm(user_text)
    log("EMO", reply)
    set_mood("happy")   # ^ ^ while speaking
    speak(reply)
    set_mood("normal")  # big idle eyes
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
    # clear any recorder orphaned by a previous killed loop (-x matches
    # the process name only, so it can never match our own shell)
    subprocess.run(["pkill", "-x", "arecord"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    _signal.signal(_signal.SIGTERM, _cleanup)
    last_speech, sleeping = time.time(), False
    while True:
        try:
            set_mood("sleep" if sleeping else "listening")
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
                if not sleeping and time.time() - last_speech > 300:
                    sleeping = True
                    log("EMO", "quiet for 5 min -> sleep.")
                continue
            last_speech, sleeping = time.time(), False
            log("EMO", f"mic level rms={rms:.0f} peak={peak}.")
            round_trip(text)
        except KeyboardInterrupt:
            log("EMO", "going to sleep.")
            set_mood("sleep")
            _cleanup()
            break


if __name__ == "__main__":
    sys.exit(main())
