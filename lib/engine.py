"""Core engine: HTTP transport, Wayback API, scraping, downloading."""

from __future__ import annotations

import asyncio
import os
import re
import time

import httpx

# ── Constants ───────────────────────────────────────────────────────────

WAYBACK = "https://web.archive.org/web"
CDX_API = "https://web.archive.org/cdx/search/cdx"
UA = "WebshotsResurrector/1.0 (archive-photo-recovery)"
JPEG_MAGIC = b"\xff\xd8"


# ── Configuration ───────────────────────────────────────────────────────


class Config:
    max_concurrent: int = 4
    rate_delay: float = 0.4
    timeout: float = 45
    max_retries: int = 3
    backoff_base: float = 2
    backoff_cap: float = 60


# ── Stats ───────────────────────────────────────────────────────────────


class Stats:
    __slots__ = ("downloaded", "failed", "skipped", "bytes", "_t0")

    def __init__(self):
        self.downloaded = 0
        self.failed = 0
        self.skipped = 0
        self.bytes = 0
        self._t0 = time.monotonic()

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self._t0

    def as_dict(self, output_dir: str = "") -> dict:
        return {
            "downloaded": self.downloaded,
            "failed": self.failed,
            "skipped": self.skipped,
            "bytes": self.bytes,
            "elapsed": self.elapsed,
            "output_dir": output_dir,
        }


# ── Rate limiter ────────────────────────────────────────────────────────


class _RateLimiter:
    """Global rate limiter: enforces minimum delay between request starts."""

    def __init__(self, delay: float):
        self._delay = delay
        self._lock = asyncio.Lock()
        self._last = 0.0

    async def acquire(self):
        async with self._lock:
            now = time.monotonic()
            gap = self._delay - (now - self._last)
            if gap > 0:
                await asyncio.sleep(gap)
            self._last = time.monotonic()


# ── Engine ──────────────────────────────────────────────────────────────


