"""Terminal display layer for Webshots Resurrector.

Tower-cab aesthetic: Zulu-clock comms log, flight strips, radar-green
scope colors.  Every line still says what it means — jargon decorates,
it never obscures.
"""

import sys
from datetime import datetime, timezone

# Windows consoles default to a legacy codepage (cp1252) that can't encode
# the banner's block glyphs; force UTF-8 before rich binds to the streams.
if sys.platform == "win32":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.progress import (
    Progress,
    BarColumn,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)
from rich.spinner import SPINNERS
from rich.theme import Theme

from lib import __version__

# Distant-traffic anti-collision strobe: quick double-pulse, then dark.
# Runs as the spinner wherever the tool is working — like watching a
# far-off aircraft hold over the water at night.
SPINNERS["strobe"] = {
    "interval": 100,
    "frames": ["✸", "✦", "·", " ", "✸", "✦", "·", " ",
               " ", " ", " ", " ", " ", " ", " ", " "],
}

# FAA HF-STD-010 standard color palette for ATC displays, as evaluated on
# ERAM/STARS in DOT/FAA/AM-20/08 (Table 2, sRGB).  This terminal is,
# colorimetrically, a certified radar scope.
HF = {
    "white": "#FFFFFF",
    "pink": "#F684D8",
    "gray": "#B3B3B3",
    "blue": "#5E8DF6",
    "orange": "#FE930D",
    "red": "#FF1320",
    "green": "#23E162",
    "yellow": "#DFF334",
    "magenta": "#D822FF",
    "aqua": "#07CDED",
    "brown": "#C5955B",
}

THEME = Theme(
    {
        "phase": f"bold {HF['green']}",
        "ok": f"bold {HF['green']}",
        "warn": f"bold {HF['yellow']}",
        "err": f"bold {HF['red']}",
        "dim": "dim",
        "target": f"bold {HF['white']}",
        "heading": f"bold {HF['white']}",
        "scope": HF["green"],
        "amber": HF["orange"],
        "zulu": f"dim {HF['green']}",
        "strip": f"bold black on {HF['green']}",
        "brand": f"bold {HF['white']}",
        "deep": f"bold {HF['magenta']}",
        "ident": f"bold {HF['aqua']}",
        # Sectional-chart backdrop: barely-there green, under the black.
        "chart": "#20362a",
        "chartlabel": "#2e4b36",
    }
)

console = Console(theme=THEME, highlight=False)

VERSION = __version__


def _zulu() -> str:
    """Tower clock — every transmission gets a Zulu timestamp."""
    return datetime.now(timezone.utc).strftime("%H:%M:%SZ")


# ── Banner ──────────────────────────────────────────────────────────────

LOGO_PAISLEY = (
    "  [phase]█▀█ █▀█ █ █▀▀ █   █▀▀ █ █[/]\n"
    "  [phase]█▀▀ █▀█ █ ▀▀█ █   █▀▀ ▀█▀[/]\n"
    "  [phase]▀   ▀ ▀ ▀ ▀▀▀ ▀▀▀ ▀▀▀  ▀ [/]"
)

LOGO_PONYTAIL = (
    "  [brand]█▀█ █▀█ █▀█ █ █ ▀█▀ █▀█ █ █  [/]\n"
    "  [brand]█▀▀ █ █ █ █ ▀█▀  █  █▀█ █ █  [/]\n"
    "  [brand]▀   ▀▀▀ ▀ ▀  ▀   ▀  ▀ ▀ ▀ ▀▀▀[/]"
)

SCANLINE = "[zulu]" + "▔" * 60 + "[/]"

# Video map, N90 style: Long Island's south shore with the W-105/106
# warning areas off the coast, drawn the way STARS draws the world —
# faint lines under the black that you stop seeing until you need them.
# Fixes are real: DPK, ISP, CCC, HTO up the island; CAMRN, SHIPP, MONEY
# over the water; Y483 running oceanic.  ✦ is distant traffic.
VIDEOMAP = (
    "  [chart] ∙LGA                  LONG ISLAND[/]\n"
    "  [chart]∙JFK˙·¸¸.·‾‾·¸¸ ∙DPK ¸¸.·‾‾‾·¸¸ ∙ISP ¸.·‾‾·¸ ∙HTO ¸¸.·˙MONTK[/]\n"
    "  [chart]   ∙CAMRN          ∙SHIPP            ∙MONEY            ˙✦[/]\n"
    "  [chart]   ╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍  Y483 ⟶[/]\n"
    "  [chart]   ╏    [/][chartlabel]W-105A[/][chart]     ╏     [/]"
    "[chartlabel]W-105B[/][chart]     ╏    [/][chartlabel]W-106[/][chart]   ╏[/]\n"
    "  [chart]   ╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍[/]"
)


