"""Contact-sheet generator: a self-contained gallery.html after every pull.

The terminal summary tells you numbers; this page shows someone their
photos again.  No network, no JS dependencies — file:// friendly.
"""

from __future__ import annotations

import html
import os
from datetime import datetime, timezone

from lib import __version__

_CSS = """
:root { color-scheme: dark; }
* { box-sizing: border-box; margin: 0; padding: 0; }
body { background: #0c0f0c; color: #d8e8d8; font-family: Segoe UI, system-ui, sans-serif; }
header { padding: 28px 32px 20px; border-bottom: 2px solid #1f3d1f; }
header h1 { font-size: 26px; color: #7dff7d; letter-spacing: 2px; }
header h1 span { color: #fff; }
header p { color: #7a967a; margin-top: 6px; font-size: 14px; }
.stats { display: flex; gap: 24px; margin-top: 14px; flex-wrap: wrap; }
.stat b { color: #7dff7d; font-size: 20px; display: block; }
.stat { color: #7a967a; font-size: 12px; text-transform: uppercase; letter-spacing: 1px; }
section { padding: 24px 32px; }
section h2 { font-size: 17px; color: #eaffea; margin-bottom: 4px; }
section .meta { color: #6a836a; font-size: 12px; margin-bottom: 14px; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(190px, 1fr)); gap: 10px; }
.card { background: #131a13; border: 1px solid #1f3d1f; border-radius: 6px; overflow: hidden; }
.card a { display: block; }
.card img { width: 100%; height: 150px; object-fit: cover; display: block; }
.card .cap { padding: 6px 8px; font-size: 11px; color: #9db89d; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.badge { float: right; color: #557a55; }
.badge.fs { color: #7dff7d; }
.badge.th { color: #d9b84a; }
footer { padding: 24px 32px; color: #4a5f4a; font-size: 12px; border-top: 1px solid #1f3d1f; }
"""


def write_gallery(
    output_dir: str,
    username: str,
    albums: list[dict],
    stats: dict,
) -> str:
    """Write gallery.html into output_dir; returns its path.

    albums: [{"id", "title", "category", "dir", "photos": [record...]}]
    photo records: {"id", "variant", "size", "file", "title"}
    """
    when = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%MZ")
    recovered = sum(
        1 for a in albums for p in a["photos"]
        if p.get("variant") in ("fs", "ph", "th", "skip")
    )

    parts: list[str] = []
    parts.append(f"<!DOCTYPE html><html><head><meta charset='utf-8'>")
    parts.append(f"<title>{html.escape(username)} — recovered Webshots photos</title>")
    parts.append(f"<style>{_CSS}</style></head><body>")
    parts.append("<header>")
    parts.append(
        "<h1>PAISLEY PONYTAIL <span>// photos recovered for "
        f"{html.escape(username)}</span></h1>"
    )
    parts.append(
        "<p>Pulled from the Internet Archive's Wayback Machine — "
        "originally shared on Webshots (1995–2012).</p>"
    )
    parts.append("<div class='stats'>")
    for label, value in (
        ("Albums", len(albums)),
        ("Photos recovered", recovered),
        ("Full-size originals", sum(1 for a in albums for p in a["photos"] if p.get("variant") == "fs")),
        ("Recovered", f"{stats.get('bytes', 0) / 1024 / 1024:.1f} MB"),
    ):
        parts.append(f"<div class='stat'><b>{value}</b>{label}</div>")
    parts.append("</div></header>")

    for album in albums:
        photos = [p for p in album["photos"] if p.get("file")]
        if not photos:
            continue
        title = album.get("title") or f"Album {album['id']}"
        parts.append("<section>")
        parts.append(f"<h2>{html.escape(title)}</h2>")
        parts.append(
            f"<div class='meta'>{html.escape(album.get('category', ''))}"
            f" · {len(photos)} photos · album {html.escape(album['id'])}</div>"
        )
        parts.append("<div class='grid'>")
        for p in photos:
            rel = f"{album['dir']}/{p['file']}".replace(os.sep, "/")
            cap = p.get("title") or p.get("id") or ""
            variant = p.get("variant", "")
            badge = {"fs": "FULL-SIZE", "ph": "800×600", "th": "THUMB ONLY",
                     "skip": ""}.get(variant, "")
            badge_cls = "fs" if variant == "fs" else variant
            parts.append(
                f"<div class='card'><a href='{html.escape(rel)}' target='_blank'>"
                f"<img src='{html.escape(rel)}' loading='lazy' alt=''></a>"
                f"<div class='cap'>{html.escape(str(cap))}"
                f"<span class='badge {badge_cls}'>{badge}</span></div></div>"
            )
        parts.append("</div></section>")

    parts.append(
        f"<footer>Recovered {when} · Paisley Ponytail v{__version__} "
        "(the Webshots Resurrector) · Tailstrike Studios × Ash Airfoil · "
        "github.com/coldbricks/paisley-ponytail · "
        "Be kind to archive.org — they kept these photos alive.</footer>"
    )
    parts.append("</body></html>")

    path = os.path.join(output_dir, "gallery.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write("".join(parts))
    return path
