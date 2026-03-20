"""Terminal display layer for Webshots Resurrector."""

from datetime import datetime, timezone

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
from rich.theme import Theme

THEME = Theme(
    {
        "phase": "bold cyan",
        "ok": "green",
        "warn": "yellow",
        "err": "bold red",
        "dim": "dim",
        "target": "bold white",
        "heading": "bold white",
    }
)

console = Console(theme=THEME, highlight=False)

# ── Banner ──────────────────────────────────────────────────────────────

LOGO_WEBSHOTS = (
    "  [bold cyan]█ █ █▀▀ █▀▄ █▀▀ █ █ █▀█ ▀█▀ █▀▀[/]\n"
    "  [bold cyan]█▄█ █▀▀ █▀▄ ▀▀█ █▀█ █ █  █  ▀▀█[/]\n"
    "  [bold cyan]▀ ▀ ▀▀▀ ▀▀  ▀▀▀ ▀ ▀ ▀▀▀  ▀  ▀▀▀[/]"
)

LOGO_RESURRECTOR = (
    "  [bold white]█▀█ █▀▀ █▀▀ █ █ █▀█ █▀█ █▀▀ █▀▀ ▀█▀ █▀█ █▀█[/]\n"
    "  [bold white]█▀▄ █▀▀ ▀▀█ █ █ █▀▄ █▀▄ █▀▀ █    █  █ █ █▀▄[/]\n"
    "  [bold white]▀ ▀ ▀▀▀ ▀▀▀ ▀▀▀ ▀ ▀ ▀ ▀ ▀▀▀ ▀▀▀  ▀  ▀▀▀ ▀ ▀[/]"
)

VERSION = "1.0.0"


def show_banner():
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    body = (
        f"{LOGO_WEBSHOTS}\n"
        f"{LOGO_RESURRECTOR}\n\n"
        f"  [dim]v{VERSION}  |  Internet Archive Photo Recovery System[/]\n"
        f"  [dim]{now}[/]"
    )
    console.print()
    console.print(Panel(body, border_style="cyan", padding=(1, 1)))
    console.print()


# ── Phase logging ───────────────────────────────────────────────────────


def phase(tag, msg):
    console.print(f" [phase]\\[{tag}][/] {msg}")


def success(tag, msg):
    console.print(f" [ok]\\[{tag}][/] {msg}")


def warn(tag, msg):
    console.print(f" [warn]\\[{tag}][/] {msg}")


def fail(tag, msg):
    console.print(f" [err]\\[{tag}][/] {msg}")


def detail(msg):
    console.print(f"         {msg}")


def dl_ok(variant, size, filename):
    v = f"[ok]{variant}[/]"
    console.print(f"         {v}  {size:>9,}B  [dim]{filename}[/]")


def dl_skip(filename):
    console.print(f"         [dim]--  EXISTING   {filename}[/]")


def dl_fail(filename):
    console.print(f"         [err]--    FAILED[/]   {filename}")


# ── Tables ──────────────────────────────────────────────────────────────


def show_albums_table(albums):
    """Display album scan results.

    albums: list of (url, category, photo_count)
    """
    table = Table(
        show_header=True,
        header_style="bold cyan",
        padding=(0, 1),
        border_style="dim",
    )
    table.add_column("#", style="dim", width=4, justify="right")
    table.add_column("Album ID", style="white", max_width=38)
    table.add_column("Category", style="cyan", max_width=14)
    table.add_column("Photos", style="ok", justify="right", width=7)

    for i, (url, category, count) in enumerate(albums, 1):
        album_id = url.split("/album/")[1] if "/album/" in url else url[-30:]
        table.add_row(str(i), album_id[:38], category[:14], str(count))

    console.print(table)


def show_summary(stats):
    """Display final operation summary.

    stats: dict with downloaded, failed, skipped, bytes, elapsed, output_dir
    """
    ok = stats["downloaded"]
    bad = stats["failed"]
    skip = stats["skipped"]
    total_found = ok + bad + skip

    table = Table(show_header=False, padding=(0, 2), box=None)
    table.add_column("K", style="dim", width=14)
    table.add_column("V", style="bold white")

    table.add_row("Found", str(total_found))
    table.add_row("Downloaded", f"[ok]{ok}[/]")
    if bad:
        table.add_row("Failed", f"[err]{bad}[/]")
    if skip:
        table.add_row("Skipped", f"[dim]{skip}[/]")
    table.add_row("Total Size", f"{stats['bytes'] / 1024 / 1024:.1f} MB")
    table.add_row("Duration", f"{stats['elapsed']:.1f}s")
    if stats["elapsed"] > 0:
        table.add_row("Rate", f"{ok / stats['elapsed']:.2f} photos/sec")
    table.add_row("Output", stats["output_dir"])

    border = "green" if bad == 0 else "yellow"
    title = "[bold]OPERATION COMPLETE[/]"
    console.print()
    console.print(Panel(table, title=title, border_style=border, padding=(1, 2)))


# ── Progress bars ───────────────────────────────────────────────────────


def make_progress(transient=False):
    return Progress(
        SpinnerColumn(spinner_name="dots"),
        TextColumn("[bold cyan]{task.description}"),
        BarColumn(bar_width=30, complete_style="green", finished_style="bold green"),
        TextColumn("[bold]{task.completed}[/]/{task.total}"),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
        TimeRemainingColumn(),
        console=console,
        transient=transient,
    )