def show_banner():
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%MZ")
    body = (
        f"{LOGO_PAISLEY}\n"
        f"{LOGO_PONYTAIL}\n\n"
        f"  {SCANLINE}\n"
        f"  [scope]THE WEBSHOTS RESURRECTOR ▪ ARCHIVE PHOTO RECOVERY[/]"
        f"  [dim]│[/]  [scope]v{VERSION}[/]\n"
        f"  [dim]2,437 MEGAWARCS ON FREQUENCY ▪ 105.9 TB ▪"
        f" WAYBACK RADAR ONLINE[/]\n"
        f"  {SCANLINE}\n"
        f"  [brand]TAILSTRIKE STUDIOS[/] [dim]×[/] [brand]ASH AIRFOIL[/]"
        f" [dim]// coldbricks // {now}[/]\n\n"
        f"{VIDEOMAP}"
    )
    console.print()
    console.print(
        Panel(body, border_style=HF["green"], box=box.DOUBLE, padding=(1, 1))
    )
    console.print()


# ── Comms log ───────────────────────────────────────────────────────────
#
#  Every line reads like a tower transmission:
#    21:04:11Z  RECON  ▸ radar contact: bexbee12


def _xmit(style: str, tag: str, msg: str):
    console.print(f" [zulu]{_zulu()}[/]  [{style}]{tag:<5}[/] [dim]▸[/] {msg}")


def phase(tag, msg):
    # DEEP wears TRACON magenta (special condition); SWEEP wears beacon aqua.
    style = {"DEEP": "deep", "SWEEP": "ident"}.get(tag, "phase")
    _xmit(style, tag, msg)


def success(tag, msg):
    _xmit("ok", tag, msg)


def warn(tag, msg):
    _xmit("warn", tag, msg)


def fail(tag, msg):
    _xmit("err", tag, msg)


def detail(msg):
    console.print(f"                    {msg}")


def ident_status(target):
    """Blinking SQUAWK IDENT while we interrogate the archive's radar.

    Terminals without blink support render it steady — still correct,
    just less fun.
    """
    return console.status(
        f"[blink ident]■ SQUAWK IDENT ■[/] "
        f"[dim]interrogating[/] [target]{target}[/] [dim]— awaiting reply[/]",
        spinner="strobe",
        spinner_style=HF["white"],
    )


# ── Download callouts ───────────────────────────────────────────────────
#
#  fs  = full-size original landed        → LANDED  FS
#  ph  = 800x600 fallback landed          → LANDED  PH
#  skip = already on disk                 → AT GATE
#  fail = both variants unrecoverable     → MISSED APCH


def dl_ok(variant, size, filename):
    if variant == "fs":
        v = "[ok]LANDED  FS[/]"
    else:
        v = "[amber]LANDED  PH[/]"
    console.print(
        f" [zulu]{_zulu()}[/]   {v}  {size:>9,}B  [dim]{filename}[/]"
    )


def dl_skip(filename):
    console.print(
        f" [zulu]{_zulu()}[/]   [dim]AT GATE      already on disk  {filename}[/]"
    )


def dl_thumb(size, filename):
    console.print(
        f" [zulu]{_zulu()}[/]   [amber]THUMB ONLY[/]  {size:>9,}B  [dim]{filename}  "
        f"(full image never archived)[/]"
    )


def dl_upgrade(size, filename):
    console.print(
        f" [zulu]{_zulu()}[/]   [ok]UPGRADED FS[/] {size:>9,}B  [dim]{filename}  "
        f"(replaced 800x600 with original)[/]"
    )


def dl_fail(filename):
    console.print(
        f" [zulu]{_zulu()}[/]   [err]MISSED APCH[/]  not recoverable  [dim]{filename}[/]"
    )


# ── Flight strips (album table) ─────────────────────────────────────────


