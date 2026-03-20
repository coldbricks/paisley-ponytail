#!/usr/bin/env python3
"""Stress test: download all full-size photos for a Webshots user via Wayback Machine.

v2: async concurrent downloads, derive image URLs from thumbnails (skip photo pages).
"""

import asyncio
import re
import os
import sys
import time
import httpx

WAYBACK_BASE = "https://web.archive.org/web"
CDX_API = "https://web.archive.org/cdx/search/cdx"
USER_AGENT = "WebshotsResurrector/0.2 (archive recovery tool)"
MAX_CONCURRENT = 4  # parallel downloads
RATE_DELAY = 0.3    # seconds between request starts (burst-friendly)


class Stats:
    def __init__(self):
        self.downloaded = 0
        self.failed = 0
        self.skipped = 0
        self.total_bytes = 0
        self.start_time = time.time()


async def fetch(client, url, retries=3):
    for attempt in range(retries):
        try:
            r = await client.get(url, follow_redirects=True, timeout=45)
            if r.status_code == 200:
                return r
            if r.status_code in (429, 503, 504):
                wait = 2 ** (attempt + 1)
                print(f"  [{r.status_code}] backing off {wait}s...")
                await asyncio.sleep(wait)
                continue
            return None
        except (httpx.TimeoutException, httpx.ConnectError):
            wait = 2 ** (attempt + 1)
            await asyncio.sleep(wait)
    return None


async def fetch_text(client, url):
    r = await fetch(client, url)
    return r.text if r else None


def thumb_to_image_url(thumb_url):
    """Convert a thumbnail URL to a full-size image URL.

    thumb: http://thumb13.webshots.net/s/thumb3/8/29/37/71082937TyqapS_th.jpg
    image: http://image13.webshots.com/13/8/29/37/71082937TyqapS_fs.jpg

    The path after /thumbN/ or /N/ is identical. The server number in the
    hostname may differ, but Wayback doesn't care — it resolves by URL key.
    We just need a plausible imageNN hostname.
    """
    # Extract server number from thumbNN
    m = re.match(r'https?://thumb(\d+)\.webshots\.net/', thumb_url)
    if not m:
        return None
    server_num = m.group(1)
    # Extract the path portion after /s/thumbN/
    m2 = re.search(r'/s/thumb\d+/(.+)_th\.jpg', thumb_url)
    if not m2:
        return None
    path = m2.group(1)
    return f"http://image{server_num}.webshots.com/{server_num}/{path}_fs.jpg"


def thumb_to_ph_url(thumb_url):
    """Same as above but for _ph.jpg fallback."""
    m = re.match(r'https?://thumb(\d+)\.webshots\.net/', thumb_url)
    if not m:
        return None
    server_num = m.group(1)
    m2 = re.search(r'/s/thumb\d+/(.+)_th\.jpg', thumb_url)
    if not m2:
        return None
    path = m2.group(1)
    return f"http://image{server_num}.webshots.com/{server_num}/{path}_ph.jpg"


def extract_thumbnails_from_album(html):
    """Extract thumbnail URLs and their associated photo IDs from an album page."""
    # Match Wayback-proxied thumbnail URLs
    pattern = r'https?://web\.archive\.org/web/(\d+)im_/(https?://thumb\d+\.webshots\.net/s/thumb\d+/[^"\'<>\s]+_th\.jpg)'
    matches = re.findall(pattern, html)
    # Deduplicate by thumbnail URL
    seen = set()
    results = []
    for ts, url in matches:
        if url not in seen:
            seen.add(url)
            results.append((ts, url))
    return results


async def download_one(sem, client, thumb_ts, thumb_url, output_dir, index, total, stats):
    """Download a single image: try _fs.jpg from thumbnail, fall back to _ph.jpg."""
    async with sem:
        await asyncio.sleep(RATE_DELAY)

        filename_base = thumb_url.split('/')[-1].replace('_th.jpg', '')
        fs_url = thumb_to_image_url(thumb_url)
        ph_url = thumb_to_ph_url(thumb_url)

        # Try _fs.jpg first
        if fs_url:
            wb_url = f"{WAYBACK_BASE}/{thumb_ts}im_/{fs_url}"
            r = await fetch(client, wb_url)
            if r and len(r.content) > 1000 and r.content[:2] == b'\xff\xd8':
                out = os.path.join(output_dir, f"{filename_base}_fs.jpg")
                with open(out, "wb") as f:
                    f.write(r.content)
                stats.downloaded += 1
                stats.total_bytes += len(r.content)
                elapsed = time.time() - stats.start_time
                rate = stats.total_bytes / 1024 / max(elapsed, 1)
                print(f"  [{index}/{total}] fs {len(r.content):>8,}B  {filename_base}_fs.jpg  ({rate:.0f} KB/s)")
                return

        # Fall back to _ph.jpg
        await asyncio.sleep(RATE_DELAY)
        if ph_url:
            wb_url = f"{WAYBACK_BASE}/{thumb_ts}im_/{ph_url}"
            r = await fetch(client, wb_url)
            if r and len(r.content) > 500 and r.content[:2] == b'\xff\xd8':
                out = os.path.join(output_dir, f"{filename_base}_ph.jpg")
                with open(out, "wb") as f:
                    f.write(r.content)
                stats.downloaded += 1
                stats.total_bytes += len(r.content)
                elapsed = time.time() - stats.start_time
                rate = stats.total_bytes / 1024 / max(elapsed, 1)
                print(f"  [{index}/{total}] ph {len(r.content):>8,}B  {filename_base}_ph.jpg  ({rate:.0f} KB/s)")
                return

        # Also try deriving from imageNN directly on photo page as last resort
        # (some thumbnails use /t/ path instead of /s/thumbN/)
        stats.failed += 1
        print(f"  [{index}/{total}] FAIL {filename_base}")


