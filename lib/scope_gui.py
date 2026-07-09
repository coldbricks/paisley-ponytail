"""STARS/ERAM-style scope window for Paisley Ponytail.

Pure tkinter (stdlib) — no new deps. Dark scope, HF-STD-010A palette
from DOT/FAA/AM-20/08, N90 video map, anti-collision strobes on traffic,
CEDAR-style login / position-relief gate, transit door chime (MTA/LIRR-style), comms log,
and the recovery controls a non-coder needs.

Not FAA equipment. Issues no ATC clearances. ATC language is presentation.
"""

from __future__ import annotations

import asyncio
import math
import os
import queue
import random
import sys
import threading
import time
import webbrowser
from datetime import datetime, timezone
from tkinter import (
    BOTH,
    END,
    LEFT,
    RIGHT,
    X,
    Y,
    BooleanVar,
    Canvas,
    Entry,
    Frame,
    Label,
    StringVar,
    Text,
    Tk,
    messagebox,
    ttk,
)

from lib import __version__
from lib.engine import Config, Engine, Stats
from lib.gallery import write_gallery
from lib.grade import count_variants, grade_from_albums
from lib.prefs import load_prefs, save_pref
from lib.remarks import load_remarks, remark_for
from lib.truth import TRUTH, classify_recovery, mission_report, weather_state

from lib.theme import C, F, LAYOUT, synthesize_door_chime

# Palette + type scale: lib.theme (C, F, LAYOUT)

# Project assets/ next to repo root
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DOOR_CHIME = os.path.join(_ROOT, "assets", "door_chime.wav")
_RINGER_LEGACY = os.path.join(_ROOT, "assets", "artcc_ringer.wav")
_RINGER = _DOOR_CHIME if os.path.isfile(_DOOR_CHIME) else _RINGER_LEGACY

# Public regulatory anchor (FAA Order JO 7110.65) + NWS-style "danger to
# life and property" formulation. This is a simulation UI — not operational
# ATC. (Not 14 CFR 65.45 — that's tower operators; this glass is radar.)
_WARNING_BODY = """\
WARNING

DANGER TO LIFE AND PROPERTY MAY RESULT IF AIR TRAFFIC CONTROL DUTIES
ARE NOT PERFORMED IN ACCORDANCE WITH THE PROCEDURES AND PRACTICES
PRESCRIBED IN AIR TRAFFIC CONTROL ORDERS OF THE FEDERAL AVIATION
ADMINISTRATION.

FAA Order JO 7110.65 — Air Traffic Control.
  2-1-1 ATC SERVICE. The primary purpose of the ATC system is to prevent
      a collision involving aircraft operating in the system, and to
      provide a safe, orderly, and expeditious flow of air traffic.

JO 7110.65 Appendix A — Transfer of Position Responsibility.
  Specialists engaged in position relief share equal responsibility for the
  completeness and accuracy of the position relief briefing.

────────────────────────────────────────────────────────────────────────
THIS IS NOT AN FAA OPERATIONAL SYSTEM.
It issues no ATC clearances and controls no aircraft.
It is a Wayback Machine photo-recovery interface that uses ATC display
language for presentation only. (Paisley Ponytail / Tailstrike Studios)
────────────────────────────────────────────────────────────────────────

TYPE YOUR INITIALS TO ACKNOWLEDGE AND CONTINUE.
"""

# INTRO = pure hook. Show weight. Never announce the weight.
# No coaching. No "you don't need to understand." The glass does the rest.
# (eyebrow, headline, body, footer)
_INTRO_PAGES: list[tuple[str, str, str, str]] = [
    (
        "1999 — 2012",
        "THERE IS A PHOTO THAT SHOULD NOT BE GONE.",
        """A birthday.
A band practice.
Someone who isn't around anymore.
A caption you wrote when you were twenty.

Uploaded to Webshots because that's what people did.
Memory cards were small. Hard drives died. Prints never got made.

For a lot of families it was the only copy left.

Anywhere.""",
        "CONTINUE  →",
    ),
    (
        "01 DEC 2012  ·  0000Z",
        "THEY DELETED EVERYTHING.",
        """Not a migration.
Not a backup.

Gone.

Fourteen million accounts.
Ordinary lives, wiped at the source.

Volunteers hauled 105.9 terabytes into the Internet Archive
in the final weeks.

Then the door to open it broke.
For nearly a decade the method was one Wayback page at a time.

Most people stopped.
Some never did.""",
        "CONTINUE  →",
    ),
    (
        "THE WRECKAGE",
        "THE PHOTOS ARE STILL IN THERE.",
        """Not all of them.
Private albums died with the site.

The rest sits in 2,437 megawarcs —
locked, indexed wrong, or not indexed at all.

You are going in after them.""",
        "CONTINUE  →",
    ),
    (
        "PPTY  ·  SECTOR ARCHIVE  ·  ON FREQUENCY",
        "BRING THEM HOME.",
        """You are an air traffic controller
at the busiest air traffic control radar facility on the planet.

Your traffic is not airplanes.
Your traffic is other people's only copies.

1.  Screen name
2.  SEARCH
3.  PULL

The only person who can save these photos is you.

Good luck.
We're all counting on you.""",
        "CONTINUE  →",
    ),
    (
        "PRIORITIES  ·  DO NOT MOVE",
        "AVIATE.  NAVIGATE.  COMMUNICATE.",
        """1.  AVIATE
       Keep it flying.
       Protect what already landed.

2.  NAVIGATE
       Know the route before you commit.
       Search before you pull.

3.  COMMUNICATE
       Then talk.
       Short. True.

RESOLVE EVERY CONFLICT WITH MULTIPLE PLANS.

    Plan A.
    Plan B.
    An out.

Full-size → photo-size → thumbnail.
Missed approach: go around.
The wreckage will still be there.""",
        "ENTER  →",
    ),
]

# Trainer mantra — short form for strips / status / post-grant
_MANTRA_SHORT = "AVIATE · NAVIGATE · COMMUNICATE  ·  MULTIPLE PLANS · ALWAYS AN OUT"
_MANTRA_STRIP = (
    "MANTRA  AVIATE first  ·  NAVIGATE second  ·  COMMUNICATE third  ·  "
    "RESOLVE CONFLICTS WITH MULTIPLE PLANS"
)

# Sector designators — 5-letter callsign energy + -R## (radar).
# Format: XXXXX-R##  or  XXXXX##-R## (5 letters, optional digits, radar id)
_SECTOR_BOARD = [
    "PORTR-R41",
    "PYSLY-R90",   # Paisley — this facility
    "RACHL-R67",   # Rachel
    "TAMMY-R11",   # Tammy
    "RILEY-R28",
    "JENNA-R55",
    "SAWAN-R33",
    "LEXII-R72",
    "STORM-R19",
    "BLAZE-R44",
    "VIXEN-R08",
    "NIKKI-R61",
    "ASHLY-R15",   # Ash Airfoil nod
    "BRAND-R03",
    "KITTY-R77",
]
_OUR_SECTOR = "PYSLY-R90"  # home plate — Paisley Ponytail recovery sector


def _missed_plain(counts: dict) -> str:
    """Training-mode MISSED instrument: never call a retryable miss
    "never archived" — transport failures retry on the next run."""
    failed = counts.get("failed", 0)
    if not failed:
        return "none"
    transport = min(counts.get("transport", 0), failed)
    absent = failed - transport
    if transport and absent:
        return f"{absent} never archived · {transport} retry next run"
    if transport:
        return f"{transport} missed on weather — retry next run"
    return f"{absent} were never archived"



def _ensure_door_chime() -> str:
    """Return path to sector-open chime; synthesize if asset missing."""
    if os.path.isfile(_RINGER):
        return _RINGER
    try:
        synthesize_door_chime(_DOOR_CHIME)
        return _DOOR_CHIME if os.path.isfile(_DOOR_CHIME) else _RINGER
    except Exception:
        return _RINGER


def _play_wav(path: str) -> None:
    """Play a wav non-blocking (sector-open door chime on INITIAL grant only)."""
    if not path or not os.path.isfile(path):
        return
    if sys.platform == "win32":
        try:
            import winsound
            winsound.PlaySound(
                path, winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT
            )
            return
        except Exception:
            pass
    # Ringer-only fallback — dual tone is OK here (INITIAL grant), never for countdown
    try:
        if sys.platform == "win32":
            import winsound
            # BEEP...BEEP D power approx (D3 ~147 Hz)
            winsound.Beep(147, 300)
            winsound.Beep(147, 300)
    except Exception:
        pass