def show_albums_table(albums):
    """Display album scan results as a flight-strip board.

    albums: list of (url, category, photo_count, title)
    """
    table = Table(
        show_header=True,
        header_style="strip",
        padding=(0, 1),
        border_style=f"dim {HF['green']}",
        box=box.HEAVY_HEAD,
        title="[phase]▮▮ FLIGHT STRIPS — ALBUMS ON SCOPE ▮▮[/]",
        title_justify="left",
    )
    table.add_column("STRIP", style="dim", width=5, justify="right")
    table.add_column("ALBUM", style="bold white", max_width=30)
    table.add_column("SQUAWK · ID", style="scope", max_width=20)
    table.add_column("SECTOR", style="phase", max_width=14)
    table.add_column("PHOTOS", style="bold white", justify="right", width=7)

    for i, (url, category, count, title) in enumerate(albums, 1):
        album_id = url.split("/album/")[1] if "/album/" in url else url[-30:]
        table.add_row(
            f"{i:03d}",
            (title or "—")[:30],
            album_id[:20],
            category[:14].upper(),
            str(count),
        )

    console.print(table)


def show_callsigns_table(rows, total_found):
    """Display username-sweep results.

    rows: list of {name, pages, first, last} dicts, already ordered.
    """
    table = Table(
        show_header=True,
        header_style="strip",
        padding=(0, 1),
        border_style=f"dim {HF['green']}",
        box=box.HEAVY_HEAD,
        title="[ident]▮▮ CALLSIGNS ON FREQUENCY ▮▮[/]",
        title_justify="left",
    )
    table.add_column("STRIP", style="dim", width=5, justify="right")
    table.add_column("SCREEN NAME", style="bold white", max_width=32)
    table.add_column("ARCHIVED PAGES", style="scope", justify="right", width=14)
    table.add_column("FIRST SEEN", style="dim", width=10)
    table.add_column("LAST SEEN", style="dim", width=10)

    def _d(ts):
        return f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}" if len(ts) >= 8 else ts

    for i, r in enumerate(rows, 1):
        table.add_row(
            f"{i:03d}", r["name"][:32], str(r["pages"]), _d(r["first"]), _d(r["last"])
        )
    console.print(table)
    if total_found > len(rows):
        console.print(
            f"         [dim]{total_found - len(rows)} more matches not shown — "
            f"narrow the prefix or raise -n[/]"
        )


# ── Debrief (final summary) ─────────────────────────────────────────────


def show_summary(stats):
    """Display final operation summary.

    stats: dict with downloaded, failed, skipped, bytes, elapsed, output_dir
    """
    ok = stats["downloaded"]
    bad = stats["failed"]
    skip = stats["skipped"]
    total_found = ok + bad + skip + stats.get("thumbs_only", 0)

    table = Table(show_header=False, padding=(0, 2), box=None)
    table.add_column("K", style=f"dim {HF['green']}", width=22)
    table.add_column("V", style="bold white")

    table.add_row("TRAFFIC (photos found)", str(total_found))
    table.add_row("RECOVERED (landed)", f"[ok]{ok}[/]")
    if stats.get("upgraded"):
        table.add_row("UPGRADED TO FULL-SIZE", f"[ok]{stats['upgraded']}[/]")
    if stats.get("thumbs_only"):
        table.add_row("THUMBNAIL ONLY", f"[amber]{stats['thumbs_only']}[/]")
    if bad:
        table.add_row("MISSED APPROACHES", f"[err]{bad}[/]")
    if skip:
        table.add_row("AT GATE (already had)", f"[dim]{skip}[/]")
    if stats.get("pages_failed"):
        table.add_row("ALBUM PAGES UNREACHED", f"[warn]{stats['pages_failed']}[/]")
    table.add_row("PAYLOAD", f"{stats['bytes'] / 1024 / 1024:.1f} MB")
    table.add_row("BLOCK TIME", f"{stats['elapsed']:.1f}s")
    if stats["elapsed"] > 0:
        table.add_row("RECOVERY RATE", f"{ok / stats['elapsed']:.2f} photos/sec")
    table.add_row("HANGAR (output dir)", stats["output_dir"])

    if bad == 0:
        border, title = HF["green"], "[phase]■ OPERATIONS NORMAL — RUNWAY CLEAR ■[/]"
    else:
        border, title = HF["yellow"], "[warn]■ OPERATION COMPLETE — WITH MISSES ■[/]"
    console.print()
    console.print(
        Panel(table, title=title, border_style=border, box=box.DOUBLE, padding=(1, 2))
    )


# ── Progress bars ───────────────────────────────────────────────────────


def make_progress(transient=False):
    return Progress(
        SpinnerColumn(spinner_name="strobe", style=HF["white"]),
        TextColumn("[phase]{task.description}"),
        BarColumn(bar_width=30, complete_style=HF["green"], finished_style=f"bold {HF['green']}"),
        TextColumn("[bold]{task.completed}[/]/{task.total}"),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
        TimeRemainingColumn(),
        console=console,
        transient=transient,
    )