async def main():
    username = sys.argv[1] if len(sys.argv) > 1 else "marysnewwebshots"
    output_base = os.path.join(os.path.dirname(__file__), "output", username)
    os.makedirs(output_base, exist_ok=True)

    print(f"=== WEBSHOTS RESURRECTOR v2 (ASYNC) ===")
    print(f"Target:      {username}")
    print(f"Concurrency: {MAX_CONCURRENT}")
    print(f"Output:      {output_base}/")
    print()

    async with httpx.AsyncClient(
        headers={"User-Agent": USER_AGENT},
        timeout=45,
        follow_redirects=True,
        limits=httpx.Limits(max_connections=MAX_CONCURRENT + 2),
    ) as client:

        # Step 1: Find profile timestamp
        print(f"[1] Finding latest profile snapshot...")
        cdx_url = f"{CDX_API}?url=community.webshots.com/user/{username}&output=json&limit=-1"
        r = await fetch(client, cdx_url)
        if not r or r.text.strip() in ('', '[]'):
            print("    FAILED: no Wayback captures found")
            return
        rows = r.json()
        if len(rows) < 2:
            print("    FAILED: no captures")
            return
        ts = rows[-1][1]
        print(f"    Latest: {ts} ({len(rows)-1} total captures)")

        # Step 2: Get albums
        profile_url = f"http://community.webshots.com/user/{username}"
        print(f"[2] Loading profile page...")
        html = await fetch_text(client, f"{WAYBACK_BASE}/{ts}/{profile_url}")
        if not html:
            print("    FAILED: couldn't load profile")
            return

        album_pattern = r'href="https?://web\.archive\.org/web/\d+/(https?://[^/"]*webshots\.[^/"]+/album/[^"#]+)'
        albums = list(dict.fromkeys(re.findall(album_pattern, html)))
        print(f"    Found {len(albums)} albums")

        if not albums:
            # Try alternate timestamps
            for row in reversed(rows[1:-1]):
                alt_ts = row[1]
                html = await fetch_text(client, f"{WAYBACK_BASE}/{alt_ts}/{profile_url}")
                if html:
                    albums = list(dict.fromkeys(re.findall(album_pattern, html)))
                    if albums:
                        ts = alt_ts
                        print(f"    Found {len(albums)} albums at {ts}")
                        break

        if not albums:
            print("    FAILED: no albums found")
            return

        # Step 3: Load all album pages and extract thumbnails (skip photo pages!)
        print(f"\n[3] Loading {len(albums)} album pages...")
        all_thumbs = []  # (wayback_ts, thumb_url, album_name)

        for i, album_url in enumerate(albums):
            await asyncio.sleep(RATE_DELAY)
            album_name = album_url.split('/album/')[1] if '/album/' in album_url else f"album_{i}"

            html = await fetch_text(client, f"{WAYBACK_BASE}/{ts}/{album_url}")
            if not html:
                print(f"    Album {i+1}/{len(albums)} [{album_name[:30]}]: FAILED to load")
                continue

            thumbs = extract_thumbnails_from_album(html)

            # Filter out non-user thumbnails (sidebar/related content)
            # User photos typically appear in the main content area
            # We keep all for now since deduplication handles it

            print(f"    Album {i+1}/{len(albums)} [{album_name[:30]}]: {len(thumbs)} photos")
            for thumb_ts, thumb_url in thumbs:
                all_thumbs.append((thumb_ts, thumb_url, album_name))

        # Deduplicate across albums (same photo can appear in multiple views)
        seen = set()
        unique_thumbs = []
        for item in all_thumbs:
            if item[1] not in seen:
                seen.add(item[1])
                unique_thumbs.append(item)

        print(f"\n    Total: {len(unique_thumbs)} unique photos")

        if not unique_thumbs:
            print("    FAILED: no photos found")
            return

        # Step 4: Download all images concurrently
        print(f"\n[4] Downloading {len(unique_thumbs)} photos ({MAX_CONCURRENT} concurrent)...")
        stats = Stats()
        sem = asyncio.Semaphore(MAX_CONCURRENT)

        tasks = []
        for i, (thumb_ts, thumb_url, album_name) in enumerate(unique_thumbs):
            safe_album = re.sub(r'[^\w\-.]', '_', album_name)[:50]
            album_dir = os.path.join(output_base, safe_album)
            os.makedirs(album_dir, exist_ok=True)
            tasks.append(
                download_one(sem, client, thumb_ts, thumb_url, album_dir, i + 1, len(unique_thumbs), stats)
            )

        await asyncio.gather(*tasks)

        elapsed = time.time() - stats.start_time
        print(f"\n=== RESULTS ===")
        print(f"User:       {username}")
        print(f"Albums:     {len(albums)}")
        print(f"Photos:     {len(unique_thumbs)}")
        print(f"Downloaded: {stats.downloaded}")
        print(f"Failed:     {stats.failed}")
        print(f"Total size: {stats.total_bytes:,} bytes ({stats.total_bytes/1024/1024:.1f} MB)")
        print(f"Time:       {elapsed:.1f}s ({stats.downloaded/max(elapsed,1):.1f} photos/sec)")
        print(f"Output:     {os.path.abspath(output_base)}/")


if __name__ == "__main__":
    asyncio.run(main())
