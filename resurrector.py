#!/usr/bin/env python3
"""
Paisley Ponytail  --  the Webshots Resurrector
Internet Archive Photo Recovery System

Search for Webshots users and download their archived photos from
the Wayback Machine.  Full-size originals when available, 800x600
fallback otherwise.

Usage:
    python3 resurrector.py search <username>
    python3 resurrector.py pull   <username> [-j JOBS] [-o DIR]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from datetime import datetime, timezone

from lib.engine import Config, Engine, Stats
from lib.ui import (
    console,
    detail,
    dl_fail,
    dl_ok,
    dl_skip,
    fail,
    make_progress,
    phase,
    show_albums_table,
    show_banner,
    show_summary,
    success,
    warn,
)

# ── Recon + Scan (shared by search and pull) ────────────────────────────


async def recon(
    username: str, engine: Engine
) -> tuple[str, list[list[str]]] | None:
    """RECON phase: locate user in Wayback CDX.

    Returns (latest_timestamp, cdx_rows) or None.
    """
    phase("RECON", f"Target: [target]{username}[/]")
    phase("RECON", "Querying Wayback Machine CDX API...")

    url = f"community.webshots.com/user/{username}"
    rows = await engine.cdx_search(url)

    if not rows:
        fail("RECON", f"No Wayback captures found for [target]{username}[/]")
        return None

    timestamps = [r[1] for r in rows]
    first, last = timestamps[0][:8], timestamps[-1][:8]
    first_fmt = f"{first[:4]}-{first[4:6]}-{first[6:8]}"
    last_fmt = f"{last[:4]}-{last[4:6]}-{last[6:8]}"

    success("RECON", f"radar contact — {len(rows)} snapshots  ({first_fmt} .. {last_fmt})")
    phase("RECON", f"Latest capture: [bold]{timestamps[-1]}[/]")

    return timestamps[-1], rows


async def scan(
    username: str,
    ts: str,
    rows: list[list[str]],
    engine: Engine,
    deep: bool = False,
) -> tuple[str, list[tuple[str, str, str, str]]] | None:
    """SCAN phase: load profile page(s), extract album list.

    Returns (effective_timestamp, albums) or None.
    albums: [(original_url, category, album_id, wayback_ts), ...] —
    each album carries the profile snapshot it was discovered at.
    """
    phase("SCAN", "Loading profile...")
    _, html = await engine.load_profile(username, ts)

    albums: dict[str, tuple[str, str, str, str]] = {}  # album_id -> entry
    if html:
        for url, category, album_id in engine.extract_albums(html):
            albums.setdefault(album_id, (url, category, album_id, ts))

    if not albums:
        warn("SCAN", "No albums at latest timestamp, probing alternates...")
        timestamps = [r[1] for r in rows]
        for alt_ts in list(reversed(timestamps[:-1]))[:8]:
            _, html = await engine.load_profile(username, alt_ts)
            if html:
                found = engine.extract_albums(html)
                if found:
                    ts = alt_ts
                    for url, category, album_id in found:
                        albums.setdefault(album_id, (url, category, album_id, ts))
                    success("SCAN", f"Found albums at {alt_ts}")
                    break

    if deep:
        phase("DEEP", "Enumerating profile-page variants via CDX prefix search...")
        pages = await engine.discover_profile_pages(username)
        success("DEEP", f"{len(pages)} archived profile pages across all eras")
        with make_progress(transient=True) as progress:
            # Probe each page at its first and last capture — album sets
            # changed across the site's decade, so eras matter.
            probes = [
                (url, snap_ts)
                for url, ts_list in pages
                for snap_ts in dict.fromkeys((ts_list[0], ts_list[-1]))
            ]
            task = progress.add_task("Deep scan", total=len(probes))
            before = len(albums)
            for url, snap_ts in probes:
                page_html = await engine.load_page(url, snap_ts)
                if page_html:
                    for a_url, category, album_id in engine.extract_albums(page_html):
                        albums.setdefault(album_id, (a_url, category, album_id, snap_ts))
                progress.advance(task)
        gained = len(albums) - before
        if gained:
            success("DEEP", f"[bold]+{gained}[/] albums not visible on the latest profile")
        else:
            phase("DEEP", "No additional albums beyond the latest profile")

    if not albums:
        fail("SCAN", "No albums found at any timestamp")
        return None

    success("SCAN", f"[bold]{len(albums)}[/] albums identified")
    return ts, list(albums.values())


# ── Commands ────────────────────────────────────────────────────────────


async def cmd_search(username: str, engine: Engine, deep: bool = False) -> None:
    """Search for a user: show profile info and album listing."""
    result = await recon(username, engine)
    if not result:
        return
    ts, rows = result

    scan_result = await scan(username, ts, rows, engine, deep=deep)
    if not scan_result:
        return
    ts, albums_raw = scan_result

    # Count photos per album
    phase("SCAN", f"Counting photos in {len(albums_raw)} albums...")
    album_data: list[tuple[str, str, int]] = []
    total_photos = 0

    with make_progress(transient=True) as progress:
        task = progress.add_task("Scanning", total=len(albums_raw))
        for url, category, album_id, album_ts in albums_raw:
            thumbs = await engine.load_album(url, album_ts)
            album_data.append((url, category, len(thumbs)))
            total_photos += len(thumbs)
            progress.advance(task)

    console.print()
    show_albums_table(album_data)
    console.print()
    success("SCAN", f"[bold]{total_photos}[/] photos across {len(albums_raw)} albums")
    console.print()
    detail(
        f"[ok]CLEARED FOR PULL[/] [dim]▸[/] "
        f"[bold]python resurrector.py pull {username}[/] "
        f"[dim]to recover all photos[/]"
    )


async def cmd_pull(
    username: str,
    engine: Engine,
    output_root: str = "output",
    deep: bool = False,
) -> None:
    """Download all photos for a user."""
    result = await recon(username, engine)
    if not result:
        return
    ts, rows = result

    scan_result = await scan(username, ts, rows, engine, deep=deep)
    if not scan_result:
        return
    ts, albums_raw = scan_result

    # ── Build photo manifest ────────────────────────────────────────
    phase("SCAN", f"Building photo manifest from {len(albums_raw)} albums...")

    all_thumbs: list[tuple[str, str, str, str]] = []  # (ts, url, album_id, cat)
    album_data: list[tuple[str, str, int]] = []

    with make_progress(transient=True) as progress:
        task = progress.add_task("Scanning albums", total=len(albums_raw))
        for url, category, album_id, album_ts in albums_raw:
            thumbs = await engine.load_album(url, album_ts)
            album_data.append((url, category, len(thumbs)))
            for t_ts, t_url in thumbs:
                all_thumbs.append((t_ts, t_url, album_id, category))
            progress.advance(task)

    console.print()
    show_albums_table(album_data)

    # Deduplicate by thumbnail URL
    seen: set[str] = set()
    unique: list[tuple[str, str, str, str]] = []
    for item in all_thumbs:
        if item[1] not in seen:
            seen.add(item[1])
            unique.append(item)

    console.print()
    success("SCAN", f"[bold]{len(unique)}[/] unique photos in manifest")

    if not unique:
        return

    # ── Download ────────────────────────────────────────────────────
    output_dir = os.path.join(output_root, username)
    os.makedirs(output_dir, exist_ok=True)

    stats = Stats()
    phase(
        "PULL",
        f"Extracting {len(unique)} photos  "
        f"([bold]{engine.cfg.max_concurrent}[/] concurrent)",
    )
    console.print()

    with make_progress() as progress:
        task = progress.add_task(f"Pulling {username}", total=len(unique))

        async def _dl(thumb_ts, thumb_url, album_id, category):
            safe = re.sub(r"[^\w\-.]", "_", f"{category}_{album_id}")[:60]
            album_dir = os.path.join(output_dir, safe)
            os.makedirs(album_dir, exist_ok=True)

            pid = engine.photo_id(thumb_url) or "unknown"
            path, variant, size = await engine.download_photo(
                thumb_ts, thumb_url, album_dir, stats
            )

            if variant == "fs":
                dl_ok("fs", size, f"{pid}_fs.jpg")
            elif variant == "ph":
                dl_ok("ph", size, f"{pid}_ph.jpg")
            elif variant == "skip":
                dl_skip(f"{pid}")
            else:
                dl_fail(pid)

            progress.advance(task)

        tasks = [_dl(t, u, a, c) for t, u, a, c in unique]
        await asyncio.gather(*tasks)

    # ── Manifest ────────────────────────────────────────────────────
    manifest = {
        "tool": "webshots-resurrector",
        "codename": "Paisley Ponytail",
        "version": "1.1.0",
        "user": username,
        "wayback_timestamp": ts,
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "albums": len(albums_raw),
        "photos_found": len(unique),
        "downloaded": stats.downloaded,
        "failed": stats.failed,
        "skipped": stats.skipped,
        "bytes": stats.bytes,
        "elapsed_sec": round(stats.elapsed, 2),
    }
    manifest_path = os.path.join(output_dir, "manifest.json")
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    show_summary(stats.as_dict(os.path.abspath(output_dir)))


# ── CLI ─────────────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="resurrector",
        description="Paisley Ponytail (the Webshots Resurrector)  -  Internet Archive Photo Recovery System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  python3 resurrector.py search bexbee12\n"
            "  python3 resurrector.py pull   bexbee12 -j 6\n"
            "  python3 resurrector.py pull   yankeefan519 -o ~/recovered\n"
        ),
    )

    sub = parser.add_subparsers(dest="command")

    deep_help = (
        "enumerate every archived profile-page variant via CDX prefix "
        "search — finds albums from older site eras (2002-2013)"
    )

    p_search = sub.add_parser("search", help="Search for a user, list albums and photo counts")
    p_search.add_argument("username", help="Webshots username to look up")
    p_search.add_argument("--deep", action="store_true", help=deep_help)

    p_pull = sub.add_parser("pull", help="Download all photos for a user")
    p_pull.add_argument("username", help="Webshots username to download")
    p_pull.add_argument("--deep", action="store_true", help=deep_help)
    p_pull.add_argument(
        "-o", "--output", default="output", help="Output root directory (default: output/)"
    )
    p_pull.add_argument(
        "-j", "--jobs", type=int, default=4, metavar="N",
        help="Concurrent downloads (default: 4)",
    )

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    show_banner()

    if not args.command:
        parser.print_help()
        return

    cfg = Config()
    if hasattr(args, "jobs"):
        cfg.max_concurrent = max(1, min(args.jobs, 12))

    async def _run():
        async with Engine(cfg) as engine:
            deep = getattr(args, "deep", False)
            if args.command == "search":
                await cmd_search(args.username, engine, deep=deep)
            elif args.command == "pull":
                out = getattr(args, "output", "output")
                await cmd_pull(args.username, engine, out, deep=deep)

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        console.print("\n [dim]Operation cancelled.[/]")
        sys.exit(130)


if __name__ == "__main__":
    main()