class Engine:
    """Async engine for Wayback Machine interaction and photo extraction."""

    def __init__(self, cfg: Config | None = None):
        self.cfg = cfg or Config()
        self._limiter = _RateLimiter(self.cfg.rate_delay)
        self._client: httpx.AsyncClient | None = None
        self._sem: asyncio.Semaphore | None = None

    async def __aenter__(self):
        self._client = httpx.AsyncClient(
            headers={"User-Agent": UA},
            timeout=self.cfg.timeout,
            follow_redirects=True,
            limits=httpx.Limits(
                max_connections=self.cfg.max_concurrent + 6,
                max_keepalive_connections=self.cfg.max_concurrent + 2,
            ),
        )
        self._sem = asyncio.Semaphore(self.cfg.max_concurrent)
        return self

    async def __aexit__(self, *exc):
        if self._client:
            await self._client.aclose()

    # ── HTTP primitives ─────────────────────────────────────────────

    async def _fetch(self, url: str, retries: int | None = None) -> httpx.Response | None:
        retries = retries or self.cfg.max_retries
        for attempt in range(retries):
            await self._limiter.acquire()
            try:
                r = await self._client.get(url)
                if r.status_code == 200:
                    return r
                if r.status_code in (429, 503, 504):
                    wait = min(
                        self.cfg.backoff_base ** (attempt + 1), self.cfg.backoff_cap
                    )
                    await asyncio.sleep(wait)
                    continue
                return None
            except (
                httpx.TimeoutException,
                httpx.ConnectError,
                httpx.ReadError,
                httpx.RemoteProtocolError,
            ):
                wait = min(
                    self.cfg.backoff_base ** (attempt + 1), self.cfg.backoff_cap
                )
                await asyncio.sleep(wait)
        return None

    async def _fetch_text(self, url: str) -> str | None:
        r = await self._fetch(url)
        return r.text if r else None

    # ── Wayback CDX API ─────────────────────────────────────────────

    async def cdx_search(
        self,
        url: str,
        match_type: str | None = None,
        collapse: str | None = None,
        status_filter: str | None = None,
        limit: int = 0,
    ) -> list[list[str]]:
        """Query Wayback CDX API.

        Returns list of rows: [urlkey, timestamp, original, mimetype,
        statuscode, digest, length].  Header row is stripped.

        NOTE: never pass a negative limit — the CDX API treats limit=-N
        as "last N rows", which silently truncates results.
        """
        query = f"{CDX_API}?url={url}&output=json"
        if match_type:
            query += f"&matchType={match_type}"
        if collapse:
            query += f"&collapse={collapse}"
        if status_filter:
            query += f"&filter=statuscode:{status_filter}"
        if limit > 0:
            query += f"&limit={limit}"
        r = await self._fetch(query)
        if not r:
            return []
        text = r.text.strip()
        if not text or text == "[]":
            return []
        try:
            rows = r.json()
            return rows[1:] if len(rows) > 1 else []
        except Exception:
            return []

    async def get_timestamps(self, url: str) -> list[str]:
        """All Wayback timestamps for a URL, newest first."""
        rows = await self.cdx_search(url)
        return [r[1] for r in reversed(rows)]

    # ── Profile scraping ────────────────────────────────────────────

    async def load_page(self, original_url: str, timestamp: str) -> str | None:
        """Fetch any original URL through Wayback playback at a timestamp."""
        return await self._fetch_text(f"{WAYBACK}/{timestamp}/{original_url}")

    async def load_profile(
        self, username: str, timestamp: str | None = None
    ) -> tuple[str | None, str | None]:
        """Load a user's profile page.

        Returns (timestamp, html) or (None, None).
        """
        base = f"http://community.webshots.com/user/{username}"
        if not timestamp:
            ts_list = await self.get_timestamps(base)
            if not ts_list:
                return None, None
            timestamp = ts_list[0]
        html = await self._fetch_text(f"{WAYBACK}/{timestamp}/{base}")
        # Guard against Wayback redirecting to modern webshots.com
        if html and "community.webshots.com" not in html and "album/" not in html:
            return timestamp, None
        return timestamp, html

    @staticmethod
    def extract_albums(html: str) -> list[tuple[str, str, str]]:
        """Extract album URLs from profile page HTML.

        Returns [(original_url, category_subdomain, album_id), ...].
        """
        # Wayback rewrites hrefs both absolute and host-relative (/web/TS/...);
        # album IDs must not swallow ?start= pagination queries.
        pattern = (
            r'href="(?:https?://web\.archive\.org)?/web/\d+/'
            r"(https?://([^/\"]*?)\.webshots\.[^/\"]+/album/([^\"#?]+))"
        )
        seen: set[str] = set()
        results: list[tuple[str, str, str]] = []
        for full_url, subdomain, album_id in re.findall(pattern, html):
            if full_url not in seen:
                seen.add(full_url)
                results.append((full_url, subdomain, album_id))
        return results

    # ── Album scraping ──────────────────────────────────────────────

    async def load_album(
        self,
        album_url: str,
        timestamp: str,
        follow_pagination: bool = True,
        max_pages: int = 50,
    ) -> list[tuple[str, str]]:
        """Load album page(s), return [(wayback_ts, thumb_url), ...].

        Album grids paginate via ?start=N — page 1 shows at most ~42
        thumbnails, so every discovered start value is fetched and the
        thumbnails unioned.  Without this, large albums silently lose
        every photo past the first page.
        """
        thumbs: dict[str, str] = {}  # thumb_url -> wayback_ts
        todo: set[int | None] = {None}
        done: set[int | None] = set()

        while todo and len(done) < max_pages:
            start = todo.pop()
            done.add(start)
            page_url = album_url if start is None else f"{album_url}?start={start}"
            html = await self._fetch_text(f"{WAYBACK}/{timestamp}/{page_url}")
            if not html:
                continue
            for ts, url in self._extract_thumbnails(html):
                thumbs.setdefault(url, ts)
            if follow_pagination:
                for s in self._extract_starts(html, album_url):
                    if s not in done:
                        todo.add(s)

        return [(ts, url) for url, ts in thumbs.items()]

    @staticmethod
    def _extract_starts(html: str, album_url: str) -> set[int]:
        """Find ?start=N pagination values pointing at this album."""
        album_id = album_url.rsplit("/album/", 1)[-1]
        pattern = rf'/album/{re.escape(album_id)}\?(?:[^"\'>]*&(?:amp;)?)?start=(\d+)'
        return {int(m) for m in re.findall(pattern, html)}

    @staticmethod
    def _extract_thumbnails(html: str) -> list[tuple[str, str]]:
        """Extract unique thumbnail URLs from album HTML.

        Handles both /s/thumbN/ and /t/NN/ path formats.
        """
        pattern = (
            r"(?:https?://web\.archive\.org)?/web/(\d+)im_/"
            r"(https?://thumb\d+\.webshots\.net/"
            r"(?:s/thumb\d+|t)/"
            r"[^\"'<>\s]+_th\.jpg)"
        )
        seen: set[str] = set()
        results: list[tuple[str, str]] = []
        for ts, url in re.findall(pattern, html):
            if url not in seen:
                seen.add(url)
                results.append((ts, url))
        return results

    # ── Deep discovery (CDX prefix enumeration) ─────────────────────

    async def discover_profile_pages(
        self, username: str
    ) -> list[tuple[str, list[str]]]:
        """Enumerate every archived profile album-list page for a user.

        The raw freeze-frame megawarcs are access-restricted (401) and the
        old search index item is dark, but their contents were ingested
        into the Wayback Machine — a CDX prefix query surfaces profile
        pagination pages (/user/NAME/2) and the date-sorted variant
        (/user/NAME-date/0) from every site era, 2002-2013.

        Returns [(original_url, [timestamps...]), ...], timestamps ascending.
        """
        rows = await self.cdx_search(
            f"community.webshots.com/user/{username}",
            match_type="prefix",
            status_filter="200",
        )
        page_re = re.compile(
            rf"^https?://community\.webshots\.com(?::80)?"
            rf"/user/{re.escape(username)}(?:-date)?(?:/\d+)?/?$",
            re.IGNORECASE,
        )
        pages: dict[str, list[str]] = {}
        for row in rows:
            ts, original = row[1], row[2]
            if not page_re.match(original):
                continue
            canonical = original.replace(":80/", "/").rstrip("/")
            pages.setdefault(canonical, []).append(ts)
        return [(url, sorted(ts_list)) for url, ts_list in sorted(pages.items())]

    # ── URL derivation ──────────────────────────────────────────────

    @staticmethod
    def thumb_to_image(thumb_url: str, suffix: str = "_fs.jpg") -> str | None:
        """Derive an imageNN.webshots.com URL from a thumbnail URL.

        Handles /s/thumbN/ format.  /t/ format uses same path structure.
        """
        m_host = re.match(r"https?://thumb(\d+)\.webshots\.net/", thumb_url)
        if not m_host:
            return None
        num = m_host.group(1)

        # /s/thumbN/path/to/PHOTO_th.jpg
        m_s = re.search(r"/s/thumb\d+/(.+)_th\.jpg$", thumb_url)
        if m_s:
            return f"http://image{num}.webshots.com/{num}/{m_s.group(1)}{suffix}"

        # /t/path/to/PHOTO_th.jpg
        m_t = re.search(r"/t/(.+)_th\.jpg$", thumb_url)
        if m_t:
            return f"http://image{num}.webshots.com/{num}/{m_t.group(1)}{suffix}"

        return None

    @staticmethod
    def photo_id(thumb_url: str) -> str | None:
        """Extract photo ID + hash from thumbnail filename."""
        m = re.search(r"/(\d+\w+)_th\.jpg$", thumb_url)
        return m.group(1) if m else None

    # ── Downloading ─────────────────────────────────────────────────

    async def download_photo(
        self,
        thumb_ts: str,
        thumb_url: str,
        output_dir: str,
        stats: Stats,
    ) -> tuple[str | None, str | None, int]:
        """Download one photo.  Try _fs.jpg, fall back to _ph.jpg.

        Returns (file_path, variant, size_bytes) or (None, None, 0).
        variant is one of: "fs", "ph", "skip", None (failed).
        """
        async with self._sem:
            pid = self.photo_id(thumb_url)
            if not pid:
                stats.failed += 1
                return None, None, 0

            # Resume: skip existing files
            for sfx in ("_fs.jpg", "_ph.jpg"):
                existing = os.path.join(output_dir, f"{pid}{sfx}")
                if os.path.isfile(existing) and os.path.getsize(existing) > 500:
                    stats.skipped += 1
                    return existing, "skip", os.path.getsize(existing)

            # Try _fs.jpg (full-size)
            path, sz = await self._try_download(thumb_ts, thumb_url, output_dir, pid, "_fs.jpg")
            if path:
                stats.downloaded += 1
                stats.bytes += sz
                return path, "fs", sz

            # Fall back to _ph.jpg (800x600)
            path, sz = await self._try_download(thumb_ts, thumb_url, output_dir, pid, "_ph.jpg")
            if path:
                stats.downloaded += 1
                stats.bytes += sz
                return path, "ph", sz

            stats.failed += 1
            return None, None, 0

    async def _try_download(
        self,
        thumb_ts: str,
        thumb_url: str,
        output_dir: str,
        pid: str,
        suffix: str,
    ) -> tuple[str | None, int]:
        """Attempt to download a single image variant.  Returns (path, size) or (None, 0)."""
        img_url = self.thumb_to_image(thumb_url, suffix)
        if not img_url:
            return None, 0

        wb_url = f"{WAYBACK}/{thumb_ts}im_/{img_url}"
        r = await self._fetch(wb_url)
        if not r:
            return None, 0

        data = r.content
        min_size = 1000 if suffix == "_fs.jpg" else 500

        if len(data) < min_size:
            return None, 0
        if data[:2] != JPEG_MAGIC:
            return None, 0

        path = os.path.join(output_dir, f"{pid}{suffix}")
        with open(path, "wb") as f:
            f.write(data)
        return path, len(data)
