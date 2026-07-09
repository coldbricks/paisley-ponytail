"""Optional ambient radio bed for the scope intro.

Default: synthesized equipment-room ambience — a continuous faint
400 Hz hum (aircraft electrical power frequency), a whisper of noise
floor, one faint beep roughly every 15 seconds, and once per loop the
sector ringer heard from across the room: very quiet, muffled by
distance. No squelch breaks.

Optional: drop custom loops in assets/radio/ (.wav/.mp3/.ogg).
Playback: pygame if available, else winsound loop for .wav.
"""

from __future__ import annotations

import math
import os
import struct
import sys
import threading
import time
import wave
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_RADIO_DIR = _ROOT / "assets" / "radio"
_DEFAULT_BED = _RADIO_DIR / "hf_bed.wav"
# v8: server-room ambience — continuous 400 Hz hum + fan floor, faint beep
# ~every 15 s, the real ARTCC ringer once per loop from across the room
# (distant_ringer.wav stem), mixed BELOW the hum floor. Squelch breaks removed.
_BED_VERSION = 8
_BED_VER_FILE = _RADIO_DIR / ".hf_bed_version"

_play_lock = threading.Lock()
_playing = False
_stop_flag = False
_mode: str | None = None


def radio_dir() -> Path:
    _RADIO_DIR.mkdir(parents=True, exist_ok=True)
    return _RADIO_DIR


def find_radio_files() -> list[Path]:
    d = radio_dir()
    seen: set[str] = set()
    out: list[Path] = []
    for ext in ("*.wav", "*.mp3", "*.ogg"):
        for p in d.glob(ext):
            key = str(p.resolve()).lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(p)
    # Prefer user beds; never treat random packs as default over hf_bed
    user = [
        p for p in out
        if p.name.lower() != "hf_bed.wav"
        and "roger" not in p.name.lower()
    ]
    if user:
        return sorted(user, key=lambda p: p.stat().st_mtime, reverse=True)
    return sorted(
        [p for p in out if p.name.lower() == "hf_bed.wav"],
        key=lambda p: p.name.lower(),
    )


def _noise(seed: int) -> tuple[float, int]:
    seed = (1103515245 * seed + 12345) & 0x7FFFFFFF
    return (seed / 0x7FFFFFFF) * 2.0 - 1.0, seed


