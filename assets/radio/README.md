# Intro radio bed

Ambient audio plays **during the main intro** (low volume, looped).

## Drop your own (ElevenLabs, etc.)

Put a file here:

- `chatter.mp3` / `chatter.ogg` — needs `pip install pygame`
- `chatter.wav` — works with built-in Windows `winsound` (no extra deps)

**Tips for ElevenLabs**

- 45–90 second seamless-ish loop
- Mono, radio EQ (tinny), light static
- Fake chatter only — no real ATC recordings
- Keep under ~3–5 MB if you commit to git

The newest matching file wins (except the auto-generated `hf_bed.wav`).

## Default

The app synthesizes `hf_bed.wav`: quiet server-room ambience — a
continuous faint **400 Hz hum** (aircraft electrical power frequency)
over a fan/HVAC noise floor, one faint monitor beep roughly every
15 seconds, and once per 45 s loop the **ARTCC ringer** heard from
across the room — the real thing (`distant_ringer.wav`, pre-muffled),
mixed so quiet it's barely there. No squelch breaks, nothing keys up.

User-supplied ambient loops in this folder still override the default
(if present).

## Mute

Closing the intro (or taking the sector) stops the bed.

**Sector-open sound** is separate: `assets/door_chime.wav` — a short two-note
MTA / LIRR-style door chime (ding-dong), not a long ARTCC ringer. Generated
in `lib/theme.py` (`synthesize_door_chime`).
