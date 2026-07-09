"""Paisley Ponytail visual + audio theme.

Typography scale, HF-STD-010A-inspired palette, and the sector-open chime.
No third-party deps. MIT-clean (no vice / GPL assets).

Chime character: NYC transit door chime — short two-note "ding-dong"
(MTA classic / LIRR electronic door tone), not a long ARTCC ringer.
"""

from __future__ import annotations

import math
import os
import struct
import wave
from typing import Any

# ── Palette (DOT/FAA/AM-20/08 Table 1 + scope polish) ───────────────
# Slightly richer blacks and clearer hierarchy than pure mono green.

C: dict[str, str] = {
    "bg": "#070b08",
    "panel": "#0a100c",
    "scope": "#040704",
    "line": "#1c3220",
    "green": "#2AFF7A",       # slightly brighter primary
    "dim": "#3a5c44",
    "muted": "#5a8064",
    "white": "#F4FFF6",
    "yellow": "#E8F84A",
    "orange": "#FF9A1A",
    "red": "#FF2A35",
    "aqua": "#1AE0F5",
    "blue": "#6B9BFF",
    "magenta": "#E040FF",
    "gray": "#B8C4BA",
    "chart": "#1e3a28",
    "warn": "#3d4a1a",
    "chip_fg": "#001408",     # text on bright chips
    "zulu_bg": "#000000",
    "strip_fg": "#001408",
}

# ── Typography ──────────────────────────────────────────────────────
# Consolas is the scope mono. Sizes are *base* design points; F() scales
# them up so laptop kitchen duty (1080p / 1440p) stays readable.

_FONT_FAMILY = "Consolas"
# Global bump — body text was too small at 1.0; 1.45 clipped button and
# hint text inside the fixed-width right panel. 1.38 is the fit point.
_SCALE = 1.38
_MIN = 10


def F(size: int, weight: str = "") -> tuple[Any, ...]:
    """Return a tkinter font tuple, scaled for readability."""
    s = max(_MIN, int(round(size * _SCALE)))
    if weight:
        return (_FONT_FAMILY, s, weight)
    return (_FONT_FAMILY, s)


# Named roles for new code / map labels (optional convenience)
class Type:
    micro = lambda w="": F(7, w)       # footnotes, SIM tags
    caption = lambda w="": F(8, w)     # secondary labels
    body = lambda w="": F(9, w)        # log, mission copy
    ui = lambda w="": F(10, w)         # buttons, strip
    title = lambda w="": F(12, w)      # section headers
    banner = lambda w="": F(14, w)     # facility strip weight
    entry = lambda w="": F(20, w)      # screen-name field
    zulu = lambda w="": F(36, w)       # top clock
    hero = lambda w="": F(28, w)       # intro headlines


# Layout metrics (tk units / pixels)
LAYOUT = {
    "minsize": (1400, 900),
    "geometry": "1680x1050",
    "zulu_h": 64,
    "strip_h": 34,
    "sector_h": 36,
    "channel_h": 38,
    "right_w": 576,  # widest button label + padding at F(10) — no truncation
    "pad_body": 10,
    "btn_pady": 12,
    "entry_ipady": 16,
    "log_pad": 8,
}


# ── Sector-open aural (AP-disconnect / dual-tone family) ────────────

# Equal-temperament helpers (A4 = 440)
def _midi_hz(midi: float) -> float:
    return 440.0 * (2.0 ** ((midi - 69.0) / 12.0))


# Chord blasts — solid D power chord, hard edges (no trail-off).
# D power = D–A–D (root + P5 + octave).
CHIME_VARIATIONS: dict[str, dict[str, Any]] = {
    "maj3": {
        "label": "1  D power ×2 (short)",
        "freqs": (_midi_hz(50), _midi_hz(57), _midi_hz(62)),  # D3 A3 D4
        "duration": 0.30,
        "gap": 0.14,
        "count": 2,
    },
    "p4": {
        "label": "2  D power ×2 (PRODUCTION) — BEEP...BEEP hard cut",
        # D3–A3–D4
        "freqs": (_midi_hz(50), _midi_hz(57), _midi_hz(62)),
        "duration": 0.38,
        "gap": 0.16,
        "count": 2,
    },
    "p5": {
        "label": "3  D power ×2 (longer holds)",
        "freqs": (_midi_hz(50), _midi_hz(57), _midi_hz(62)),
        "duration": 0.48,
        "gap": 0.18,
        "count": 2,
    },
    "tight": {
        "label": "4  D power ×2 (tight)",
        "freqs": (_midi_hz(50), _midi_hz(57), _midi_hz(62)),
        "duration": 0.24,
        "gap": 0.12,
        "count": 2,
    },
    "heavy": {
        "label": "5  D power low ×2 (D2–A2–D3)",
        "freqs": (_midi_hz(38), _midi_hz(45), _midi_hz(50)),
        "duration": 0.42,
        "gap": 0.18,
        "count": 2,
    },
}


def synthesize_door_chime(
    path: str,
    *,
    variant: str = "p4",
    rate: int = 44100,
    amplitude: float = 0.42,
) -> str:
    """Write sector-open aural: **BEEP...BEEP** solid D power chord.

    Hard on / hard off — no trail-off. Original synthesis only.
    """
    cfg = CHIME_VARIATIONS.get(variant) or CHIME_VARIATIONS["p4"]
    freqs = [float(f) for f in cfg["freqs"]]
    duration = float(cfg["duration"])
    gap = float(cfg.get("gap", 0.16))
    count = int(cfg.get("count", 2))
    # Hard-edged feel, but no literal hard cut: a sine sliced mid-cycle
    # CLICKS. Tiny attack + a 12 ms release tail — too short to hear as
    # a fade, long enough to land the wave at zero.
    attack = 0.003
    release = 0.012
    n_partial = len(freqs)

    frames: list[int] = []
    frames.extend([0] * int(rate * 0.008))

    def _beep() -> None:
        n = max(1, int(rate * duration))
        for i in range(n):
            t = i / rate
            if t < attack:
                env = t / attack
            elif t > duration - release:
                env = max(0.0, (duration - t) / release)
            else:
                env = 1.0  # flat hold
            s = 0.0
            for f in freqs:
                phase = 2 * math.pi * f * t
                s += (
                    1.00 * math.sin(phase)
                    + 0.40 * math.sin(2 * phase)
                    + 0.20 * math.sin(3 * phase)
                    + 0.10 * math.sin(4 * phase)
                )
            s /= n_partial * 1.70
            sample = amplitude * env * s
            frames.append(int(max(-1.0, min(1.0, sample)) * 30000))

    for bi in range(count):
        _beep()
        if bi < count - 1:
            frames.extend([0] * int(rate * gap))

    frames.extend([0] * int(rate * 0.04))

    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with wave.open(path, "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"".join(struct.pack("<h", s) for s in frames))
    return path


def write_chime_variations(out_dir: str) -> list[str]:
    """Write all audition WAVs into ``out_dir``. Returns paths."""
    paths: list[str] = []
    for key in CHIME_VARIATIONS:
        p = os.path.join(out_dir, f"chime_{key}.wav")
        synthesize_door_chime(p, variant=key)
        paths.append(p)
    return paths