def ensure_default_hf_bed(seconds: float = 45.0, rate: int = 22050) -> Path:
    """Server-room ambience. Quiet. Nothing keys up.

    Layers, all faint:
      - continuous 400 Hz hum (aircraft electrical power frequency) with
        a slow organic wobble + soft 800 Hz harmonic
      - broadband fan/HVAC floor (filtered noise, no squelch events)
      - one short 1 kHz beep roughly every 15 s (jittered, not a metronome)
      - the sector ringer once per loop, heard from across the room:
        fundamentals only, soft edges, very quiet
    """
    radio_dir()
    ver_ok = (
        _DEFAULT_BED.is_file()
        and _DEFAULT_BED.stat().st_size > 1000
        and _BED_VER_FILE.is_file()
        and _BED_VER_FILE.read_text(encoding="utf-8").strip() == str(_BED_VERSION)
    )
    if ver_ok:
        return _DEFAULT_BED

    n = int(rate * seconds)
    samples: list[int] = []
    seed = 0x5A1E1E55
    lp = 0.0
    bp = 0.0

    # Faint monitor beeps ~every 15 s — jittered so the loop breathes.
    # Wrap gap (6.5 + 45 - 36.2) ≈ 15.3 s keeps the cadence across loops.
    beeps = [6.5, 21.8, 36.2]
    BEEP_LEN = 0.14
    BEEP_TAIL = 0.10

    def beep_env(t: float) -> float:
        for start in beeps:
            local = t - start
            if local < 0 or local > BEEP_LEN + BEEP_TAIL:
                continue
            if local < 0.008:
                return local / 0.008
            if local < BEEP_LEN:
                return 1.0
            return math.exp(-6.0 * (local - BEEP_LEN) / BEEP_TAIL)
        return 0.0

    # Distant sector ringer: the REAL ARTCC ringer, heard from across
    # the room once per loop. Ships as a pre-muffled stem
    # (assets/radio/distant_ringer.wav — low-passed at 900 Hz, peak 0.7);
    # mixed here so quiet it's barely there. Synth D-power fallback only
    # if the stem file is gone.
    RINGER_AT = 28.0
    RINGER_HOLD = 0.38
    RINGER_GAP = 0.16
    _D3, _A3, _D4 = 146.83, 220.0, 293.66

    ringer_stem: list[float] = []
    stem_path = _RADIO_DIR / "distant_ringer.wav"
    if stem_path.is_file():
        try:
            with wave.open(str(stem_path)) as rw:
                if rw.getsampwidth() == 2 and rw.getnchannels() == 1:
                    raw = rw.readframes(rw.getnframes())
                    vals = struct.unpack(f"<{len(raw) // 2}h", raw)
                    step = rw.getframerate() / rate
                    pos = 0.0
                    while pos < len(vals):
                        ringer_stem.append(vals[int(pos)] / 32768.0)
                        pos += step
        except Exception:
            ringer_stem = []

    def ringer_env(t: float) -> float:
        for k in (0, 1):
            local = t - (RINGER_AT + k * (RINGER_HOLD + RINGER_GAP))
            if local < 0 or local > RINGER_HOLD + 0.14:
                continue
            if local < 0.035:
                return local / 0.035          # smeared attack
            if local < RINGER_HOLD:
                return 1.0
            return math.exp(-5.0 * (local - RINGER_HOLD) / 0.14)
        return 0.0

    for i in range(n):
        t = i / rate
        white, seed = _noise(seed)
        # colored noise: fan / HVAC mush
        lp = 0.90 * lp + 0.10 * white
        bp = 0.55 * bp + 0.45 * (white - lp)

        # Fan floor — the "server room" hush, steady, no events
        floor = 0.020 * lp + 0.007 * bp

        # 400 Hz hum — the main character. Slow wobble so it breathes.
        wobble = 0.88 + 0.12 * math.sin(2 * math.pi * 0.11 * t)
        hum = wobble * (
            0.030 * math.sin(2 * math.pi * 400.0 * t)
            + 0.009 * math.sin(2 * math.pi * 800.0 * t)
        )

        # Faint monitor beep
        be = beep_env(t)
        beep = be * 0.026 * math.sin(2 * math.pi * 1020.0 * t) if be else 0.0

        # Distant ringer — SUPER quiet, under the hum. If you notice it,
        # it's too loud; it should register only when you listen for it.
        ringer = 0.0
        if ringer_stem:
            ri = i - int(rate * RINGER_AT)
            if 0 <= ri < len(ringer_stem):
                ringer = 0.012 * ringer_stem[ri]
        else:
            re_ = ringer_env(t)
            if re_:
                ringer = re_ * 0.020 * (
                    math.sin(2 * math.pi * _D3 * t)
                    + 0.8 * math.sin(2 * math.pi * _A3 * t)
                    + 0.5 * math.sin(2 * math.pi * _D4 * t)
                ) / 2.3

        sample = floor + hum + beep + ringer

        edge = int(rate * 0.04)
        fade = 1.0
        if i < edge:
            fade = i / edge
        elif i > n - edge:
            fade = (n - i) / edge

        # overall faint
        samples.append(int(max(-1.0, min(1.0, sample * fade * 0.62)) * 9500))

    with wave.open(str(_DEFAULT_BED), "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"".join(struct.pack("<h", s) for s in samples))
    _BED_VER_FILE.write_text(str(_BED_VERSION), encoding="utf-8")
    return _DEFAULT_BED


def start_intro_radio(*, volume: float = 0.13) -> str:
    """Start ambient bed for intro. Returns status string for UI."""
    global _playing, _stop_flag, _mode
    with _play_lock:
        stop_intro_radio()
        _stop_flag = False
        try:
            ensure_default_hf_bed()
        except Exception:
            pass
        files = find_radio_files()
        if not files:
            return "radio silent (no files)"

        path = files[0]
        try:
            import pygame

            if not pygame.mixer.get_init():
                pygame.mixer.init(frequency=22050, size=-16, channels=1, buffer=1024)
            pygame.mixer.music.load(str(path))
            pygame.mixer.music.set_volume(max(0.04, min(0.25, volume)))
            pygame.mixer.music.play(loops=-1)
            _playing = True
            _mode = "pygame"
            return f"radio bed  ·  {path.name}  ·  loop"
        except Exception:
            pass

        if path.suffix.lower() == ".wav" and sys.platform == "win32":
            try:
                import winsound

                winsound.PlaySound(
                    str(path),
                    winsound.SND_FILENAME
                    | winsound.SND_ASYNC
                    | winsound.SND_LOOP
                    | winsound.SND_NODEFAULT,
                )
                _playing = True
                _mode = "winsound"
                return f"radio bed  ·  {path.name}  ·  loop"
            except Exception as exc:
                return f"radio silent ({exc})"

        return f"radio silent (need pygame for {path.suffix} or use .wav)"


def stop_intro_radio() -> None:
    """Stop ambient bed (intro end / sector open)."""
    global _playing, _stop_flag, _mode
    _stop_flag = True
    if not _playing and _mode is None:
        return
    try:
        if _mode == "pygame":
            import pygame

            if pygame.mixer.get_init():
                pygame.mixer.music.fadeout(500)
                time.sleep(0.05)
                pygame.mixer.music.stop()
        elif _mode == "winsound" and sys.platform == "win32":
            import winsound

            winsound.PlaySound(None, winsound.SND_PURGE)
    except Exception:
        pass
    _playing = False
    _mode = None


def is_playing() -> bool:
    return _playing