def _synth_sine_wav(
    path: str,
    *,
    freq: float = 300.0,
    duration: float = 0.42,
    rate: int = 22050,
    amplitude: float = 0.11,
) -> None:
    """Almost-too-calming pure sine — same pitch every time, soft as a breath."""
    import math
    import struct
    import wave

    n = max(1, int(rate * duration))
    # Long gentle bloom in, long fade out — no percussive edge
    attack = 0.09
    release = 0.22
    frames: list[int] = []
    for i in range(n):
        t = i / rate
        if t < attack:
            # ease-in (smoothstep) so it never pokes
            x = t / attack
            env = x * x * (3.0 - 2.0 * x)
        elif t > duration - release:
            x = max(0.0, (duration - t) / release)
            env = x * x * (3.0 - 2.0 * x)
        else:
            env = 1.0
        sample = amplitude * env * math.sin(2 * math.pi * freq * t)
        frames.append(int(max(-1.0, min(1.0, sample)) * 32000))

    with wave.open(path, "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"".join(struct.pack("<h", s) for s in frames))


def _beep_countdown(_n: int = 2) -> None:
    """Same calm ~300 Hz sine every beat (3, 2, 1). No pitch descent. No ding-ding.

    Door chime (_play_wav door_chime) only on INITIAL grant.
    """
    freq = 300.0
    path = None
    try:
        import tempfile

        fd, path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        _synth_sine_wav(path, freq=freq, duration=0.42, amplitude=0.11)
        if sys.platform == "win32":
            import winsound
            # Sync play so the file is not deleted under our feet; no dual-beep path
            winsound.PlaySound(
                path, winsound.SND_FILENAME | winsound.SND_NODEFAULT
            )
        else:
            _play_wav(path)
    except Exception:
        # Single low soft tone only — never 880/660 ding-ding
        try:
            if sys.platform == "win32":
                import winsound
                winsound.Beep(300, 180)
        except Exception:
            pass
    finally:
        if path:
            try:
                os.unlink(path)
            except OSError:
                pass


class ScopeApp:
    """Primary glass — looks like a night scope, runs recovery behind it."""

    def __init__(self):
        self.root = Tk()
        self.root.configure(bg=C["bg"])
        self.root.minsize(*LAYOUT['minsize'])
        self.root.geometry(LAYOUT['geometry'])
        try:
            self.root.state("zoomed")  # Windows maximize — use the whole wall
        except Exception:
            pass

        # TRAINING (default): a very simple guided wizard.
        # PROFESSIONAL: the entire cascade — gate ritual, panels, live feeds.
        self._pro = load_prefs().get("mode") == "professional"
        self._apply_title()

        self._q: queue.Queue = queue.Queue()
        self._busy = False
        self._tick = 0
        self._strobe_phase = 0
        self._position_open = False  # locked until login gate completes
        self._initials = ""
        self.callsign = StringVar()
        self.deep = BooleanVar(value=False)
        self.status = StringVar(value="LOGIN REQUIRED  ·  POSITION CLOSED")
        self._last_albums: list = []
        self._last_user = ""

        # Live mission state (WS1) — wired to the real engine, never cosmetic
        self._live_stats: Stats | None = None
        self._live_engine: Engine | None = None
        self._phase = "IDLE"
        self._pull_total = 0
        self._pull_board = 0
        self._pull_counts = {"fs": 0, "ph": 0, "th": 0, "failed": 0}
        self._missed_logged = 0
        self._last_wx_key = ""

        # Ambient (fake) strobes — always under live when LIVE ADS-B on
        self._targets = self._seed_targets()
        # Live cooperative surveillance — Professional only by default
        self._adsb_on = bool(self._pro)
        self._adsb_filter = "airborne"  # all | airborne | high | emerg
        self._adsb_aircraft: list = []
        self._adsb_source = ""
        self._adsb_count = 0
        self._adsb_trails: dict[str, list[tuple[float, float]]] = {}  # id -> [(x,y),...]
        # Datablock layout: recomputed per poll / filter / resize, NOT per
        # 80 ms strobe frame — placement is O(n²)-ish and positions only
        # move when the feed does.
        self._adsb_offsets: dict[str, tuple[float, float, float]] = {}
        self._adsb_layout_dirty = True
        self._adsb_layout_size = (0, 0)
        self._adsb_seen: set[str] = set()
        # Mission radar: the albums ARE the traffic. Each found album is
        # a target — flashing until the pull starts working it, solid
        # while photos land, white when its count is home.
        self._mission: dict[str, dict] = {}
        self._mission_order: list[str] = []
        self._mission_sweep = False
        self._adsb_error = ""
        self._adsb_fetching = False

        # Dual / tertiary channel redundancy (NAS automation style)
        # Real ERAM/STARS-class systems run dual-channel; tertiary = hot spare.
        self._channels = {
            "A": {"role": "ACTIVE", "health": "NORM", "ms": 12},
            "B": {"role": "STANDBY", "health": "NORM", "ms": 12},
            "C": {"role": "HOT SPARE", "health": "NORM", "ms": 14},
        }
        self._channel_active = "A"  # which channel is online for the glass
        self._vscs_active: str | None = None  # keyed landline (mock)
        self._vscs_keys: dict = {}
        # ZWY oceanic data-link / HF — mock lamps
        self._oceanic = {
            "ADSC": {"state": "LOGGED ON", "detail": "contracts OK"},
            "CPDLC": {"state": "ACTIVE", "detail": "FANS-1/A"},
            "SATCOM": {"state": "UP", "detail": "primary voice/data"},
            "HF": {"state": "STBY", "detail": "ARINC / backup"},
            "ARINC": {"state": "MON", "detail": "G/G relay"},
        }

        self._build()
        self._draw_map()
        self.root.after(40, self._animate)
        self.root.after(100, self._drain_queue)
        self.root.after(2000, self._channel_heartbeat)
        self.root.after(200, self._tick_zulu_clock)
        self.root.after(500, self._instr_poll)
        # Login gate sits on top of glass until sector is accepted.
        # Training: one calm card. Professional: the entire cascade.
        self.root.after(200, self._show_gate_for_mode)

    # ── Training / Professional mode plumbing ───────────────────────

    def _apply_title(self):
        mode = "PROFESSIONAL" if self._pro else "TRAINING"
        try:
            self.root.title(
                f"PPTY SCOPE  ·  {_OUR_SECTOR}  ·  Paisley Ponytail "
                f"v{__version__}  ·  {mode} MODE"
            )
        except Exception:
            pass

    def _show_gate_for_mode(self):
        if self._pro:
            self._show_login_gate()
        else:
            self._show_training_gate()

    def _toggle_mode(self):
        """Flip Training ↔ Professional; persist; rebuild the glass."""
        if self._busy:
            self._xmit("SYS", "UNABLE — finish the current operation first", "yellow")
            return
        self._pro = not self._pro
        save_pref("mode", "professional" if self._pro else "training")
        # Live feeds follow the mode unless the user re-toggles them
        self._adsb_on = bool(self._pro)
        self._apply_title()
        self._rebuild()
        # Switching INTO Professional replays the full front-door cascade
        # (intro slides -> gate -> brief -> countdown) even if the position
        # was already open — the ritual is the point of the mode.
        if self._pro and self._position_open:
            self._position_open = False
            self._show_gate_for_mode()

    def _rebuild(self):
        """Tear down and repaint the glass in the current mode.

        Preserves: comms log text, callsign box, position/initials,
        mission state. The gate reappears only if it was still up.
        """
        log_text = ""
        try:
            log_text = self.log.get("1.0", END)
        except Exception:
            pass
        gate_was_up = getattr(self, "_gate", None) is not None
        self._stop_intro_radio()
        for w in self.root.winfo_children():
            w.destroy()
        self._gate = None
        self._adsb_filter_btns = {}
        self._build()
        self._draw_map()
        try:
            self.log.configure(state="normal")
            if log_text.strip():
                self.log.insert(END, log_text)
            self.log.configure(state="disabled")
            self.log.see(END)
        except Exception:
            pass
        if gate_was_up and not self._position_open:
            self._show_gate_for_mode()
        elif self._position_open:
            mode = "PROFESSIONAL" if self._pro else "TRAINING"
            self._xmit("SYS", f"MODE SWITCH — {mode} glass painted", "aqua")
            if not self._pro:
                self._xmit(
                    "SYS",
                    "Training mode: simple path — name, SEARCH, PULL, gallery.",
                    "dim",
                )
            else:
                self._xmit(
                    "SYS",
                    "Professional mode: full cab armed — panels are presentation "
                    "(SIM) unless marked LIVE.",
                    "dim",
                )
            if self._adsb_on:
                self.root.after(800, self._poll_adsb)
            self._pulse_callsign_entry()
        self._set_busy(self._busy)

    # ── layout ──────────────────────────────────────────────────────

    def _build(self):
        # ── BIG ZULU / UTC CLOCK — top of the cab, always ───────────
        # Controllers live in Z. If it's not huge and at the top, it's wrong.
        zulu_bar = Frame(self.root, bg=C['zulu_bg'], height=LAYOUT['zulu_h'])
        zulu_bar.pack(fill=X, side="top")
        zulu_bar.pack_propagate(False)

        Label(
            zulu_bar,
            text=" UTC ",
            bg=C["zulu_bg"],
            fg=C["dim"],
            font=F(12, "bold"),
        ).pack(side=LEFT, padx=(18, 6))

        self._zulu_clock = StringVar(value="00:00:00Z")
        Label(
            zulu_bar,
            textvariable=self._zulu_clock,
            bg=C["zulu_bg"],
            fg=C["green"],
            font=F(36, "bold"),
        ).pack(side=LEFT, padx=(4, 14))

        self._zulu_date = StringVar(value="0000-00-00")
        Label(
            zulu_bar,
            textvariable=self._zulu_date,
            bg=C["zulu_bg"],
            fg=C["muted"],
            font=F(15, "bold"),
        ).pack(side=LEFT, padx=(0, 10))

        Label(
            zulu_bar,
            text=" ZULU ",
            bg=C["green"],
            fg=C["chip_fg"],
            font=F(13, "bold"),
            padx=12,
            pady=5,
        ).pack(side=LEFT, padx=10)

        Label(
            zulu_bar,
            text="  COORDINATED UNIVERSAL TIME  ·  ALL ENTRIES IN Z  ",
            bg=C["zulu_bg"],
            fg=C["dim"],
            font=F(10),
        ).pack(side=LEFT, padx=8)

        # Mode toggle — always visible, both modes, top right
        mode_chip = Label(
            zulu_bar,
            text=(
                "  MODE: PROFESSIONAL  ·  switch to TRAINING  "
                if self._pro
                else "  MODE: TRAINING  ·  switch to PROFESSIONAL  "
            ),
            bg=C["magenta"] if self._pro else C["aqua"],
            fg=C["chip_fg"],
            font=F(10, "bold"),
            padx=10,
            pady=5,
            cursor="hand2",
        )
        mode_chip.pack(side=RIGHT, padx=14)
        mode_chip.bind("<Button-1>", lambda e: self._toggle_mode())

        Label(
            zulu_bar,
            text=f"  PPTY  ·  v{__version__}  ",
            bg=C["zulu_bg"],
            fg=C["muted"],
            font=F(10),
        ).pack(side=RIGHT, padx=6)

        # Facility strip
        strip = Frame(self.root, bg=C['green'], height=LAYOUT['strip_h'])
        strip.pack(fill=X, side="top")
        strip.pack_propagate(False)
        strip_text = (
            f"  PPTY TWR   │   SECTOR {_OUR_SECTOR}   │   WAYBACK RADAR   │   "
            f"STARS/ERAM GLASS   │   DUAL+TERTIARY CHANNEL   │   NOT FAA EQUIPMENT  "
            if self._pro
            else "  PAISLEY PONYTAIL   │   WEBSHOTS PHOTO RECOVERY   │   "
                 "TRAINING MODE — GUIDED   │   PHOTOS STAY ON YOUR MACHINE  "
        )
        Label(
            strip,
            text=strip_text,
            bg=C["green"],
            fg=C["chip_fg"],
            font=F(11, "bold"),
            anchor="w",
        ).pack(fill=BOTH, expand=True)

        # The full cascade rides only in PROFESSIONAL mode
        self._sector_labels = {}
        self._ch_frames = {}
        self._ch_labels = {}
        self._ch_sync = None
        if self._pro:
            self._build_sector_bar()
            self._build_channel_bar()
            self._build_mantra_bar()

        body = Frame(self.root, bg=C["bg"])
        body.pack(fill=BOTH, expand=True)

        # Left: scope canvas
        left = Frame(body, bg=C["bg"])
        left.pack(side=LEFT, fill=BOTH, expand=True, padx=(LAYOUT['pad_body'], 6), pady=LAYOUT['pad_body'])

        self.map_title = StringVar(
            value=(
                f"{_OUR_SECTOR}  ·  N90 THEATER  ·  VIDEO MAP  ·  IFR  ·  "
                f"RNG 60 NM  ·  AMBIENT (SIM)"
                if self._pro
                else "RADAR PRESENTATION  ·  AMBIENT TRAFFIC (SIM — atmosphere only)"
            )
        )
        Label(
            left,
            textvariable=self.map_title,
            bg=C["bg"],
            fg=C["green"],
            font=F(9, "bold"),
            anchor="w",
        ).pack(fill=X)

        self.canvas = Canvas(
            left,
            bg=C["scope"],
            highlightthickness=1,
            highlightbackground=C["green"],
            highlightcolor=C["green"],
        )
        self.canvas.pack(fill=BOTH, expand=True, pady=(4, 0))
        self.canvas.bind("<Configure>", lambda e: self._draw_map())

        # Bottom status under map
        Label(
            left,
            textvariable=self.status,
            bg=C["bg"],
            fg=C["aqua"],
            font=F(10, "bold"),
            anchor="w",
        ).pack(fill=X, pady=(6, 0))

        # VSCS — Voice Switching and Control System (mock landline / interphone
        # panel). Professional only: it's sector ambiance, not an instrument.
        if self._pro:
            self._build_vscs(left)

        # Right: controls + comms
        right = Frame(body, bg=C['panel'], width=LAYOUT['right_w'])
        right.pack(side=RIGHT, fill=Y, padx=(6, LAYOUT['pad_body']), pady=LAYOUT['pad_body'])
        right.pack_propagate(False)

        Label(
            right,
            text=" CLEARANCE DELIVERY " if self._pro else " RECOVER YOUR PHOTOS ",
            bg=C["aqua"],
            fg="#000000",
            font=F(10, "bold"),
        ).pack(fill=X, pady=(0, 4))

        # Short reminder — still plain English
        mission = Label(
            right,
            text=(
                (
                    "105.9 TB still on frequency.\n"
                    "Screen name → SEARCH → PULL.\n\n"
                    "AVIATE · NAVIGATE · COMMUNICATE\n"
                    "Multiple plans. Always an out."
                )
                if self._pro
                else (
                    "1. Type the old Webshots screen name\n"
                    "2. SEARCH — see what the archive holds\n"
                    "3. PULL — save the photos to this computer\n"
                    "4. The photo gallery opens by itself"
                )
            ),
            bg=C["panel"],
            fg=C["white"],
            font=F(9),
            justify="left",
            wraplength=460,
            anchor="w",
        )
        mission.pack(fill=X, padx=10, pady=(2, 8))

        # Screen-name entry — the only control that matters. Make it scream.
        self._callsign_frame = Frame(
            right,
            bg=C["green"],
            highlightthickness=3,
            highlightbackground=C["green"],
            highlightcolor=C["yellow"],
            padx=3,
            pady=3,
        )
        self._callsign_frame.pack(fill=X, padx=8, pady=(10, 10))

        self._callsign_banner = Label(
            self._callsign_frame,
            text=" ▼  ENTER WEBSHOTS SCREEN NAME  ▼ ",
            bg=C["green"],
            fg="#000000",
            font=F(12, "bold"),
            anchor="center",
        )
        self._callsign_banner.pack(fill=X)

        Label(
            self._callsign_frame,
            text="the old username · half-remembered is fine · then SEARCH or PULL",
            bg="#0a140a",
            fg=C["aqua"],
            font=F(8),
            anchor="center",
        ).pack(fill=X)

        entry_row = Frame(self._callsign_frame, bg="#0a140a")
        entry_row.pack(fill=X, padx=4, pady=4)
        self.entry = Entry(
            entry_row,
            textvariable=self.callsign,
            bg="#000000",
            fg=C["green"],
            insertbackground=C["yellow"],
            font=F(20, "bold"),
            relief="flat",
            highlightthickness=2,
            highlightbackground=C["green"],
            highlightcolor=C["yellow"],
        )
        self.entry.pack(fill=X, ipady=LAYOUT['entry_ipady'])
        self.entry.bind("<Return>", lambda e: self._on_search())
        self._callsign_pulse = True

        btn_style = {
            "font": F(11, "bold"),
            "relief": "flat",
            "cursor": "hand2",
            "padx": 10,
            "pady": LAYOUT["btn_pady"],
        }

        def mkbtn(parent, text, cmd, bg, fg="#000000"):
            b = Label(parent, text=text, bg=bg, fg=fg, **btn_style)
            b.bind("<Button-1>", lambda e: cmd() if not self._busy else None)
            b.bind("<Enter>", lambda e: b.configure(bg=C["white"]) if not self._busy else None)
            b.bind("<Leave>", lambda e: b.configure(bg=bg))
            b.pack(fill=X, padx=12, pady=4)
            return b

        if self._pro:
            self.btn_search = mkbtn(right, "■  SEARCH  —  what's on the scope?", self._on_search, C["green"])
            self.btn_pull = mkbtn(right, "■  PULL  —  recover all photos now", self._on_pull, C["green"])
            self.btn_deep = mkbtn(
                right, "■  DEEP PULL  —  long-range 2002–2013", self._on_deep_pull, C["magenta"], fg=C["white"]
            )
            self.btn_find = mkbtn(
                right, "■  FIND  —  half-remembered name sweep", self._on_find, C["aqua"]
            )
            self.btn_gallery = mkbtn(
                right, "■  OPEN GALLERY  —  last hangar contact sheet", self._on_gallery, C["yellow"]
            )
        else:
            self.btn_search = mkbtn(right, "■  SEARCH  —  look first (recommended)", self._on_search, C["green"])
            self.btn_pull = mkbtn(right, "■  PULL  —  save all the photos", self._on_pull, C["green"])
            self.btn_deep = mkbtn(
                right, "■  ALSO CHECK OLDER YEARS  —  2002–2013, slower", self._on_deep_pull, C["magenta"], fg=C["white"]
            )
            self.btn_find = mkbtn(
                right, "■  FIND  —  can't remember the exact name?", self._on_find, C["aqua"]
            )
            self.btn_gallery = mkbtn(
                right, "■  OPEN GALLERY  —  see the photos", self._on_gallery, C["yellow"]
            )

        # Mission instruments — the glass always tells the truth about
        # traffic, weather, and landings. Both modes; density differs.
        self._build_instruments(right)

        self._adsb_filter_btns = {}
        if self._pro:
            Label(
                right,
                text="SURVEILLANCE  ·  LIVE ADS-B (PUBLIC FEEDS)",
                bg=C["panel"],
                fg=C["muted"],
                font=F(8),
                anchor="w",
            ).pack(fill=X, padx=10, pady=(12, 2))
            self.btn_adsb = mkbtn(
                right,
                f"■  LIVE ADS-B  —  {'ON' if self._adsb_on else 'OFF'}  (adsb.lol / OpenSky)",
                self._toggle_adsb,
                C["blue"] if self._adsb_on else C["dim"],
                fg=C["white"],
            )
            filt = Frame(right, bg=C["panel"])
            filt.pack(fill=X, padx=10, pady=(2, 4))
            for lab, mode in (
                ("ALL", "all"),
                ("AIR", "airborne"),
                ("HI", "high"),
                ("EMERG", "emerg"),
            ):
                b = Label(
                    filt,
                    text=f" {lab} ",
                    bg=C["dim"] if mode != self._adsb_filter else C["green"],
                    fg=C["white"] if mode != self._adsb_filter else "#000",
                    font=F(8, "bold"),
                    cursor="hand2",
                    padx=4,
                    pady=3,
                )
                b.bind("<Button-1>", lambda e, m=mode: self._set_adsb_filter(m))
                b.pack(side=LEFT, padx=2)
                self._adsb_filter_btns[mode] = b

            # ZWY oceanic coms — ADS-C / CPDLC / SATCOM / HF / ARINC (SIM)
            self._build_oceanic_panel(right)

        Label(
            right,
            text="COMMS LOG  ·  ZULU",
            bg=C["panel"],
            fg=C["muted"],
            font=F(8),
            anchor="w",
        ).pack(fill=X, padx=10, pady=(10, 2))

        log_frame = Frame(right, bg=C["line"])
        log_frame.pack(fill=BOTH, expand=True, padx=10, pady=(0, 10))
        self.log = Text(
            log_frame,
            bg="#060a06",
            fg=C["green"],
            font=F(9),
            relief="flat",
            wrap="word",
            state="disabled",
            highlightthickness=0,
            padx=6,
            pady=6,
        )
        self.log.pack(fill=BOTH, expand=True)
        self.log.tag_configure("green", foreground=C["green"])
        self.log.tag_configure("yellow", foreground=C["yellow"])
        self.log.tag_configure("red", foreground=C["red"])
        self.log.tag_configure("aqua", foreground=C["aqua"])
        self.log.tag_configure("dim", foreground=C["muted"])
        self.log.tag_configure("white", foreground=C["white"])
        self.log.tag_configure("magenta", foreground=C["magenta"])
        self.log.tag_configure("orange", foreground=C["orange"])

        Label(
            right,
            text="Photos stay on your machine. Be kind to archive.org.",
            bg=C["panel"],
            fg=C["dim"],
            font=F(7),
        ).pack(pady=(0, 8))

    # ── Professional-only top bars (sector board, channels, mantra) ──

    def _build_sector_bar(self):
        sec_bar = Frame(self.root, bg='#030603', height=LAYOUT['sector_h'])
        sec_bar.pack(fill=X, side="top")
        sec_bar.pack_propagate(False)
        Label(
            sec_bar,
            text=" SECTORS ",
            bg="#030603",
            fg=C["dim"],
            font=F(8, "bold"),
        ).pack(side=LEFT, padx=(8, 4))

        for sid in _SECTOR_BOARD:
            ours = sid == _OUR_SECTOR
            lab = Label(
                sec_bar,
                text=f" {sid} ",
                bg=C["green"] if ours else "#0a120a",
                fg="#000000" if ours else C["green"],
                font=F(9, "bold"),
                padx=3,
                pady=2,
                cursor="hand2",
            )
            lab.pack(side=LEFT, padx=2, pady=3)
            lab.bind("<Button-1>", lambda e, s=sid: self._select_sector(s))
            self._sector_labels[sid] = lab

        Label(
            sec_bar,
            text="  SIM  ·  click to set home sector  ·  R = radar  ",
            bg="#030603",
            fg=C["dim"],
            font=F(7),
        ).pack(side=RIGHT, padx=8)

    def _build_channel_bar(self):
        chbar = Frame(self.root, bg='#050805', height=LAYOUT['channel_h'])
        chbar.pack(fill=X, side="top")
        chbar.pack_propagate(False)
        Label(
            chbar,
            text=" CHANNEL ",
            bg="#050805",
            fg=C["muted"],
            font=F(8, "bold"),
        ).pack(side=LEFT, padx=(8, 4))

        for ch in ("A", "B", "C"):
            f = Frame(chbar, bg="#0a120a", padx=2, pady=2)
            f.pack(side=LEFT, padx=4, pady=3)
            lab = Label(
                f,
                text=self._channel_label_text(ch),
                bg="#0a120a",
                fg=C["green"],
                font=F(9, "bold"),
                padx=8,
                pady=2,
                cursor="hand2",
            )
            lab.pack()
            lab.bind("<Button-1>", lambda e, c=ch: self._force_channel(c))
            self._ch_frames[ch] = f
            self._ch_labels[ch] = lab

        self._ch_sync = Label(
            chbar,
            text="  SYNC OK  ·  REDUNDANT PAIR  ·  FAILOVER ARMED  ",
            bg="#050805",
            fg=C["dim"],
            font=F(8),
        )
        self._ch_sync.pack(side=LEFT, padx=10)
        Label(
            chbar,
            text="SIM  ·  NOT FAA EQUIPMENT  ·  click channel to force switch  ",
            bg="#050805",
            fg=C["muted"],
            font=F(7),
        ).pack(side=RIGHT, padx=8)

        self._paint_channels()

    def _build_mantra_bar(self):
        mantra_bar = Frame(self.root, bg="#0a100a", height=24)
        mantra_bar.pack(fill=X, side="top")
        mantra_bar.pack_propagate(False)
        Label(
            mantra_bar,
            text=f"  {_MANTRA_STRIP}  ",
            bg="#0a100a",
            fg=C["yellow"],
            font=F(8, "bold"),
            anchor="w",
        ).pack(fill=BOTH, expand=True)

    # ── Mission instruments (WS1) — truth about the recovery, always ──

    def _build_instruments(self, parent):
        wrap = Frame(parent, bg="#0a100c", highlightthickness=1,
                     highlightbackground=C["dim"])
        wrap.pack(fill=X, padx=8, pady=(10, 4))

        Label(
            wrap,
            text=" MISSION INSTRUMENTS " if self._pro else " STATUS ",
            bg=C["green"],
            fg="#000000",
            font=F(9, "bold"),
            anchor="w",
        ).pack(fill=X)

        self._iv_target = StringVar(value="—")
        self._iv_wx = StringVar(value="not checked yet")
        self._iv_phase = StringVar(value="ready")
        self._iv_board = StringVar(value="—")
        self._iv_landed = StringVar(value="—")
        self._iv_missed = StringVar(value="—")
        self._iv_next = StringVar(
            value="Type a screen name, then SEARCH."
        )

        rows = (
            ("TGT" if self._pro else "Working on", self._iv_target, C["white"]),
            ("ARCHIVE WX" if self._pro else "Archive", self._iv_wx, C["aqua"]),
            ("PHASE" if self._pro else "Doing", self._iv_phase, C["green"]),
            ("BOARD" if self._pro else "Albums", self._iv_board, C["white"]),
            ("LANDED" if self._pro else "Saved", self._iv_landed, C["green"]),
            ("MISSED" if self._pro else "Not recoverable", self._iv_missed, C["yellow"]),
            ("NEXT" if self._pro else "Next step", self._iv_next, C["aqua"]),
        )
        grid = Frame(wrap, bg="#0a100c")
        grid.pack(fill=X, padx=8, pady=6)
        for r, (key, var, color) in enumerate(rows):
            Label(
                grid, text=key, bg="#0a100c", fg=C["muted"],
                font=F(8, "bold"), anchor="ne", width=16,  # "Not recoverable" = 15 chars
                justify="right",
            ).grid(row=r, column=0, sticky="ne", padx=(0, 8), pady=1)
            Label(
                grid, textvariable=var, bg="#0a100c", fg=color,
                font=F(9, "bold") if self._pro else F(9),
                anchor="nw", justify="left", wraplength=320,
            ).grid(row=r, column=1, sticky="nw", pady=1)
        grid.columnconfigure(1, weight=1)

        # Truth banner — authored words for whatever just happened
        self._truth_banner = Label(
            wrap,
            text="",
            bg="#0a100c",
            fg=C["muted"],
            font=F(8),
            anchor="w",
            justify="left",
            wraplength=520,
            padx=8,
        )
        self._truth_banner.pack(fill=X, pady=(0, 6))

    def _set_truth(self, state, extra: str = ""):
        """Paint a truth state onto the banner + comms. state may be None."""
        tone_color = {
            "ok": "green", "caution": "yellow", "alert": "red", "dim": "dim",
        }
        if state is None:
            try:
                self._truth_banner.configure(text="", fg=C["muted"])
            except Exception:
                pass
            return
        text = f"{state.callout}\n{state.plain}"
        if extra:
            text += f"\n{extra}"
        text += f"\n▸ {state.action}"
        color = {"ok": C["green"], "caution": C["yellow"],
                 "alert": C["red"], "dim": C["muted"]}[state.tone]
        try:
            self._truth_banner.configure(text=text, fg=color)
        except Exception:
            pass
        self._xmit("TRUTH", state.callout, tone_color[state.tone])
        self._xmit("TRUTH", state.plain, "dim")
        if extra:
            self._xmit("TRUTH", extra, "dim")
        self._xmit("TRUTH", f"Next: {state.action}", "aqua")

    def _set_instr(self, *, target=None, wx=None, phase=None, board=None,
                   landed=None, missed=None, next_step=None):
        for var, val in (
            (self._iv_target, target), (self._iv_wx, wx),
            (self._iv_phase, phase), (self._iv_board, board),
            (self._iv_landed, landed), (self._iv_missed, missed),
            (self._iv_next, next_step),
        ):
            if val is not None:
                try:
                    var.set(val)
                except Exception:
                    pass

    def _fmt_landed(self) -> str:
        c = self._pull_counts
        if self._pro:
            return f"{c['fs']} FS  ·  {c['ph']} PH  ·  {c['th']} TH"
        total = c["fs"] + c["ph"] + c["th"]
        bits = [f"{total} photos"]
        if c["fs"]:
            bits.append(f"{c['fs']} full-size")
        if c["th"]:
            bits.append(f"{c['th']} small")
        return "  ·  ".join(bits)

    def _instr_poll(self):
        """Read the live engine + stats every 500ms — real events, no theater."""
        try:
            eng = self._live_engine
            if eng is not None and self._busy:
                wx = weather_state(eng.last_status, eng.last_nid)
                cool = eng.cooldown_remaining
                if wx is not None and wx.key.startswith("FLOW"):
                    label = (
                        f"FLOW CONTROL — pacing ({cool:.0f}s)"
                        if self._pro
                        else f"asked us to slow down — waiting politely ({cool:.0f}s)"
                    )
                    self._set_instr(wx=label)
                    if self._last_wx_key != wx.key:
                        self._last_wx_key = wx.key
                        self._set_truth(wx)
                elif wx is not None:
                    self._set_instr(
                        wx="ATC ZERO — unreachable" if self._pro
                        else "unreachable right now"
                    )
                    if self._last_wx_key != wx.key:
                        self._last_wx_key = wx.key
                        self._set_truth(wx)
                elif cool > 5:
                    self._set_instr(
                        wx=f"FLOW CONTROL — pacing ({cool:.0f}s)" if self._pro
                        else f"slowing down on purpose ({cool:.0f}s)"
                    )
                else:
                    self._set_instr(
                        wx="OK — archive answering" if self._pro
                        else "OK — answering"
                    )
                    if self._last_wx_key:
                        self._last_wx_key = ""
        except Exception:
            pass
        self.root.after(500, self._instr_poll)

    # ── video map + traffic ─────────────────────────────────────────

    def _seed_targets(self):
        """Ambient traffic for strobes — not real tracks."""
        random.seed(90)  # N90
        targets = []
        labels = [
            "AAL114", "JBU1804", "DAL488", "AWE123", "UAL712",
            "SWA441", "BAW117", "EJA55", "N17XX", "FDX301",
        ]
        for i, lab in enumerate(labels):
            targets.append({
                "label": lab,
                "x": 0.15 + (i % 5) * 0.16 + random.uniform(-0.03, 0.03),
                "y": 0.25 + (i // 5) * 0.22 + random.uniform(-0.04, 0.04),
                "vx": random.uniform(-0.0008, 0.0008),
                "vy": random.uniform(-0.0005, 0.0005),
                "alt": random.choice(["FL310", "FL350", "FL280", "120", "090"]),
                "phase": random.randint(0, 15),
            })
        return targets

    def _mission_place(self, idx: int) -> tuple[float, float]:
        """Golden-angle spiral around home plate: deterministic, spreads
        like real traffic, and no two targets land on each other."""
        import math as _m
        ang = _m.radians(90 + idx * 137.508)
        rad = min(0.13 + 0.034 * _m.sqrt(idx), 0.40)
        return 0.46 + rad * _m.cos(ang) * 1.12, 0.45 + rad * _m.sin(ang)

    def _draw_map(self):
        """N90 theater from assets/videomap/n90.json (public geo — not vice/GPL)."""
        c = self.canvas
        c.delete("static")
        w = max(c.winfo_width(), 100)
        h = max(c.winfo_height(), 100)

        try:
            from lib.videomap import load_videomap, project_point
            vm = load_videomap()
        except Exception:
            vm = None

        if not vm:
            c.create_text(
                w * 0.5, h * 0.5,
                text="VIDEO MAP UNAVAILABLE",
                fill=C["dim"], font=F(12, "bold"), tags="static",
            )
            self._draw_traffic()
            return

        bbox = vm.get("bbox")
        # Range rings centered on KJFK (or map center)
        jfk = next((a for a in vm.get("airports", []) if a.get("id") == "KJFK"), None)
        if jfk:
            cx, cy = project_point(jfk["lat"], jfk["lon"], w, h, bbox)
        else:
            ctr = vm.get("center", {})
            cx, cy = project_point(ctr.get("lat", 40.64), ctr.get("lon", -73.78), w, h, bbox)

        for r_frac, label in ((0.18, "20"), (0.32, "40"), (0.48, "60")):
            r = min(w, h) * r_frac
            c.create_oval(
                cx - r, cy - r, cx + r, cy + r,
                outline=C["dim"], width=1, tags="static",
            )
            c.create_text(
                cx + r * 0.72, cy - r * 0.72,
                text=label, fill=C["muted"], font=F(9, "bold"), tags="static",
            )

        c.create_line(0, h * 0.5, w, h * 0.5, fill=C["line"], dash=(3, 8), width=1, tags="static")
        c.create_line(w * 0.5, 0, w * 0.5, h, fill=C["line"], dash=(3, 8), width=1, tags="static")

        def _poly(coords, **kw):
            pts = []
            for lon, lat in coords:
                x, y = project_point(lat, lon, w, h, bbox)
                pts.extend([x, y])
            if len(pts) >= 4:
                c.create_line(*pts, tags="static", **kw)

        coast = vm.get("coast") or []
        if coast:
            _poly(coast, fill=C["chart"], width=3, smooth=True)
            _poly(coast, fill=C["green"], width=1, smooth=True)
        nj = vm.get("nj_coast") or []
        if nj:
            _poly(nj, fill=C["chart"], width=2, smooth=True)

        cold = "#3a5a6a"
        cold_fill = "#0a1218"
        cold_txt = "#6a8a9a"
        for wa in vm.get("warning_areas") or []:
            bb = wa.get("bbox") or {}
            x0, y1 = project_point(bb.get("lat_min", 40.4), bb.get("lon_min", -74.0), w, h, bbox)
            x1, y0 = project_point(bb.get("lat_max", 40.5), bb.get("lon_max", -73.5), w, h, bbox)
            c.create_rectangle(
                x0, y0, x1, y1,
                outline=cold, width=1, dash=(3, 3), fill=cold_fill, tags="static",
            )
            mx, my = (x0 + x1) / 2, (y0 + y1) / 2
            c.create_text(
                mx, my - 10,
                text=wa.get("label", wa.get("id", "")),
                fill=cold_txt, font=F(12, "bold"), tags="static",
            )
            c.create_text(
                mx, my + 12,
                text=wa.get("status", "COLD"),
                fill=cold_txt, font=F(10, "bold"), tags="static",
            )

        for ap in vm.get("airports") or []:
            x, y = project_point(ap["lat"], ap["lon"], w, h, bbox)
            col = C["yellow"] if ap.get("primary") else C["green"]
            c.create_text(
                x, y,
                text=ap.get("label", ap.get("id", "")),
                fill=col, font=F(int(ap.get("size", 10)), "bold"), tags="static",
            )

        for fx in vm.get("fixes") or []:
            x, y = project_point(fx["lat"], fx["lon"], w, h, bbox)
            col = C["aqua"] if fx.get("role") == "gate" else C["green"]
            c.create_text(
                x, y,
                text=fx.get("label", fx.get("id", "")),
                fill=col, font=F(int(fx.get("size", 9)), "bold"), tags="static",
            )

        for lab in vm.get("labels") or []:
            x, y = project_point(lab["lat"], lab["lon"], w, h, bbox)
            role = lab.get("role", "")
            if role == "water":
                col = C["chart"]
            elif role == "route":
                col = C["green"]
            elif role == "footer":
                col = "#6a8a9a"
            else:
                col = C["muted"]
            c.create_text(
                x, y,
                text=lab.get("text", ""),
                fill=col, font=F(int(lab.get("size", 10)), "bold"), tags="static",
            )

        self._draw_traffic()

    @staticmethod
    def _adsb_block_lines(ac: dict) -> tuple[str, str]:
        """The two datablock lines — single source for draw AND layout."""
        block1 = f"{ac.get('callsign') or '????'}"
        block2 = f"{ac.get('alt', '----')}  {ac.get('gs', '---')}KT"
        if ac.get("squawk") and ac["squawk"] not in ("----", ""):
            block2 += f"  SQ{ac['squawk']}"
        if ac.get("type"):
            block2 += f"  {ac['type']}"
        return block1, block2

    def _layout_datablocks(self, w: int, h: int):
        """Leader placement so full datablocks don't print over each other.

        STARS-ish: try eight positions around the target, then a farther
        ring, take the first that doesn't collide with an already-placed
        block. Emergencies place first. Aircraft that can't be placed at
        all (dead-center soup) keep the default east leader — rare.
        Runs per poll / filter / resize, never per strobe frame.
        """
        from lib.adsb_feed import geo_to_frac

        # ≈ px/char, Consolas via F(): line1 F(10,bold), line2 F(9)
        ch1 = F(10)[1] * 0.62
        ch2 = F(9)[1] * 0.62
        blk_h = F(10)[1] + F(9)[1] + 14
        placed: list[tuple[float, float, float, float]] = []
        offsets: dict[str, tuple[float, float, float]] = {}

        def overlaps(r):
            return any(
                not (r[2] < p[0] or p[2] < r[0] or r[3] < p[1] or p[3] < r[1])
                for p in placed
            )

        def try_place(x, y, est, bh):
            # Rings grow like a real leader extending in dense traffic —
            # a far label with a long leader beats an unreadable near one.
            for r, v in ((12, 0), (30, 16), (58, 40), (92, 72)):
                for dx, dy in (
                    (r, -22 - v), (r, -4), (r, 14 + v),          # east
                    (-r - est, -22 - v), (-r - est, -4),          # west
                    (-r - est, 14 + v),
                    (-est / 2, -30 - bh - v),                    # north
                    (-est / 2, 18 + v),                          # south
                ):
                    rect = (x + dx - 2, y + dy - 9, x + dx + est + 2, y + dy - 9 + bh)
                    if not overlaps(rect):
                        placed.append(rect)
                        return dx, dy
            return None

        acs = [a for a in self._adsb_aircraft if self._adsb_pass_filter(a)]
        acs.sort(key=lambda a: (not a.get("emergency"), bool(a.get("on_ground"))))
        drawn = 0
        for ac in acs:
            xf, yf = geo_to_frac(ac["lat"], ac["lon"])
            if xf < -0.05 or xf > 1.05 or yf < -0.05 or yf > 1.05:
                continue
            drawn += 1
            if drawn > 80:
                break
            x, y = w * xf, h * yf
            b1, b2 = self._adsb_block_lines(ac)
            # Degrade before you overlap: full block -> short block
            # (callsign + altitude) -> bare target. Real scopes declutter
            # the same way; ink never prints over ink.
            est_full = max(len(b1) * ch1, len(b2) * ch2) + 4
            est_short = max(len(b1) * ch1, len(str(ac.get("alt", "----"))) * ch2) + 4
            pos = try_place(x, y, est_full, blk_h)
            if pos is not None:
                offsets[ac["id"]] = (pos[0], pos[1], est_full, "full")
                continue
            if not ac.get("emergency"):  # an emergency never shrinks
                pos = try_place(x, y, est_short, blk_h)
                if pos is not None:
                    offsets[ac["id"]] = (pos[0], pos[1], est_short, "short")
                    continue
            offsets[ac["id"]] = (12, -22, est_short, "dot")
        self._adsb_offsets = offsets
        self._adsb_layout_dirty = False
        self._adsb_layout_size = (w, h)

    def _draw_traffic(self):
        c = self.canvas
        c.delete("traffic")
        c.delete("adsb")
        c.delete("trail")
        c.delete("mission")
        w = max(c.winfo_width(), 100)
        h = max(c.winfo_height(), 100)
        flash = self._strobe_phase in (0, 1, 4, 5)
        flash2 = self._strobe_phase in (0, 1)

        # ── Live ADS-B (real lat/lon → glass) ──
        if self._adsb_on and self._adsb_aircraft:
            from lib.adsb_feed import altitude_color, geo_to_frac

            if self._adsb_layout_dirty or self._adsb_layout_size != (w, h):
                self._layout_datablocks(w, h)

            drawn = 0
            for ac in self._adsb_aircraft:
                if not self._adsb_pass_filter(ac):
                    continue
                xf, yf = geo_to_frac(ac["lat"], ac["lon"])
                if xf < -0.05 or xf > 1.05 or yf < -0.05 or yf > 1.05:
                    continue
                x, y = w * xf, h * yf
                aid = ac["id"]
                if aid not in self._adsb_offsets:
                    continue  # beyond the layout's readability cap
                # history trail
                trail = self._adsb_trails.setdefault(aid, [])
                trail.append((x, y))
                if len(trail) > 12:
                    del trail[:-12]
                if len(trail) >= 2:
                    flat = []
                    for px, py in trail:
                        flat.extend([px, py])
                    c.create_line(
                        *flat,
                        fill=C["dim"],
                        width=1,
                        tags="trail",
                    )

                emerg = ac.get("emergency")
                on_gnd = ac.get("on_ground")
                col = C["red"] if emerg else altitude_color(
                    float(ac.get("alt_ft") or -1), bool(on_gnd)
                )
                # chevron / velocity vector oriented by track
                track = ac.get("track")
                size = 6 if emerg else 5
                if track is not None:
                    import math as _m
                    rad = _m.radians(float(track) - 90)  # 0=N → canvas
                    dx, dy = _m.cos(rad), _m.sin(rad)
                    # nose
                    c.create_line(
                        x, y, x + dx * 16, y + dy * 16,
                        fill=col, width=2, tags="adsb",
                    )
                # diamond target
                fill = C["white"] if (flash and not on_gnd) or (emerg and flash2) else col
                c.create_polygon(
                    x, y - size, x + size, y, x, y + size, x - size, y,
                    fill=fill, outline=col, tags="adsb",
                )
                if emerg and flash:
                    c.create_oval(
                        x - 14, y - 14, x + 14, y + 14,
                        outline=C["red"], width=2, tags="adsb",
                    )
                    c.create_oval(
                        x - 20, y - 20, x + 20, y + 20,
                        outline=C["orange"], width=1, tags="adsb",
                    )
                elif flash and not on_gnd:
                    c.create_oval(
                        x - 9, y - 9, x + 9, y + 9,
                        outline=C["white"], width=1, tags="adsb",
                    )

                # Data block — deconflicted leader + degrade level from
                # the layout pass ("dot" = target only, glass too dense)
                block1, block2 = self._adsb_block_lines(ac)
                dx, dy, est, style = self._adsb_offsets[aid]
                if style != "dot":
                    if style == "short":
                        block2 = str(ac.get("alt", "----"))
                    lx, ly = x + dx, y + dy
                    # leader meets the block on the edge facing the target
                    ex = lx - 2 if dx >= 0 else lx + est + 2
                    c.create_line(x, y, ex, ly + 8, fill=C["dim"], tags="adsb")
                    c.create_text(
                        lx, ly,
                        text=block1,
                        fill=C["white"] if not emerg else C["red"],
                        font=F(10, "bold"),
                        anchor="w",
                        tags="adsb",
                    )
                    c.create_text(
                        lx, ly + 14,
                        text=block2,
                        fill=col if not emerg else C["orange"],
                        font=F(9),
                        anchor="w",
                        tags="adsb",
                    )
                drawn += 1
                if drawn >= 80:
                    break  # glass readability hard cap

        # ── Mission radar: the albums ARE the traffic ──
        # Interrogation sweep while the archive is being searched
        if self._mission_sweep:
            import math as _m
            cx, cy = w * 0.46, h * 0.45
            r = min(w, h) * 0.46
            ang = (self._tick * 4.0) % 360
            for k, (colkey, wd) in enumerate(
                (("green", 2), ("muted", 1), ("dim", 1), ("chart", 1))
            ):
                a = _m.radians(ang - k * 6)
                c.create_line(
                    cx, cy, cx + r * _m.cos(a), cy + r * _m.sin(a),
                    fill=C[colkey], width=wd, tags="mission",
                )
        # Album targets: flash on find, solid while landing, white = home
        if self._mission:
            blink_on = (self._tick // 5) % 2 == 0
            for aid in self._mission_order:
                t = self._mission[aid]
                x, y = w * t["xf"], h * t["yf"]
                st = t["state"]
                landed = st == "solid" and t["n"] and t["done"] >= t["n"]
                col = C["white"] if landed else C["green"]
                c.create_polygon(
                    x, y - 6, x + 6, y, x, y + 6, x - 6, y,
                    outline=col,
                    fill=col if st == "solid" else "",
                    width=2, tags="mission",
                )
                if st == "flash" and not blink_on:
                    continue  # symbol stays painted; the block blinks
                if st == "solid":
                    line2 = f"{min(t['done'], t['n'])}/{t['n']}"
                elif t["n"]:
                    line2 = f"{t['n']} PHOTOS"
                else:
                    line2 = "NO TARGETS"
                c.create_line(x, y, x + 11, y - 15, fill=C["dim"], tags="mission")
                c.create_text(
                    x + 11, y - 24, text=t["title"], fill=col,
                    font=F(9, "bold"), anchor="w", tags="mission",
                )
                c.create_text(
                    x + 11, y - 10, text=line2,
                    fill=C["yellow"] if st == "solid" and not landed else C["muted"],
                    font=F(8), anchor="w", tags="mission",
                )

        # ── Ambient ghost traffic (dim) when ADS-B off or as underlay ──
        # Unlabeled on purpose: ambience must never read as live traffic
        # (no callsigns, no datablocks — LIVE ≠ SIM is a trust rule).
        show_ambient = (not self._adsb_on) or (self._adsb_count == 0)
        if show_ambient:
            for t in self._targets:
                x, y = w * t["x"], h * t["y"]
                size = 3
                c.create_polygon(
                    x, y - size, x + size, y, x, y + size, x - size, y,
                    fill=C["dim"] if not flash else C["muted"],
                    outline=C["dim"], tags="traffic",
                )

    def _adsb_pass_filter(self, ac: dict) -> bool:
        f = self._adsb_filter
        if f == "all":
            return True
        if f == "airborne":
            return not ac.get("on_ground")
        if f == "high":
            return (ac.get("alt_ft") or 0) >= 10000 and not ac.get("on_ground")
        if f == "emerg":
            return bool(ac.get("emergency")) or ac.get("squawk") in ("7700", "7600", "7500")
        return True

    def _toggle_adsb(self):
        self._adsb_on = not self._adsb_on
        state = "ON" if self._adsb_on else "OFF"
        try:
            self.btn_adsb.configure(
                text=f"■  LIVE ADS-B  —  {state}  (adsb.lol / OpenSky)",
                bg=C["blue"] if self._adsb_on else C["dim"],
            )
        except Exception:
            pass
        self._xmit(
            "SURV",
            f"LIVE ADS-B {state}"
            + (f"  ·  last {self._adsb_count} from {self._adsb_source}" if self._adsb_on else "  ·  ambient strobes only (SIM)"),
            "aqua" if self._adsb_on else "dim",
        )
        if self._adsb_on and self._position_open:
            self._poll_adsb()
        else:
            self.map_title.set(
                f"{_OUR_SECTOR}  ·  N90 THEATER  ·  VIDEO MAP  ·  IFR  ·  "
                f"RNG 60 NM  ·  AMBIENT (SIM)"
            )
        self._draw_traffic()

    def _set_adsb_filter(self, mode: str):
        self._adsb_filter = mode
        self._adsb_layout_dirty = True
        for m, b in getattr(self, "_adsb_filter_btns", {}).items():
            on = m == mode
            b.configure(bg=C["green"] if on else C["dim"], fg="#000" if on else C["white"])
        self._xmit("SURV", f"FILTER {mode.upper()}  ·  {self._adsb_count} in last paint", "aqua")
        self._draw_traffic()

    def _poll_adsb(self):
        if not self._adsb_on or self._adsb_fetching:
            return
        self._adsb_fetching = True

        def worker():
            try:
                from lib.adsb_feed import fetch_traffic
                result = fetch_traffic()
                self._q.put(("adsb", result, None))
            except Exception as exc:
                self._q.put(("adsb", {"ok": False, "error": str(exc), "aircraft": [], "count": 0}, None))

        threading.Thread(target=worker, daemon=True).start()

    def _apply_adsb(self, result: dict):
        self._adsb_fetching = False
        if not result.get("ok"):
            self._adsb_error = result.get("error") or "feed failed"
            self._xmit("SURV", f"ADS-B FEED DOWN — {self._adsb_error[:80]}", "yellow")
            self.map_title.set(
                "N90  ·  VIDEO MAP  ·  ADS-B PRIMARY LOST  ·  AMBIENT STROBES"
            )
            return
        ac = result.get("aircraft") or []
        self._adsb_aircraft = ac
        self._adsb_layout_dirty = True
        self._adsb_count = len(ac)
        self._adsb_source = result.get("source") or "?"
        emerg = [a for a in ac if a.get("emergency")]
        air = sum(1 for a in ac if not a.get("on_ground"))
        self.map_title.set(
            f"N90  ·  LIVE ADS-B  ·  {self._adsb_source}  ·  "
            f"{air} AIR / {self._adsb_count} TOT  ·  STROBE"
            + (f"  ·  ⚠ EMERG {len(emerg)}" if emerg else "")
        )
        # First-contact + emergency callouts
        for a in ac:
            aid = a["id"]
            if aid not in self._adsb_seen:
                self._adsb_seen.add(aid)
                if len(self._adsb_seen) <= 8 or a.get("emergency"):
                    self._xmit(
                        "RADAR",
                        f"CONTACT {a['callsign']}  {a.get('alt')}  "
                        f"{a.get('gs')}KT  SQ{a.get('squawk')}"
                        + (f"  ** {a['emergency'].upper()} **" if a.get("emergency") else ""),
                        "red" if a.get("emergency") else "green",
                    )
            if a.get("emergency"):
                self._xmit(
                    "EMERG",
                    f"{a['callsign']}  squawk {a.get('squawk')}  "
                    f"{a.get('emergency')}  {a.get('alt')}",
                    "red",
                )
        if self._position_open and not self._busy:
            z = datetime.now(timezone.utc).strftime("%H:%M:%SZ")
            self.status.set(
                f"SCOPE LIVE  ·  {z}  ·  ADS-B {self._adsb_count} "
                f"({self._adsb_source})  ·  {self._initials or '—'}"
            )
        self._draw_traffic()

    def _animate(self):
        self._tick += 1
        self._strobe_phase = (self._strobe_phase + 1) % 16
        # drift ambient ghosts
        for t in self._targets:
            t["x"] += t["vx"]
            t["y"] += t["vy"]
            if t["x"] < 0.05 or t["x"] > 0.95:
                t["vx"] *= -1
            if t["y"] < 0.12 or t["y"] > 0.65:
                t["vy"] *= -1
        self._draw_traffic()
        if self._tick % 25 == 0 and not self._busy and not self._position_open:
            z = datetime.now(timezone.utc).strftime("%H:%M:%SZ")
            self.status.set(
                f"LOGIN REQUIRED  ·  {z}" if self._pro
                else f"PRESS START TO BEGIN  ·  {z}"
            )
        # ADS-B poll ~ every 12s (150 * 80ms)
        if self._adsb_on and self._position_open and self._tick % 150 == 30:
            self._poll_adsb()
        self.root.after(80, self._animate)

    # ── comms ───────────────────────────────────────────────────────

    def _zulu(self) -> str:
        return datetime.now(timezone.utc).strftime("%H:%M:%SZ")

    def _tick_zulu_clock(self):
        """Big top-of-cab UTC clock — updates every second, always in Z."""
        now = datetime.now(timezone.utc)
        try:
            self._zulu_clock.set(now.strftime("%H:%M:%SZ"))
            self._zulu_date.set(now.strftime("%Y-%m-%d"))
        except Exception:
            pass
        self.root.after(1000, self._tick_zulu_clock)

    def _select_sector(self, sid: str):
        """Light up a sector designator — home plate for this recovery glass."""
        global _OUR_SECTOR
        _OUR_SECTOR = sid
        for s, lab in self._sector_labels.items():
            ours = s == sid
            lab.configure(
                bg=C["green"] if ours else "#0a120a",
                fg="#000000" if ours else C["green"],
            )
        self._xmit("SEC", f"SECTOR {sid}  —  you have the plate", "green")
        try:
            self.root.title(
                f"PPTY SCOPE  ·  {sid}  ·  Paisley Ponytail v{__version__}  ·  WAYBACK RADAR"
            )
        except Exception:
            pass

    def _pulse_callsign_entry(self):
        """After sector open: pulse the green screen-name box so it's obvious."""
        if not self._position_open:
            return
        try:
            # Stop screaming once they've typed something
            if self.callsign.get().strip():
                self._callsign_banner.configure(
                    text=" SCREEN NAME ",
                    bg=C["dim"],
                    fg=C["white"],
                )
                self._callsign_frame.configure(
                    highlightbackground=C["green"],
                    bg=C["green"],
                )
                return
            self._callsign_pulse = not getattr(self, "_callsign_pulse", True)
            if self._callsign_pulse:
                self._callsign_banner.configure(
                    text=" ▼  ENTER WEBSHOTS SCREEN NAME HERE  ▼ ",
                    bg=C["yellow"],
                    fg="#000000",
                )
                self._callsign_frame.configure(
                    highlightbackground=C["yellow"],
                    bg=C["yellow"],
                )
            else:
                self._callsign_banner.configure(
                    text=" ▼  ENTER WEBSHOTS SCREEN NAME HERE  ▼ ",
                    bg=C["green"],
                    fg="#000000",
                )
                self._callsign_frame.configure(
                    highlightbackground=C["green"],
                    bg=C["green"],
                )
            self.entry.focus_set()
        except Exception:
            pass
        self.root.after(700, self._pulse_callsign_entry)

    # ── dual / tertiary channel status ──────────────────────────────

    def _channel_label_text(self, ch: str) -> str:
        info = self._channels[ch]
        return f" CH {ch}  {info['role']}  ·  {info['health']}  ·  {info['ms']}ms "

    # ── VSCS landline / interphone panel (mock) ─────────────────────
    # Voice Switching and Control System (P/CG): provides controllers all
    # voice circuits (A/G and G/G) for ATC. This panel is presentation-only.

    # Keys: (id, label, reply_facility) — N90 theater + common G/G
    _VSCS_LAYOUT = [
        # row 0 — local towers
        ("JFK_TWR", "JFK\nTWR", "Kennedy Tower"),
        ("LGA_TWR", "LGA\nTWR", "LaGuardia Tower"),
        ("EWR_TWR", "EWR\nTWR", "Newark Tower"),
        ("TEB_TWR", "TEB\nTWR", "Teterboro Tower"),
        ("ISP_TWR", "ISP\nTWR", "Islip Tower"),
        ("HPN_TWR", "HPN\nTWR", "Westchester Tower"),
        # row 1 — approach / TRACON neighbors
        ("N90_APP", "N90\nAPP", "New York Approach"),
        ("N90_DEP", "N90\nDEP", "New York Departure"),
        ("PHL_APP", "PHL\nAPP", "Philadelphia Approach"),
        ("BOS_APP", "BOS\nAPP", "Boston Approach"),
        ("PCT_APP", "PCT\nAPP", "Potomac Approach"),
        ("C90_APP", "C90\nAPP", "Chicago Approach"),
        # row 2 — center / en route / command
        ("ZNY", "ZNY\nCENTER", "New York Center"),
        ("ZWY", "ZWY\nOCA", "New York Oceanic"),
        ("ZBW", "ZBW\nCENTER", "Boston Center"),
        ("ZDC", "ZDC\nCENTER", "Washington Center"),
        ("ATCSCC", "ATCSCC\nCMD", "Command Center"),
        ("CIC", "CIC\nSUP", "Controller in Charge"),
        # row 3 — specials
        ("EMERG", "EMERG\nLINE", "Emergency Net"),
        ("OVRD", "OVRDE\nSHOUT", "Override / Shout"),
        ("MON", "MON\nSPKR", "Monitor Speaker"),
        ("FD", "FLIGHT\nDATA", "Flight Data"),
        ("TMU", "TMU\nFLOW", "Traffic Management"),
        ("RELIEF", "RELIEF\nBRF", "Relief Briefing"),
    ]

    def _build_vscs(self, parent):
        wrap = Frame(parent, bg="#0a0e0c", highlightthickness=1, highlightbackground=C["dim"])
        wrap.pack(fill=X, pady=(8, 0))

        hdr = Frame(wrap, bg="#121a14")
        hdr.pack(fill=X)
        Label(
            hdr,
            text="  VSCS  ·  VOICE SWITCHING & CONTROL  ·  LANDLINE / INTERPHONE  ",
            bg="#121a14",
            fg=C["aqua"],
            font=F(8, "bold"),
            anchor="w",
            pady=3,
        ).pack(side=LEFT)
        Label(
            hdr,
            text="  SIM · G/G  ·  click a key  ·  LINE CLEAR?  ",
            bg="#121a14",
            fg=C["muted"],
            font=F(7),
            anchor="e",
            pady=3,
        ).pack(side=RIGHT, padx=6)

        grid = Frame(wrap, bg="#0a0e0c")
        grid.pack(fill=X, padx=6, pady=6)

        self._vscs_keys = {}
        for i, (kid, label, facility) in enumerate(self._VSCS_LAYOUT):
            r, c = divmod(i, 6)
            bg = C["red"] if kid == "EMERG" else ("#1a2030" if kid != "OVRD" else C["orange"])
            fg = C["white"] if kid in ("EMERG", "OVRD") else C["green"]
            btn = Label(
                grid,
                text=label,
                bg=bg,
                fg=fg,
                font=F(7, "bold"),
                width=9,
                height=2,
                relief="raised",
                bd=1,
                cursor="hand2",
                padx=2,
                pady=2,
            )
            btn.grid(row=r, column=c, padx=2, pady=2, sticky="nsew")
            btn.bind("<Button-1>", lambda e, k=kid, f=facility, lab=label: self._vscs_key(k, f, lab))
            self._vscs_keys[kid] = (btn, bg, fg)
            grid.columnconfigure(c, weight=1)

        self._vscs_line = StringVar(value="LINE IDLE  ·  no keyline selected  ·  monitor continuously")
        Label(
            wrap,
            textvariable=self._vscs_line,
            bg="#0a0e0c",
            fg=C["dim"],
            font=F(8),
            anchor="w",
            padx=8,
            pady=4,
        ).pack(fill=X)

    def _vscs_reset_keys(self):
        for kid, (btn, bg, fg) in self._vscs_keys.items():
            btn.configure(bg=bg, fg=fg, relief="raised")

    def _vscs_key(self, kid: str, facility: str, lab: str):
        """Mock landline key — ring, answer, short interphone exchange (7110.10 style)."""
        if not self._position_open:
            self._xmit("VSCS", "LINE DEAD — position closed; complete login first", "yellow")
            return

        self._vscs_reset_keys()
        btn, _bg, _fg = self._vscs_keys[kid]
        btn.configure(bg=C["green"], fg="#000000", relief="sunken")
        self._vscs_active = kid
        short = lab.replace("\n", " ")
        initials = self._initials or "XX"

        # Soft ring (not sector-open ringer every time — short pip)
        threading.Thread(target=_beep_countdown, args=(3,), daemon=True).start()

        self._vscs_line.set(
            f"KEYLINE  {short}  ·  RINGING  ·  {facility}  ·  G/G landline"
        )
        self._xmit("VSCS", f"KEY  {short}  —  LINE CLEAR?", "aqua")

        # Scripted interphone (mock) — 7110.10 message initiation flavor
        def answer():
            if self._vscs_active != kid:
                return
            self._vscs_line.set(
                f"KEYLINE  {short}  ·  UP  ·  {facility}  ·  GO AHEAD"
            )
            self._xmit("VSCS", f"{facility}.", "white")
            self._xmit(
                "VSCS",
                f"PPTY Sector Archive, {initials}. Point-out / coordination mock.",
                "green",
            )
            self._xmit("VSCS", f"{facility}, go ahead.", "white")
            if kid == "EMERG":
                self._xmit("VSCS", "EMERGENCY NET — priority one (mock). No live circuit.", "red")
            elif kid == "OVRD":
                self._xmit("VSCS", "OVERRIDE / SHOUT LINE — interrupting lower priority (mock).", "orange")
            elif kid == "ATCSCC":
                self._xmit("VSCS", "Command Center — TM coordination (mock). See OIS board.", "yellow")
            elif kid == "RELIEF":
                self._xmit("VSCS", "Relief briefing line — App A complete on this position.", "aqua")
            else:
                self._xmit(
                    "VSCS",
                    f"Traffic not a factor this frequency (mock). {initials}.",
                    "dim",
                )
            self._xmit("VSCS", f"Terminating — {initials}.", "dim")
            # Drop key visual after a beat
            self.root.after(4000, self._vscs_drop_key)

        self.root.after(450, answer)

    def _vscs_drop_key(self):
        self._vscs_reset_keys()
        self._vscs_active = None
        self._vscs_line.set("LINE IDLE  ·  no keyline selected  ·  monitor continuously")

    # ── ZWY oceanic coms (ADS-C / CPDLC / HF-SATCOM / ARINC) — mock ─
    # New York Oceanic is ZWY in the ZNY world. Most A/G is SATCOM/data-
    # link these days; HF remains the classic backup. Not live circuits.

    def _build_oceanic_panel(self, parent):
        wrap = Frame(
            parent,
            bg="#060a12",
            highlightthickness=1,
            highlightbackground="#1a3040",
        )
        wrap.pack(fill=X, padx=10, pady=(10, 4))

        hdr = Frame(wrap, bg="#0a1520")
        hdr.pack(fill=X)
        Label(
            hdr,
            text=" ZWY  ·  NEW YORK OCEANIC  ·  DATA-LINK / HF ",
            bg="#0a1520",
            fg=C["aqua"],
            font=F(8, "bold"),
            anchor="w",
            pady=3,
            padx=4,
        ).pack(side=LEFT)
        Label(
            hdr,
            text=" SIM  ",
            bg="#1a3040",
            fg=C["muted"],
            font=F(7, "bold"),
            padx=4,
        ).pack(side=RIGHT, padx=4, pady=2)

        Label(
            wrap,
            text="  WATRS / NAT  ·  Y483 on map  ·  SATCOM primary · HF standby · ARINC G/G ",
            bg="#060a12",
            fg="#4a6a7a",
            font=F(6),
            anchor="w",
        ).pack(fill=X, padx=2)

        grid = Frame(wrap, bg="#060a12")
        grid.pack(fill=X, padx=4, pady=4)

        self._oceanic_lamps = {}
        # (key, short label)
        lamps = [
            ("ADSC", "ADS-C"),
            ("CPDLC", "CPDLC"),
            ("SATCOM", "SATCOM"),
            ("HF", "HF"),
            ("ARINC", "ARINC"),
        ]
        for i, (key, lab) in enumerate(lamps):
            cell = Frame(grid, bg="#0c141c", padx=2, pady=2)
            cell.grid(row=0, column=i, padx=2, sticky="nsew")
            grid.columnconfigure(i, weight=1)
            title = Label(
                cell,
                text=lab,
                bg="#0c141c",
                fg=C["muted"],
                font=F(7, "bold"),
            )
            title.pack()
            st = Label(
                cell,
                text=self._oceanic[key]["state"],
                bg="#0c141c",
                fg=C["green"],
                font=F(8, "bold"),
                cursor="hand2",
            )
            st.pack()
            st.bind("<Button-1>", lambda e, k=key: self._oceanic_key(k))
            self._oceanic_lamps[key] = st

        self._oceanic_line = StringVar(
            value="ZWY idle  ·  no SELCAL / no uplink  ·  click a lamp"
        )
        Label(
            wrap,
            textvariable=self._oceanic_line,
            bg="#060a12",
            fg="#5a7a8a",
            font=F(7),
            anchor="w",
            padx=6,
            pady=3,
        ).pack(fill=X)

        # Quick action keys
        act = Frame(wrap, bg="#060a12")
        act.pack(fill=X, padx=4, pady=(0, 4))
        for lab, kind in (
            ("UPLINK", "uplink"),
            ("DOWNLINK", "downlink"),
            ("SELCAL", "selcal"),
            ("HF PTT", "hf"),
        ):
            b = Label(
                act,
                text=f" {lab} ",
                bg="#152030",
                fg=C["aqua"],
                font=F(7, "bold"),
                cursor="hand2",
                padx=3,
                pady=2,
            )
            b.pack(side=LEFT, padx=2)
            b.bind("<Button-1>", lambda e, k=kind: self._oceanic_action(k))

        self._paint_oceanic_lamps()

    def _paint_oceanic_lamps(self):
        colors = {
            "LOGGED ON": C["green"],
            "ACTIVE": C["green"],
            "UP": C["green"],
            "STBY": C["orange"],
            "MON": C["aqua"],
            "DOWN": C["red"],
            "NO COM": C["red"],
        }
        for key, lab in self._oceanic_lamps.items():
            st = self._oceanic[key]["state"]
            lab.configure(text=st, fg=colors.get(st, C["gray"]))

    def _oceanic_key(self, key: str):
        if not self._position_open:
            self._xmit("ZWY", "Oceanic panel locked — take the sector first", "yellow")
            return
        info = self._oceanic[key]
        detail = info["detail"]
        # Cycle STBY/UP style for fun on HF
        if key == "HF":
            info["state"] = "UP" if info["state"] == "STBY" else "STBY"
            info["detail"] = "ARINC family / secondary" if info["state"] == "UP" else "ARINC / backup"
            self._paint_oceanic_lamps()
        self._oceanic_line.set(f"ZWY  {key}  ·  {info['state']}  ·  {detail}")
        self._xmit(
            "ZWY",
            f"{key}  {info['state']}  —  {detail}  (New York Oceanic mock)",
            "aqua",
        )
        if key == "ADSC":
            self._xmit("ZWY", "ADS-C: position reports / demand contract (mock).", "dim")
        elif key == "CPDLC":
            self._xmit("ZWY", "CPDLC: FANS-1/A data authority — FREE TEXT / AFN (mock).", "dim")
        elif key == "SATCOM":
            self._xmit("ZWY", "SATCOM: primary oceanic voice/data these days (mock).", "dim")
        elif key == "HF":
            self._xmit("ZWY", "HF: classic oceanic voice — still the backup when sat goes ugly.", "dim")
        elif key == "ARINC":
            self._xmit("ZWY", "ARINC: ground relay / company G/G flavor (mock).", "dim")

    def _oceanic_action(self, kind: str):
        if not self._position_open:
            self._xmit("ZWY", "Oceanic panel locked — take the sector first", "yellow")
            return
        initials = self._initials or "XX"
        if kind == "uplink":
            self._oceanic_line.set("ZWY  CPDLC UPLINK  ·  CLIMB TO FL360  ·  MOCK")
            self._xmit("ZWY", f"CPDLC UPLINK — CLIMB TO FL360 REPORT LEVEL (mock)  {initials}", "green")
        elif kind == "downlink":
            self._oceanic_line.set("ZWY  ADS-C / CPDLC DOWNLINK  ·  WILCO  ·  MOCK")
            self._xmit("ZWY", "DOWNLINK — WILCO / POSITION REPORT received (mock)", "white")
        elif kind == "selcal":
            self._oceanic_line.set("ZWY  SELCAL  ·  A-B C-D  ·  HF  ·  MOCK")
            self._xmit("ZWY", "SELCAL A-B C-D — HF ring (mock). Aircraft should call.", "yellow")
            threading.Thread(target=_beep_countdown, args=(1,), daemon=True).start()
        elif kind == "hf":
            self._oceanic["HF"]["state"] = "UP"
            self._paint_oceanic_lamps()
            self._oceanic_line.set("ZWY  HF PTT  ·  TRANSMIT  ·  MOCK")
            self._xmit("ZWY", f"HF — New York Radio / ARINC family (mock). {initials}.", "orange")

    def _paint_channels(self):
        """Color the channel lamps: ACTIVE green, STANDBY amber, SPARE dim, FAULT red."""
        for ch, lab in self._ch_labels.items():
            info = self._channels[ch]
            role = info["role"]
            health = info["health"]
            if health in ("FAULT", "DEGRADED"):
                bg, fg = C["red"], C["white"]
            elif role == "ACTIVE":
                bg, fg = C["green"], "#000000"
            elif role == "STANDBY":
                bg, fg = C["orange"], "#000000"
            else:  # HOT SPARE / tertiary
                bg, fg = C["dim"], C["aqua"]
            lab.configure(
                text=self._channel_label_text(ch),
                bg=bg,
                fg=fg,
            )
            self._ch_frames[ch].configure(bg=bg)

        a = self._channels["A"]["role"]
        b = self._channels["B"]["role"]
        c = self._channels["C"]["role"]
        sync = "SYNC OK" if self._channels[self._channel_active]["health"] == "NORM" else "SYNC DEGRADED"
        self._ch_sync.configure(
            text=f"  {sync}  ·  ACTIVE={self._channel_active}  ·  "
                 f"A:{a}  B:{b}  C:{c}  ·  FAILOVER ARMED  ",
            fg=C["green"] if sync == "SYNC OK" else C["yellow"],
        )

    def _force_channel(self, ch: str):
        """Click a channel lamp — force switch (theater, dual-channel feel)."""
        if ch == self._channel_active:
            self._xmit("CHAN", f"CHANNEL {ch} already ACTIVE — no switch", "dim")
            return
        old = self._channel_active
        # Everyone else becomes standby/spare
        for name in self._channels:
            if name == ch:
                self._channels[name]["role"] = "ACTIVE"
                self._channels[name]["health"] = "NORM"
            elif name == old:
                self._channels[name]["role"] = "STANDBY"
            else:
                self._channels[name]["role"] = "HOT SPARE"
        self._channel_active = ch
        self._paint_channels()
        self._xmit(
            "CHAN",
            f"CHANNEL SWITCH  {old} → {ch}  ·  {ch} ACTIVE  ·  "
            f"{'B' if ch != 'B' else 'A'} STANDBY  ·  TERTIARY HOT SPARE",
            "yellow",
        )
        # Soft pip, not the sector ringer
        threading.Thread(target=_beep_countdown, args=(2,), daemon=True).start()

    def _channel_heartbeat(self):
        """Jitter latency numbers; rare simulated standby health blip.

        Professional-mode theater only — and never while real recovery
        work is running: a SIM fault next to a real archive.org problem
        is how interface trust dies.
        """
        if not self._pro or not self._ch_labels:
            self.root.after(3000, self._channel_heartbeat)
            return
        import random as _r
        for ch, info in self._channels.items():
            base = 11 if info["role"] == "ACTIVE" else (12 if info["role"] == "STANDBY" else 14)
            info["ms"] = base + _r.randint(0, 5)
            # Keep NORM unless we already forced a fault (don't invent drama every tick)
            if info["health"] == "DEGRADED" and _r.random() < 0.3:
                info["health"] = "NORM"
                self._xmit("CHAN", f"CHANNEL {ch} health restored — NORM (sim)", "green")
        # ~2% chance standby gets a momentary degraded flag (very NAS) —
        # but only while idle, never during a live pull/search
        if not self._busy and _r.random() < 0.02:
            stby = next((c for c, i in self._channels.items() if i["role"] == "STANDBY"), None)
            if stby:
                self._channels[stby]["health"] = "DEGRADED"
                self._xmit(
                    "CHAN",
                    f"CHANNEL {stby} STANDBY  ·  HEALTH DEGRADED (sim — not "
                    f"your pull)  ·  ACTIVE {self._channel_active} carries",
                    "orange",
                )
        try:
            self._paint_channels()
        except Exception:
            pass
        self.root.after(3000, self._channel_heartbeat)

    def _xmit(self, tag: str, msg: str, color: str = "green"):
        self.log.configure(state="normal")
        line = f" {self._zulu()}  {tag:<6} ▸ {msg}\n"
        self.log.insert(END, line, color)
        self.log.see(END)
        self.log.configure(state="disabled")

    def _set_busy(self, busy: bool):
        self._busy = busy
        z = datetime.now(timezone.utc).strftime("%H:%M:%SZ")
        if busy:
            self.status.set(
                "SQUAWK IDENT  ·  INTERROGATING WAYBACK  ·  STAND BY"
                if self._pro else
                "WORKING  ·  talking to the archive — this can take a few minutes"
            )
        elif self._position_open:
            if self._pro:
                self.status.set(
                    f"SCOPE LIVE  ·  {z}  ·  AIRSPACE/FREQUENCY YOURS  ·  {self._initials}"
                )
            else:
                self.status.set(f"READY  ·  {z}")
        else:
            self.status.set(f"LOGIN REQUIRED  ·  {z}" if self._pro else f"READY SOON  ·  {z}")

    def _name(self) -> str:
        return self.callsign.get().strip()

    def _require_position(self) -> bool:
        if not self._position_open:
            self._xmit("SYS", "POSITION CLOSED — complete login / relief first", "yellow")
            return False
        return True

    # ── INTRO (for humans) → CEDAR login → position relief gate ─────

    def _show_login_gate(self):
        """Full-glass overlay: INTRO → warning → CEDAR → countdown → yours."""
        self._gate = Frame(self.root, bg="#020402")
        self._gate.place(x=0, y=0, relwidth=1, relheight=1)
        self._gate.lift()

        # Outer border — aqua for intro, flips to red on warning plate
        self._gate_border = Frame(self._gate, bg=C["aqua"], padx=3, pady=3)
        self._gate_border.place(relx=0.5, rely=0.5, anchor="center", relwidth=0.78, relheight=0.86)

        self._gate_inner = Frame(self._gate_border, bg="#080c08")
        self._gate_inner.pack(fill=BOTH, expand=True)

        self._gate_phase = 0  # intro
        self._intro_page = 0
        self._gate_initials_var = StringVar()
        # Ambient HF / chatter bed under the intro only
        self._start_intro_radio()
        self._render_intro_page()

    # ── TRAINING gate — one calm card, then straight to work ────────

    def _show_training_gate(self):
        """Training mode front door: what this is, in plain words, once."""
        self._gate = Frame(self.root, bg="#020402")
        self._gate.place(x=0, y=0, relwidth=1, relheight=1)
        self._gate.lift()
        # Room tone under the front door too — hum, faint beeps.
        # Stops at START; never plays over real work.
        self._start_intro_radio()

        border = Frame(self._gate, bg=C["aqua"], padx=3, pady=3)
        border.place(relx=0.5, rely=0.5, anchor="center",
                     relwidth=0.62, relheight=0.72)
        inner = Frame(border, bg="#080c08")
        inner.pack(fill=BOTH, expand=True)
        self._gate_inner = inner
        self._gate_border = border

        Label(
            inner,
            text="  PAISLEY PONYTAIL  ·  WEBSHOTS PHOTO RECOVERY  ·  TRAINING MODE  ",
            bg="#000000",
            fg=C["green"],
            font=F(11, "bold"),
            anchor="w",
            pady=8,
        ).pack(fill=X)

        mid = Frame(inner, bg="#080c08")
        mid.pack(fill=BOTH, expand=True, padx=44, pady=(24, 8))

        Label(
            mid,
            text="FIND YOUR OLD WEBSHOTS PHOTOS.",
            bg="#080c08",
            fg=C["white"],
            font=F(30, "bold"),
            justify="left",
            anchor="w",
            wraplength=900,
        ).pack(fill=X, pady=(6, 22))

        Label(
            mid,
            text=(
                "Webshots was deleted in 2012. Volunteers saved a copy into "
                "the Internet Archive.\n\n"
                "This tool digs a screen name's public photos back out of "
                "that copy and saves them\n"
                "to this computer. Nothing is uploaded anywhere.\n\n"
                "Type the old screen name. Press SEARCH to look, "
                "PULL to save. That's the whole job.\n\n"
                "It only recovers what was public back then — private albums "
                "were never archived.\n"
                "Recover your own memories and your people's, and be decent "
                "with what you find."
            ),
            bg="#080c08",
            fg="#c8dcc8",
            font=F(13),
            justify="left",
            anchor="w",
        ).pack(fill=X)

        foot = Frame(inner, bg="#000000")
        foot.pack(fill=X, side="bottom")
        Label(
            foot,
            text="  Prefer the full radar-facility experience?  "
                 "PROFESSIONAL MODE — top right, any time.",
            bg="#000000",
            fg=C["dim"],
            font=F(9),
            pady=16,
            anchor="w",
        ).pack(side=LEFT, fill=X, expand=True)

        start = Label(
            foot,
            text="  START  ",
            bg=C["green"],
            fg="#000000",
            font=F(16, "bold"),
            padx=30,
            pady=14,
            cursor="hand2",
        )
        start.pack(side=RIGHT)
        start.bind("<Button-1>", lambda e: self._grant_position_training())
        self._gate.bind("<Return>", lambda e: self._grant_position_training())
        self._gate.focus_set()

    def _grant_position_training(self):
        """Training grant: the sacred ringer, four plain lines, go."""
        if self._position_open:
            return
        self._position_open = True
        self._stop_intro_radio()  # bed belongs to the door, not the work
        threading.Thread(target=_play_wav, args=(_ensure_door_chime(),), daemon=True).start()
        try:
            self._gate.destroy()
        except Exception:
            pass
        self._gate = None
        self._xmit("HELLO", "Ready. Type the old Webshots screen name in the green box.", "green")
        self._xmit("HELLO", "SEARCH looks first. PULL saves the photos to this computer.", "dim")
        self._xmit("HELLO", "Photos stay on your machine. We go gently on archive.org.", "dim")
        z = datetime.now(timezone.utc).strftime("%H:%M:%SZ")
        self.status.set(f"READY  ·  {z}  ·  type a screen name")
        self._set_instr(phase="ready", next_step="Type a screen name, then SEARCH.")
        try:
            self.entry.focus_set()
        except Exception:
            pass
        self._pulse_callsign_entry()

    def _start_intro_radio(self):
        try:
            from lib.radio_bed import start_intro_radio
            status = start_intro_radio(volume=0.16)
            self._intro_radio_status = status
        except Exception as exc:
            self._intro_radio_status = f"radio silent ({exc})"

    def _stop_intro_radio(self):
        try:
            from lib.radio_bed import stop_intro_radio
            stop_intro_radio()
        except Exception:
            pass

    def _clear_gate_inner(self):
        for w in self._gate_inner.winfo_children():
            w.destroy()

    def _render_intro_page(self):
        """Complex facility theater. Words a civilian can actually follow."""
        self._clear_gate_inner()
        self._gate_phase = 0
        try:
            self._gate_border.configure(bg=C["aqua"])
        except Exception:
            pass

        page = self._intro_page
        if page < 0 or page >= len(_INTRO_PAGES):
            self._render_gate_phase1()
            return

        eyebrow, headline, body, footer = _INTRO_PAGES[page]
        n = page + 1
        total = len(_INTRO_PAGES)

        # Heavy frame, little chrome — let the words land
        top = Frame(self._gate_inner, bg="#000000", height=36)
        top.pack(fill=X)
        top.pack_propagate(False)
        Label(
            top,
            text=f"  PPTY  ·  {n:02d}/{total:02d}  ·  SECTOR ARCHIVE  ",
            bg="#000000",
            fg=C["green"],
            font=F(11, "bold"),
            anchor="w",
        ).pack(side=LEFT, fill=Y)
        radio_on = "loop" in (getattr(self, "_intro_radio_status", "") or "")
        Label(
            top,
            text="  ◉ HF  " if radio_on else "  HF  ",
            bg="#000000",
            fg=C["green"] if radio_on else C["dim"],
            font=F(11, "bold"),
        ).pack(side=RIGHT, padx=(0, 8))
        Label(
            top,
            text="  CH A ACTIVE   B STBY   C SPARE  ",
            bg="#000000",
            fg=C["dim"],
            font=F(10),
        ).pack(side=RIGHT, fill=Y, padx=10)

        # Thin status rail — systems present, unexplained
        rail = Frame(self._gate_inner, bg="#050805", height=22)
        rail.pack(fill=X)
        rail.pack_propagate(False)
        Label(
            rail,
            text="  WAYBACK RADAR  ·  VSCS  ·  ZWY  ·  ADS-B  ·  OIS  ·  HF-STD-010A  ",
            bg="#050805",
            fg="#2a4a35",
            font=F(9),
            anchor="w",
        ).pack(fill=BOTH, expand=True)

        Label(
            self._gate_inner,
            text=eyebrow,
            bg="#080c08",
            fg=C["aqua"],
            font=F(12, "bold"),
            pady=12,
            anchor="w",
            padx=40,
        ).pack(fill=X)

        mid = Frame(self._gate_inner, bg="#080c08")
        mid.pack(fill=BOTH, expand=True, padx=48, pady=(4, 12))

        Label(
            mid,
            text=headline,
            bg="#080c08",
            fg=C["yellow"] if page >= total - 2 else C["white"],
            font=F(34, "bold"),
            justify="left",
            anchor="w",
            wraplength=1000,
        ).pack(fill=X, pady=(12, 28))

        body_box = Text(
            mid,
            bg="#080c08",
            fg="#c8dcc8",
            font=F(17),
            relief="flat",
            wrap="word",
            height=12,
            padx=8,
            pady=8,
            highlightthickness=0,
            cursor="arrow",
            spacing1=4,
            spacing3=10,
        )
        body_box.pack(fill=BOTH, expand=True)
        body_box.insert("1.0", body.strip() + "\n")
        body_box.configure(state="disabled")

        pip_row = Frame(self._gate_inner, bg="#080c08")
        pip_row.pack(fill=X, padx=40, pady=(4, 0))
        for i in range(total):
            on = i <= page
            Label(
                pip_row,
                text="●" if on else "○",
                bg="#080c08",
                fg=C["green"] if on else "#1a2e1a",
                font=F(14, "bold"),
            ).pack(side=LEFT, padx=3)

        foot = Frame(self._gate_inner, bg="#000000")
        foot.pack(fill=X, side="bottom")

        skip = Label(
            foot,
            text="  SKIP →  ",
            bg="#000000",
            fg=C["dim"],
            font=F(11),
            padx=12,
            pady=18,
            cursor="hand2",
        )
        skip.pack(side=LEFT)
        skip.bind("<Button-1>", lambda e: self._intro_skip())

        Label(
            foot,
            text=f"  {footer}",
            bg="#000000",
            fg=C["green"],
            font=F(14, "bold"),
            pady=18,
            anchor="w",
        ).pack(side=LEFT, fill=X, expand=True)

        cont = Label(
            foot,
            text="  ENTER  ",
            bg=C["green"],
            fg="#000000",
            font=F(16, "bold"),
            padx=28,
            pady=18,
            cursor="hand2",
        )
        cont.pack(side=RIGHT)
        cont.bind("<Button-1>", lambda e: self._intro_next())

        # Keyboard: Enter / space advance, Esc skips the ritual entirely
        self._gate.bind("<Return>", lambda e: self._intro_next())
        self._gate.bind("<space>", lambda e: self._intro_next())
        self._gate.bind("<Escape>", lambda e: self._intro_skip())
        self._gate.focus_set()
        # No page-turn pips — calm cues are for the countdown, the ringer
        # is for the grant, and everything else is silence (audio doctrine).

    def _intro_next(self):
        if self._gate_phase != 0:
            return
        self._intro_page += 1
        if self._intro_page >= len(_INTRO_PAGES):
            self._render_gate_phase1()
        else:
            self._render_intro_page()

    def _intro_skip(self):
        """Skippable ritual (WS3) — straight to the warning plate."""
        if self._gate_phase != 0:
            return
        self._intro_page = len(_INTRO_PAGES)
        self._render_gate_phase1()

    def _render_gate_phase1(self):
        # Leave the soft bed behind — sharp cues (chimes/ringer) take over
        self._stop_intro_radio()
        self._clear_gate_inner()
        self._gate_phase = 1
        try:
            self._gate_border.configure(bg=C["red"])
        except Exception:
            pass

        Label(
            self._gate_inner,
            text="⚠  SYSTEM CAUTION  ·  READ BEFORE PROCEEDING  ⚠",
            bg=C["red"],
            fg=C["white"],
            font=F(12, "bold"),
            pady=8,
        ).pack(fill=X)

        Label(
            self._gate_inner,
            text=f"PPTY SCOPE  ·  v{__version__}  ·  NOT FAA EQUIPMENT",
            bg="#080c08",
            fg=C["muted"],
            font=F(8),
            pady=4,
        ).pack(fill=X)

        text = Text(
            self._gate_inner,
            bg="#050805",
            fg=C["yellow"],
            font=F(10),
            relief="flat",
            wrap="word",
            height=18,
            padx=16,
            pady=12,
            highlightthickness=0,
        )
        text.pack(fill=BOTH, expand=True, padx=12, pady=8)
        text.insert("1.0", _WARNING_BODY)
        text.configure(state="disabled")

        row = Frame(self._gate_inner, bg="#080c08")
        row.pack(fill=X, padx=16, pady=(4, 16))
        Label(
            row,
            text="INITIALS  ▸",
            bg="#080c08",
            fg=C["green"],
            font=F(12, "bold"),
        ).pack(side=LEFT)
        ent = Entry(
            row,
            textvariable=self._gate_initials_var,
            bg="#0a140a",
            fg=C["white"],
            insertbackground=C["green"],
            font=F(16, "bold"),
            width=8,
            relief="flat",
            highlightthickness=1,
            highlightbackground=C["red"],
            highlightcolor=C["green"],
        )
        ent.pack(side=LEFT, padx=10, ipady=6)
        ent.focus_set()
        ent.bind("<Return>", lambda e: self._gate_accept_phase1())
        Label(
            row,
            text="  ENTER TO ACKNOWLEDGE",
            bg="#080c08",
            fg=C["muted"],
            font=F(9),
        ).pack(side=LEFT)

    def _gate_accept_phase1(self):
        initials = self._gate_initials_var.get().strip().upper()
        if len(initials) < 1 or len(initials) > 4:
            messagebox.showwarning(
                "INITIALS REQUIRED",
                "Type 1–4 characters (your initials) and press Enter.",
            )
            return
        self._initials = initials
        self._render_gate_phase2_loading()

    def _render_gate_phase2_loading(self):
        """Fetch live METAR + NAS/OIS while painting the relief board."""
        self._clear_gate_inner()
        self._gate_phase = 2
        self._gate_initials_var.set("")

        Label(
            self._gate_inner,
            text="CEDAR LOGIN APPROVAL GRANTED TO LEVEL 2",
            bg=C["aqua"],
            fg="#000000",
            font=F(12, "bold"),
            pady=6,
        ).pack(fill=X)
        Label(
            self._gate_inner,
            text="SECTOR POSITION RELIEF BRIEFING UNDERWAY  ·  PULLING LIVE SIA…",
            bg="#080c08",
            fg=C["yellow"],
            font=F(11, "bold"),
            pady=8,
        ).pack(fill=X)
        Label(
            self._gate_inner,
            text="METAR ← aviationweather.gov    TM/OIS ← nasstatus.faa.gov / fly.faa.gov/ois",
            bg="#080c08",
            fg=C["muted"],
            font=F(9),
        ).pack(fill=X)
        self._relief_status = Label(
            self._gate_inner,
            text="SQUAWK IDENT — interrogating weather & traffic flow…",
            bg="#080c08",
            fg=C["green"],
            font=F(12),
            pady=40,
        )
        self._relief_status.pack(expand=True)

        def worker():
            try:
                from lib.nas_brief import build_live_brief
                board = build_live_brief(initials=self._initials, version=__version__)
                self._q.put(("relief_board", board, None))
            except Exception as exc:
                self._q.put(("relief_board", f"BRIEFING DEGRADED\n{exc}\n\nTYPE INITIALS TO CONTINUE.", None))

        threading.Thread(target=worker, daemon=True).start()

    def _render_gate_phase2_board(self, board_text: str):
        self._clear_gate_inner()
        self._gate_phase = 2
        self._gate_initials_var.set("")
        self._relief_board_text = board_text

        Label(
            self._gate_inner,
            text="CEDAR  ·  LEVEL 2  ·  POSITION RELIEF BRIEFING  ·  JO 7110.65 APP A",
            bg=C["aqua"],
            fg="#000000",
            font=F(11, "bold"),
            pady=6,
        ).pack(fill=X)
        Label(
            self._gate_inner,
            text=f"LOGIN {self._initials}  ·  PPTY SECTOR ARCHIVE  ·  "
                 f"OIS https://www.fly.faa.gov/ois/?legacy=true",
            bg="#080c08",
            fg=C["muted"],
            font=F(8),
            pady=4,
        ).pack(fill=X)

        text = Text(
            self._gate_inner,
            bg="#050805",
            fg=C["green"],
            font=F(9),
            relief="flat",
            wrap="none",
            padx=10,
            pady=8,
            highlightthickness=1,
            highlightbackground=C["dim"],
        )
        text.pack(fill=BOTH, expand=True, padx=10, pady=6)
        text.insert("1.0", board_text)
        text.configure(state="disabled")
        # color-ish headers via tags is hard on full dump; green is fine

        row = Frame(self._gate_inner, bg="#080c08")
        row.pack(fill=X, padx=12, pady=(4, 12))
        Label(
            row,
            text="ACCEPT SECTOR  ▸",
            bg="#080c08",
            fg=C["aqua"],
            font=F(11, "bold"),
        ).pack(side=LEFT)
        ent = Entry(
            row,
            textvariable=self._gate_initials_var,
            bg="#0a140a",
            fg=C["white"],
            insertbackground=C["aqua"],
            font=F(16, "bold"),
            width=8,
            relief="flat",
            highlightthickness=1,
            highlightbackground=C["aqua"],
            highlightcolor=C["green"],
        )
        ent.pack(side=LEFT, padx=10, ipady=6)
        ent.focus_set()
        ent.bind("<Return>", lambda e: self._gate_accept_phase2())
        Label(
            row,
            text="  RE-TYPE INITIALS + ENTER  ·  YOU HAVE READ THE BRIEF",
            bg="#080c08",
            fg=C["yellow"],
            font=F(9, "bold"),
        ).pack(side=LEFT)

        btn_row = Frame(self._gate_inner, bg="#080c08")
        btn_row.pack(fill=X, padx=12, pady=(0, 10))
        for label, url in (
            ("OPEN OIS (fly.faa.gov)", "https://www.fly.faa.gov/ois/?legacy=true"),
            ("NAS STATUS", "https://nasstatus.faa.gov/"),
            ("AVIATION WEATHER", "https://aviationweather.gov/"),
        ):
            def _open(u=url):
                webbrowser.open(u)
            b = Label(
                btn_row, text=f"  {label}  ", bg=C["dim"], fg=C["white"],
                font=F(8, "bold"), cursor="hand2", padx=4, pady=4,
            )
            b.bind("<Button-1>", lambda e, u=url: webbrowser.open(u))
            b.pack(side=LEFT, padx=4)

    def _gate_accept_phase2(self):
        again = self._gate_initials_var.get().strip().upper()
        if again != self._initials:
            messagebox.showwarning(
                "INITIALS MISMATCH",
                f"Type the same initials again ({self._initials}) to accept the sector.",
            )
            self._gate_initials_var.set("")
            return
        self._render_gate_countdown()

    def _render_gate_countdown(self):
        self._clear_gate_inner()
        self._gate_phase = 3

        Label(
            self._gate_inner,
            text="POSITION TRANSFER  ·  STAND BY",
            bg=C["green"],
            fg="#000000",
            font=F(11, "bold"),
            pady=8,
        ).pack(fill=X)

        self._count_label = Label(
            self._gate_inner,
            text="",
            bg="#080c08",
            fg=C["green"],
            font=F(96, "bold"),
        )
        self._count_label.pack(expand=True)

        self._count_sub = Label(
            self._gate_inner,
            text="TRANSFERRING SECTOR RESPONSIBILITY…",
            bg="#080c08",
            fg=C["muted"],
            font=F(11),
            pady=16,
        )
        self._count_sub.pack()

        self._countdown_n = 3
        self.root.after(400, self._countdown_tick)

    def _countdown_tick(self):
        n = self._countdown_n
        if n > 0:
            self._count_label.configure(text=str(n))
            # Cool ~300 Hz sine only — ARTCC ding comes on INITIAL grant
            threading.Thread(target=_beep_countdown, args=(n,), daemon=True).start()
            self._countdown_n -= 1
            self.root.after(850, self._countdown_tick)
            return
        self._grant_position()

    def _grant_position(self):
        self._clear_gate_inner()
        self._gate_phase = 4

        Label(
            self._gate_inner,
            text="",
            bg="#080c08",
        ).pack(expand=True)

        Label(
            self._gate_inner,
            text="AIRSPACE / FREQUENCY ARE YOURS",
            bg="#080c08",
            fg=C["green"],
            font=F(28, "bold"),
        ).pack()

        Label(
            self._gate_inner,
            text=f"POSITION ASSUMED  ·  {self._initials}  ·  LEVEL 2  ·  SECTOR ARCHIVE",
            bg="#080c08",
            fg=C["aqua"],
            font=F(12),
            pady=12,
        ).pack()

        Label(
            self._gate_inner,
            text="YOU HAVE THE POSITION",
            bg="#080c08",
            fg=C["white"],
            font=F(14, "bold"),
            pady=8,
        ).pack()

        Label(
            self._gate_inner,
            text="Good luck.  We're all counting on you.",
            bg="#080c08",
            fg=C["aqua"],
            font=F(18, "bold"),
            pady=14,
        ).pack()

        Label(
            self._gate_inner,
            text="",
            bg="#080c08",
        ).pack(expand=True)

        # Classic DING DONG door chime (not an alarm)
        threading.Thread(target=_play_wav, args=(_ensure_door_chime(),), daemon=True).start()

        self._position_open = True
        self.root.after(2200, self._dismiss_gate)

    def _dismiss_gate(self):
        self._stop_intro_radio()
        try:
            self._gate.destroy()
        except Exception:
            pass
        self._gate = None
        z = datetime.now(timezone.utc).strftime("%H:%M:%SZ")
        self.status.set(
            f"SCOPE LIVE  ·  {z}  ·  AIRSPACE/FREQUENCY YOURS  ·  {self._initials}"
        )
        self._xmit("SYS", "PPTY SCOPE ONLINE — HF-STD-010A PALETTE LOADED", "aqua")
        self._xmit("CEDAR", f"LOGIN LEVEL 2  ·  {self._initials}  ·  POSITION OPEN", "aqua")
        self._xmit("SEC", f"SECTOR {_OUR_SECTOR}  —  airspace/frequency are yours", "green")
        self._xmit("RELIEF", "YOU HAVE THE POSITION", "green")
        self._xmit(
            "GND",
            "You are at the busiest air traffic control radar facility on the planet.",
            "white",
        )
        self._xmit(
            "GND",
            "Your traffic is deleted family photos. The only person who can save them is you.",
            "yellow",
        )
        self._xmit("GND", "Good luck. We're all counting on you.", "aqua")
        self._xmit("TRNG", _MANTRA_SHORT, "yellow")
        self._xmit(
            "TRNG",
            "Priorities do not move. Plan A. Plan B. An out. Go around if you have to.",
            "dim",
        )
        self._xmit("RELIEF", "App A complete: PREVIEW · VERBAL BRIEF · ASSUME · (REVIEW ongoing)", "dim")
        self._xmit("WX", "Live METAR + NAS/OIS pulled for brief — refresh on timer", "aqua")
        self._xmit("TM", "OIS board: https://www.fly.faa.gov/ois/?legacy=true", "aqua")
        self._xmit("SYS", f"WAYBACK RADAR  ·  v{__version__}  ·  GUEST RATE ~1/S", "dim")
        self._xmit("SYS", ">>> ENTER SCREEN NAME IN THE GREEN BOX  ·  THEN SEARCH OR PULL <<<", "yellow")
        # Dump key lines of the brief into comms (weather + TFM)
        board = getattr(self, "_relief_board_text", "") or ""
        for line in board.splitlines():
            s = line.strip()
            if s.startswith("KJFK") or s.startswith("KLGA") or s.startswith("KEWR") or s.startswith("KISP") or s.startswith("KTEB"):
                self._xmit("METAR", s, "yellow")
            if s.startswith("· ") and any(x in s for x in ("DELAY", "STOP", "GDP", "JFK", "EWR", "LGA", "DCA")):
                self._xmit("OIS", s[2:90], "orange")
        try:
            self.entry.focus_set()
        except Exception:
            pass
        self._pulse_callsign_entry()
        self.root.after(500, self._refresh_wx_strip)
        self.root.after(5 * 60 * 1000, self._schedule_wx_refresh)
        # Kick live ADS-B the moment the sector opens
        self._xmit(
            "CHAN",
            f"CHANNEL A ACTIVE  ·  CHANNEL B STANDBY  ·  CHANNEL C HOT SPARE (tertiary)",
            "green",
        )
        self._xmit(
            "CHAN",
            "DUAL-CHANNEL SYNC OK  ·  FAILOVER ARMED  ·  click a channel lamp to switch",
            "dim",
        )
        self._xmit(
            "VSCS",
            "VOICE SWITCH ONLINE — landline/interphone panel armed (MOCK G/G)",
            "aqua",
        )
        self._xmit(
            "VSCS",
            "Key a sector (JFK TWR, ZNY, ATCSCC…) — LINE CLEAR? then go ahead",
            "dim",
        )
        self._xmit(
            "ZWY",
            "NEW YORK OCEANIC — ADS-C LOGGED ON · CPDLC ACTIVE · SATCOM UP · HF STBY",
            "aqua",
        )
        self._xmit(
            "ZWY",
            "ZWY panel armed (mock) — click ADS-C/CPDLC/SATCOM/HF/ARINC or SELCAL",
            "dim",
        )
        if self._adsb_on:
            self._xmit(
                "SURV",
                "LIVE ADS-B ARMED — adsb.lol primary / OpenSky fallback · N90 theater",
                "aqua",
            )
            self.root.after(800, self._poll_adsb)
        self._set_instr(
            phase="IDLE", next_step="Enter a screen name, then SEARCH or PULL.",
        )

    def _schedule_wx_refresh(self):
        if self._position_open and self._pro:
            self._refresh_wx_strip()
        self.root.after(5 * 60 * 1000, self._schedule_wx_refresh)

    def _refresh_wx_strip(self):
        if not self._pro:
            return

        def worker():
            try:
                from lib.nas_brief import fetch_metars, fetch_nas_status, _event_blurb
                metars = fetch_metars()
                nas = fetch_nas_status()
                parts = [f"{m['id']}:{m.get('fltCat', '?')}" for m in metars[:5]]
                active = 0
                for ev in nas.get("airport_events") or []:
                    if _event_blurb(ev):
                        active += 1
                strip = (
                    f"WX {' '.join(parts)}  ·  "
                    f"TM {active} airport events  ·  "
                    f"OIS fly.faa.gov/ois"
                )
                self._q.put(("wx_strip", strip, None))
            except Exception as exc:
                self._q.put(("wx_strip", f"WX/TM UNAVAILABLE ({exc})", None))

        threading.Thread(target=worker, daemon=True).start()

    def _apply_wx_strip(self, strip: str):
        z = datetime.now(timezone.utc).strftime("%H:%M:%SZ")
        if self._position_open and not self._busy:
            self.status.set(
                f"SCOPE LIVE  ·  {z}  ·  {self._initials}  ·  {strip}"
            )
        self._xmit("SIA", strip[:120], "dim")

    # ── worker bridge ───────────────────────────────────────────────

    def _run_async(self, coro_factory, on_done_msg: str | None = None):
        if self._busy:
            self._xmit("TWR", "UNABLE — already working traffic", "yellow")
            return

        def worker():
            try:
                result = asyncio.run(coro_factory())
                self._q.put(("ok", result, on_done_msg))
            except Exception as exc:
                self._q.put(("err", str(exc), None))

        self._set_busy(True)
        threading.Thread(target=worker, daemon=True).start()

    def _drain_queue(self):
        try:
            while True:
                kind, payload, msg = self._q.get_nowait()
                if kind == "relief_board":
                    # Mode may have flipped while the fetch was in flight
                    if self._pro and getattr(self, "_gate", None) is not None:
                        self._render_gate_phase2_board(str(payload))
                    continue
                if kind == "wx_strip":
                    self._apply_wx_strip(payload)
                    continue
                if kind == "adsb":
                    self._apply_adsb(payload if isinstance(payload, dict) else {})
                    continue
                if kind == "mission_start":
                    self._mission = {}
                    self._mission_order = []
                    self._mission_sweep = True
                    continue
                if kind == "album_found":
                    aid, title, n = payload
                    xf, yf = self._mission_place(len(self._mission_order))
                    self._mission[aid] = {
                        "title": (title or aid)[:14].upper(), "n": n,
                        "done": 0, "state": "flash", "xf": xf, "yf": yf,
                    }
                    self._mission_order.append(aid)
                    continue
                if kind == "mission_board":
                    self._mission_sweep = False
                    continue
                if kind == "mission_photo":
                    t = self._mission.get(payload)
                    if t:
                        t["done"] += 1
                        t["state"] = "solid"
                    continue
                if kind == "phase":
                    name, info = payload
                    self._phase = name
                    if name in ("RECON", "SCAN"):
                        self._mission_sweep = True
                    else:
                        self._mission_sweep = False
                    if name == "PULL":
                        for t in self._mission.values():
                            t["state"] = "solid"
                        self._pull_total = info.get("total", 0)
                        self._pull_board = info.get("albums", 0)
                        self._set_instr(
                            phase="PULL — landing photos" if self._pro
                            else "saving photos",
                            board=str(self._pull_board),
                            next_step="Nothing — photos are landing. The "
                            "gallery opens when they're home.",
                        )
                    elif name == "RECON":
                        self._set_instr(
                            phase="RECON — interrogating CDX" if self._pro
                            else "checking the archive",
                        )
                    elif name == "SCAN":
                        self._set_instr(
                            phase="SCAN — building the board" if self._pro
                            else "listing the albums",
                        )
                    elif name == "DONE":
                        self._set_instr(
                            phase="COMPLETE" if self._pro else "done",
                        )
                    continue
                if kind == "photo":
                    self._apply_photo_event(payload)
                    continue
                self._set_busy(False)
                if kind == "err":
                    self._xmit("ERR", payload[:200], "red")
                    self.status.set("MISSED APCH  ·  SEE COMMS LOG")
                else:
                    if callable(payload):
                        payload()  # UI callback scheduled from worker as lambda
                    if msg:
                        self._xmit("TWR", msg, "green")
        except queue.Empty:
            pass
        self.root.after(100, self._drain_queue)

    def _apply_photo_event(self, record: dict):
        """One photo landed/missed — instruments move, comms stay calm."""
        variant = record.get("variant")
        if variant == "skip":
            f = (record.get("file") or "").lower()
            variant = "fs" if f.endswith("_fs.jpg") else (
                "th" if f.endswith("_th.jpg") else "ph"
            )
        if variant in ("fs", "ph", "th"):
            self._pull_counts[variant] += 1
        elif variant == "failed":
            self._pull_counts["failed"] += 1
            # First few misses get a line with the reason; then we stop
            # narrating and let the summary carry it (no comms flood).
            if self._pro and self._missed_logged < 12:
                self._missed_logged += 1
                self._xmit(
                    "MISS",
                    f"MISSED APCH  {record.get('id') or '?'}  ·  "
                    f"{record.get('reason') or 'not recoverable'}",
                    "dim",
                )
        done = sum(self._pull_counts.values())
        landed = self._fmt_landed()
        if self._pull_total:
            landed += (
                f"   ({done}/{self._pull_total})" if self._pro
                else f"   — {done} of {self._pull_total} checked"
            )
        self._set_instr(
            landed=landed,
            missed=str(self._pull_counts["failed"]) if self._pro else (
                f"{self._pull_counts['failed']} were never archived"
                if self._pull_counts["failed"] else "none so far"
            ),
        )

    # ── operations ──────────────────────────────────────────────────

    def _on_search(self):
        if not self._require_position():
            return
        name = self._name()
        if not name:
            self._xmit("CDY", "SAY CALLSIGN — enter a screen name", "yellow")
            self._set_instr(next_step="Type a screen name first.")
            return
        if " " in name:
            self._on_find()
            return
        self._xmit("RECON", f"Target {name} — interrogating CDX", "aqua")
        self._set_truth(None)
        # New interrogation: clear the mission board, start the sweep
        self._mission = {}
        self._mission_order = []
        self._mission_sweep = True
        self._set_instr(
            target=name,
            phase="RECON" if self._pro else "checking the archive",
            board="—", landed="—", missed="—",
            next_step="Stand by — asking the archive.",
        )

        def factory():
            async def job():
                cfg = Config()
                async with Engine(cfg) as engine:
                    self._live_engine = engine
                    try:
                        url = f"community.webshots.com/user/{name}"
                        rows = await engine.cdx_search(url)
                        if rows is None:
                            wx = weather_state(engine.last_status, engine.last_nid)
                            state = wx or TRUTH["ATC_ZERO"]
                            return lambda: (
                                self._set_truth(state),
                                self._set_instr(
                                    phase="—",
                                    next_step=state.action,
                                ),
                                self.status.set(f"{state.callout}  ·  {name}"),
                            )
                        if not rows:
                            return lambda: (
                                self._set_truth(TRUTH["NO_PLAN"]),
                                self._set_instr(
                                    phase="—",
                                    next_step=TRUTH["NO_PLAN"].action,
                                ),
                                self.status.set(f"NO BEACONS  ·  {name}"),
                            )
                        ts = rows[-1][1]
                        _, html = await engine.load_profile(name, ts)
                        albums = []
                        if html:
                            albums = engine.extract_albums(html)
                        # light page follow
                        if html:
                            for page_url in list(engine.extract_profile_pages(html, name))[:5]:
                                page_html = await engine.load_page(page_url, ts)
                                if page_html:
                                    for a in engine.extract_albums(page_html):
                                        if a[2] not in {x[2] for x in albums}:
                                            albums.append(a)
                        if not albums:
                            return lambda: (
                                self._set_truth(TRUTH["ZERO_ALBUMS"]),
                                self._set_instr(
                                    phase="—", board="0",
                                    next_step=TRUTH["ZERO_ALBUMS"].action,
                                ),
                                self.status.set(f"NO TARGETS  ·  {name}"),
                            )
                        counts = []
                        total = 0
                        for aurl, cat, aid in albums[:40]:
                            entries, meta = await engine.load_album(aurl, ts)
                            n = len(entries)
                            total += n
                            title = meta.get("title") or cat
                            counts.append((title, aid, n))
                            # each counted album pops onto the glass, flashing
                            self._q.put(("album_found", (aid, title, n), None))
                        self._last_albums = counts
                        self._last_user = name
                    finally:
                        self._live_engine = None
                        self._q.put(("mission_board", None, None))

                    def ui():
                        self._xmit(
                            "RECON",
                            f"IDENT — {len(rows)} beacons  ·  {len(albums)} albums  ·  ~{total} photos",
                            "green",
                        )
                        hollow = sum(1 for _t, _a, n in counts if n == 0)
                        for title, aid, n in counts[:15]:
                            self._xmit(
                                "STRIP",
                                f"{title[:28]:<28}  {aid[:16]}  "
                                f"{n if n else 'NO TARGETS'} "
                                f"{'photos' if n else ''}",
                                "white" if n else "dim",
                            )
                        if len(counts) > 15:
                            self._xmit("STRIP", f"… {len(counts) - 15} more strips not shown", "dim")
                        if hollow:
                            self._xmit(
                                "SCAN",
                                f"{hollow} album(s) listed but empty at this "
                                "snapshot — they don't count toward the pull",
                                "dim",
                            )
                        rmk = remark_for(load_remarks(), name)
                        if rmk:
                            self._xmit("RMK", rmk, "orange")
                        self._xmit("TWR", "CLEARED FOR PULL when ready", "green")
                        self.status.set(f"RADAR CONTACT  ·  {name}  ·  {total} PHOTOS ON STRIP")
                        self._set_instr(
                            phase="board ready" if not self._pro else "BOARD READY",
                            board=f"{len(albums)}"
                            + (f" ({hollow} empty)" if hollow else ""),
                            landed="—",
                            next_step=f"PULL saves all ~{total} photos to "
                            "this computer.",
                        )

                    return ui

            return job()

        self._run_async(factory)

    def _on_pull(self, deep: bool = False):
        if not self._require_position():
            return
        name = self._name()
        if not name or " " in name:
            self._xmit("CDY", "Need a single screen name to pull", "yellow")
            self._set_instr(next_step="Type a single screen name first.")
            return
        self._xmit(
            "PULL",
            f"{'DEEP ' if deep else ''}CLEARED TO LAND — recovering {name}",
            "magenta" if deep else "green",
        )
        self._set_truth(None)
        self._pull_counts = {"fs": 0, "ph": 0, "th": 0, "failed": 0}
        self._missed_logged = 0
        self._pull_total = 0
        self._pull_board = 0
        self._set_instr(
            target=name,
            phase="RECON" if self._pro else "checking the archive",
            board="—", landed="0", missed="0" if self._pro else "none so far",
            next_step="Stand by — this runs at the archive's guest rate.",
        )

        def factory():
            async def job():
                # Import here to avoid circular import at module load
                from resurrector import cmd_pull

                cfg = Config()
                cfg.max_concurrent = 4
                out = "output"
                stats = Stats()
                self._live_stats = stats
                try:
                    async with Engine(cfg) as engine:
                        self._live_engine = engine
                        await cmd_pull(
                            name, engine, out, deep=deep, no_open=True,
                            stats=stats,
                            on_photo=lambda rec, alb: (
                                self._q.put(("photo", rec, None)),
                                self._q.put(
                                    ("mission_photo", (alb or {}).get("id"), None)
                                ),
                            ),
                            on_phase=lambda ph, **info: self._q.put(("phase", (ph, info), None)),
                        )
                finally:
                    self._live_engine = None
                    self._live_stats = None

                hangar = os.path.join(out, name)
                gallery = os.path.join(hangar, "gallery.html")
                grade = "?"
                n = 0
                counts = {"fs": 0, "ph": 0, "th": 0, "failed": 0}
                interrupted = False
                hangar_full = False
                try:
                    import json
                    with open(os.path.join(hangar, "manifest.json"), encoding="utf-8") as f:
                        man = json.load(f)
                    albums = man.get("albums") or []
                    grade = man.get("grade") or grade_from_albums(albums)[0]
                    interrupted = bool(man.get("interrupted"))
                    vc = count_variants(albums)
                    counts = {k: vc.get(k, 0) for k in ("fs", "ph", "th", "failed")}
                    counts["transport"] = sum(
                        1 for a in albums for p in a.get("photos") or []
                        if p.get("variant") == "failed"
                        and p.get("reason") == "transport"
                    )
                    hangar_full = any(
                        p.get("reason") == "disk_full"
                        for a in albums for p in a.get("photos") or []
                    )
                    n = sum(
                        1 for a in albums
                        for p in a.get("photos") or []
                        if p.get("file")
                    )
                except Exception:
                    pass

                def ui():
                    self._last_user = name
                    truth = classify_recovery(
                        counts, interrupted=interrupted, hangar_full=hangar_full
                    )
                    report = mission_report(counts)
                    self._xmit(
                        "PULL",
                        f"{truth.callout} — {n} photos  ·  grade {grade}",
                        "green" if truth.tone == "ok" else (
                            "yellow" if truth.tone == "caution" else "red"
                        ),
                    )
                    self._xmit("PULL", report, "dim")
                    self._set_truth(truth, extra=report)
                    self._set_instr(
                        phase="COMPLETE" if self._pro else "done",
                        landed=self._fmt_landed(),
                        missed=str(counts["failed"]) if self._pro else (
                            _missed_plain(counts)
                        ),
                        next_step=truth.action,
                    )
                    if truth.tone == "ok" and self._pro:
                        self._xmit("GND", f"{_OUR_SECTOR}  ·  They were counting on you.", "aqua")
                    self.status.set(
                        f"{truth.callout}  ·  {name}  ·  {grade}"
                    )
                    if os.path.isfile(gallery) and n:
                        self._xmit("GND", f"Contact sheet ready: {gallery}", "aqua")
                        try:
                            os.startfile(os.path.abspath(gallery))  # type: ignore[attr-defined]
                        except Exception:
                            webbrowser.open("file:///" + os.path.abspath(gallery).replace("\\", "/"))
                        self._xmit("GND", "Gallery opened — those are your photos back", "green")

                return ui

            return job()

        self._run_async(factory)

    def _on_deep_pull(self):
        self._on_pull(deep=True)

    def _on_find(self):
        if not self._require_position():
            return
        q = self._name()
        if len(q.replace(" ", "")) < 2:
            self._xmit("SWEEP", "Need at least 2 characters to sweep", "yellow")
            return
        self._xmit("SWEEP", f"Scanning frequency for {q}*", "aqua")

        def factory():
            async def job():
                from resurrector import _prefix_variants

                cfg = Config()
                async with Engine(cfg) as engine:
                    merged = {}
                    for v in _prefix_variants(q):
                        result = await engine.find_usernames(v)
                        if result is None:
                            return lambda: self._xmit("SWEEP", "Radar down / flow control", "red")
                        found, _ = result
                        for r in found:
                            merged[r["name"].lower()] = r
                    ranked = sorted(merged.values(), key=lambda r: (-r["pages"], r["name"].lower()))

                    def ui():
                        if not ranked:
                            self._xmit("SWEEP", "No beacons on that frequency", "red")
                            return
                        self._xmit("SWEEP", f"{len(ranked)} callsigns on frequency", "green")
                        for i, r in enumerate(ranked[:20], 1):
                            self._xmit(
                                "STRIP",
                                f"{i:02d}  {r['name']:<20}  pages={r['pages']}  "
                                f"{r['first'][:8]}..{r['last'][:8]}",
                                "white",
                            )
                        self._xmit("TWR", "Click a name into the callsign box, then SEARCH", "dim")
                        if ranked:
                            self.callsign.set(ranked[0]["name"])

                    return ui

            return job()

        self._run_async(factory)

    def _on_gallery(self):
        if not self._require_position():
            return
        name = self._name() or self._last_user
        if not name:
            self._xmit("GND", "No hangar selected", "yellow")
            return
        path = os.path.abspath(os.path.join("output", name, "gallery.html"))
        if not os.path.isfile(path):
            self._xmit("GND", f"No gallery yet for {name} — PULL first", "yellow")
            return
        try:
            os.startfile(path)  # type: ignore[attr-defined]
        except Exception:
            webbrowser.open("file:///" + path.replace("\\", "/"))
        self._xmit("GND", f"Opened {path}", "aqua")

    def run(self):
        self.root.mainloop()


def main():
    app = ScopeApp()
    app.run()


if __name__ == "__main__":
    main()
