"""Core engine: HTTP transport, Wayback API, scraping, downloading.

v1.2 resolution doctrine (from the 2026-07-08 adversarial audit): the
image server number is NOT derivable from a thumbnail URL — the only
reliable source of a photo's real image URL is its archived photo
detail page.  Download chain per photo:

    photo page  ->  real _fs.jpg  ->  real _ph.jpg
                ->  derived-guess _fs/_ph (legacy heuristic)
                ->  archived 100x75 thumbnail (last resort)
"""

from __future__ import annotations

import asyncio
import os
import re
import time
from html import unescape
from urllib.parse import quote, unquote

import httpx

from lib import __version__

# ── Constants ───────────────────────────────────────────────────────────

WAYBACK = "https://web.archive.org/web"
CDX_API = "https://web.archive.org/cdx/search/cdx"
UA = (
    f"PaisleyPonytail/{__version__} "
    "(webshots photo recovery; +https://github.com/coldbricks/paisley-ponytail)"
)
JPEG_MAGIC = b"\xff\xd8"

# Statuses worth retrying: rate limits and archive.org brownouts.
RETRY_STATUSES = {429, 500, 502, 503, 504}
# Statuses that mean "definitively not archived" — do not retry.
ABSENT_STATUSES = {404, 403, 451}


# ── Configuration ───────────────────────────────────────────────────────


class Config:
    max_concurrent: int = 4
    rate_delay: float = 0.6  # archive.org etiquette: ~1 req/s sustained
    timeout: float = 45
    max_retries: int = 4
    backoff_base: float = 2
    backoff_cap: float = 60
    deep_probe_cap: int = 60  # max profile-page snapshots fetched in --deep
    album_page_cap: int = 50  # max pagination pages per album


# ── Stats ───────────────────────────────────────────────────────────────


class Stats:
    __slots__ = (
        "downloaded", "failed", "skipped", "upgraded", "thumbs_only",
        "bytes", "pages_failed", "_t0",
    )

    def __init__(self):
        self.downloaded = 0
        self.failed = 0
        self.skipped = 0
        self.upgraded = 0      # _ph on disk replaced by recovered _fs
        self.thumbs_only = 0   # only the 100x75 thumbnail was recoverable
        self.bytes = 0
        self.pages_failed = 0  # album pages that never loaded
        self._t0 = time.monotonic()

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self._t0

    def as_dict(self, output_dir: str = "") -> dict:
        return {
            "downloaded": self.downloaded,
            "failed": self.failed,
            "skipped": self.skipped,
            "upgraded": self.upgraded,
            "thumbs_only": self.thumbs_only,
            "bytes": self.bytes,
            "pages_failed": self.pages_failed,
            "elapsed": self.elapsed,
            "output_dir": output_dir,
        }


# ── Rate limiter ────────────────────────────────────────────────────────


class _RateLimiter:
    """Global limiter: minimum gap between request starts, plus a shared
    cooldown so a 429/503 from ANY coroutine pauses ALL of them."""

    def __init__(self, delay: float):
        self._delay = delay
        self._lock = asyncio.Lock()
        self._next_ok = 0.0

    async def acquire(self):
        async with self._lock:
            now = time.monotonic()
            if self._next_ok > now:
                await asyncio.sleep(self._next_ok - now)
            self._next_ok = time.monotonic() + self._delay

    def cooldown(self, seconds: float):
        """Push the next allowed request out for everyone."""
        target = time.monotonic() + seconds
        if target > self._next_ok:
            self._next_ok = target


# ── Extraction regexes ──────────────────────────────────────────────────
# Wayback rewrites hrefs both absolute and host-relative (/web/TS/...).
# Old eras (2002-2005) serve thumbnails from thumbN.webshots.COM; the
# crawl era uses thumbNN.webshots.NET.  Path shapes vary by era, so the
# path match is deliberately generic.

RE_THUMB = re.compile(
    r"(?:https?://web\.archive\.org)?/web/(\d+)(?:im_)?/"
    r"(https?://thumb\d+\.webshots\.(?:net|com)/[^\"'<>\s]+_th\.jpg)"
)
RE_PHOTO_LINK = re.compile(
    r"(?:https?://web\.archive\.org)?/web/\d+/"
    r"(https?://[^/\"']*\.webshots\.[^/\"']+/photo/(\d+)[^\"'#?<>\s]*)"
)
RE_ALBUM_LINK = re.compile(
    r"(?:https?://web\.archive\.org)?/web/\d+/"
    r"(https?://([^/\"]*?)\.webshots\.[^/\"]+/album/([^\"#?]+))"
)
RE_PAGE_IMAGE = re.compile(
    r"(?:https?://web\.archive\.org)?/web/(\d+)(?:im_)?/"
    r"(https?://(?:image\d+\.webshots\.(?:com|net)"
    r"|community\.webshots\.com(?::80)?/sym/image\d+)"
    r"/[^\"'<>\s]+_(?:ph|fs)\.jpg)"
)
RE_TITLE = re.compile(r"<title>([^<]{1,200})</title>", re.IGNORECASE)
RE_USER_PAGE = re.compile(
    r"^https?://community\.webshots\.com(?::80)?/user/([^/?#]+)", re.IGNORECASE
)


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

    async def _get(self, url: str) -> tuple[httpx.Response | None, int]:
        """Rate-limited GET with retries.

        Returns (response, status).  status semantics:
          200        -> response present
          404/403/.. -> definitively absent (no retry)
          0          -> transport failure / retries exhausted (transient)
        """
        last_status = 0
        for attempt in range(self.cfg.max_retries):
            await self._limiter.acquire()
            try:
                r = await self._client.get(url)
                if r.status_code == 200:
                    return r, 200
                if r.status_code in ABSENT_STATUSES:
                    return None, r.status_code
                last_status = r.status_code
                if r.status_code in RETRY_STATUSES:
                    wait = min(
                        self.cfg.backoff_base ** (attempt + 1),
                        self.cfg.backoff_cap,
                    )
                    if r.status_code in (429, 503):
                        # archive.org is telling everyone to slow down
                        self._limiter.cooldown(wait)
                    await asyncio.sleep(wait)
                    continue
                return None, r.status_code
            except httpx.HTTPError:
                last_status = 0
                wait = min(
                    self.cfg.backoff_base ** (attempt + 1), self.cfg.backoff_cap
                )
                await asyncio.sleep(wait)
        return None, last_status

    async def _fetch_text(self, url: str) -> str | None:
        r, _ = await self._get(url)
        return r.text if r else None

    # ── Wayback CDX API ─────────────────────────────────────────────

    async def cdx_search(
        self,
        url: str,
        match_type: str | None = None,
        collapse: str | None = None,
        status_filter: str | None = None,
        limit: int = 0,
    ) -> list[list[str]] | None:
        """Query Wayback CDX API.

        Returns rows (header stripped), [] when genuinely empty, or
        None on transport failure — callers MUST distinguish "no
        captures" from "archive.org unreachable".

        NOTE: never pass a negative limit — the CDX API treats limit=-N
        as "last N rows", which silently truncates results.
        """
        query = f"{CDX_API}?url={quote(url, safe='/:.')}&output=json"
        if match_type:
            query += f"&matchType={match_type}"
        if collapse:
            query += f"&collapse={collapse}"
        if status_filter:
            query += f"&filter=statuscode:{status_filter}"
        if limit > 0:
            query += f"&limit={limit}"
        r, status = await self._get(query)
        if not r:
            return None if status == 0 or status in RETRY_STATUSES else []
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
        return [r[1] for r in reversed(rows)] if rows else []

    # ── Page loading ────────────────────────────────────────────────

    async def load_page(self, original_url: str, timestamp: str) -> str | None:
        """Fetch any original URL through Wayback playback at a timestamp."""
        return await self._fetch_text(f"{WAYBACK}/{timestamp}/{original_url}")

    async def load_profile(
        self, username: str, timestamp: str | None = None
    ) -> tuple[str | None, str | None]:
        """Load a user's profile page.  Returns (timestamp, html)."""
        base = f"http://community.webshots.com/user/{quote(username, safe='')}"
        if not timestamp:
            ts_list = await self.get_timestamps(base)
            if not ts_list:
                return None, None
            timestamp = ts_list[0]
        html = await self.load_page(base, timestamp)
        # Guard against Wayback redirecting to modern webshots.com
        if html and "community.webshots.com" not in html and "album/" not in html:
            return timestamp, None
        return timestamp, html

    # ── Extraction ──────────────────────────────────────────────────

    @staticmethod
    def extract_albums(html: str) -> list[tuple[str, str, str]]:
        """Extract album URLs from profile HTML.

        Returns [(original_url, category_subdomain, album_id), ...].
        """
        seen: set[str] = set()
        results: list[tuple[str, str, str]] = []
        for full_url, subdomain, album_id in RE_ALBUM_LINK.findall(html):
            # normalize: pagination path suffix (/album/ID/2) is not a
            # distinct album
            album_id = album_id.rstrip("/").split("/")[0]
            if album_id and album_id not in seen:
                seen.add(album_id)
                base = full_url.split("/album/")[0] + f"/album/{album_id}"
                results.append((base, subdomain, album_id))
        return results

    @staticmethod
    def extract_profile_pages(html: str, username: str) -> set[str]:
        """Find same-user profile pagination links (/user/NAME/2) in HTML."""
        pat = re.compile(
            rf'/web/\d+/(https?://community\.webshots\.com(?::80)?'
            rf'/user/{re.escape(username)}(?:-date)?/\d+)["\'#?]',
            re.IGNORECASE,
        )
        return {m.replace(":80/", "/") for m in pat.findall(html)}

    @staticmethod
    def extract_album_entries(html: str) -> list[tuple[str, str, str | None]]:
        """Extract (wayback_ts, thumb_url, photo_page_url|None) from album HTML.

        Thumbs are paired with the nearest preceding photo-page link —
        album grids emit <a href=photo><img src=thumb> blocks, so the
        anchor for a thumb always appears shortly before it.
        """
        events: list[tuple[int, str, tuple]] = []
        for m in RE_PHOTO_LINK.finditer(html):
            events.append((m.start(), "photo", (m.group(1),)))
        for m in RE_THUMB.finditer(html):
            events.append((m.start(), "thumb", (m.group(1), m.group(2))))
        events.sort(key=lambda e: e[0])

        # A thumb can occur multiple times (filmstrip widgets have no
        # anchors; the main grid does) — keep the occurrence that
        # carries a photo-page link.
        found: dict[str, tuple[str, str, str | None]] = {}
        last_photo: tuple[int, str] | None = None
        for pos, kind, data in events:
            if kind == "photo":
                last_photo = (pos, data[0])
            else:
                ts, thumb_url = data
                photo_url = None
                if last_photo and pos - last_photo[0] < 3000:
                    photo_url = last_photo[1]
                prev = found.get(thumb_url)
                if prev is None or (prev[2] is None and photo_url):
                    found[thumb_url] = (ts, thumb_url, photo_url)
        return list(found.values())

    @staticmethod
    def extract_page_title(html: str) -> str | None:
        """Human title of an album/photo page.

        Attribute-less <h1> carries the real album/photo name on
        crawl-era pages; <title> is often a generic site slogan, so it
        is only the fallback.
        """
        m = re.search(r"<h1>([^<]{2,120})</h1>", html)
        if not m:
            m = RE_TITLE.search(html)
        if not m:
            return None
        title = unescape(m.group(1)).strip()
        # Old-era pages prefix titles with the site name.
        title = re.sub(r"^Webshots Community\s*-\s*", "", title, flags=re.IGNORECASE)
        # "AlbumName pictures from travel photos on webshots" et al.
        title = re.sub(
            r"\s*(pictures? from|photos? (?:and videos? )?(?:on|at)|- webshots).*$",
            "",
            title,
            flags=re.IGNORECASE,
        ).strip(" -|")
        return title or None

    @staticmethod
    def _extract_page_variants(html: str, album_url: str) -> set[str]:
        """Find pagination variants of this album in HTML.

        Crawl-era albums paginate via ?start=N; 2002-2005 era albums
        paginate via a path segment (/album/ID/1).
        """
        album_id = album_url.rsplit("/album/", 1)[-1]
        aid = re.escape(album_id)
        variants: set[str] = set()
        for n in re.findall(
            rf'/album/{aid}\?(?:[^"\'>]*&(?:amp;)?)?start=(\d+)', html
        ):
            variants.add(f"{album_url}?start={n}")
        for n in re.findall(rf'/album/{aid}/(\d+)["\'#?]', html):
            variants.add(f"{album_url}/{n}")
        return variants

    # ── Album loading ───────────────────────────────────────────────

    async def load_album(
        self,
        album_url: str,
        timestamp: str,
        follow_pagination: bool = True,
        retry_alternate_ts: bool = True,
    ) -> tuple[list[tuple[str, str, str | None]], dict]:
        """Load album page(s).

        Returns (entries, meta):
          entries: [(wayback_ts, thumb_url, photo_page_url|None), ...]
          meta: {"title": str|None, "pages_failed": int}

        Follows both pagination styles; on a completely empty album
        (dead-host URL or capture far from `timestamp`), retries at the
        album's own archived timestamps before giving up.
        """
        entries: dict[str, tuple[str, str, str | None]] = {}
        meta: dict = {"title": None, "pages_failed": 0}

        async def crawl(ts: str):
            todo: set[str] = {album_url}
            done: set[str] = set()
            while todo and len(done) < self.cfg.album_page_cap:
                page_url = todo.pop()
                done.add(page_url)
                html = await self.load_page(page_url, ts)
                if not html:
                    meta["pages_failed"] += 1
                    continue
                if meta["title"] is None:
                    meta["title"] = self.extract_page_title(html)
                for e_ts, thumb, photo in self.extract_album_entries(html):
                    prev = entries.get(thumb)
                    if prev is None or (prev[2] is None and photo):
                        entries[thumb] = (e_ts, thumb, photo)
                if follow_pagination:
                    for v in self._extract_page_variants(html, album_url):
                        if v not in done:
                            todo.add(v)

        await crawl(timestamp)

        if not entries and retry_alternate_ts:
            # Dead-host album URL or bad snapshot: find its real captures.
            rows = await self.cdx_search(album_url, status_filter="200")
            if rows:
                alt_ts = [r[1] for r in rows if r[1] != timestamp]
                for ts in alt_ts[-2:]:  # newest archived captures
                    await crawl(ts)
                    if entries:
                        break

        return list(entries.values()), meta

    # ── Callsign sweep (username discovery) ─────────────────────────

    async def find_usernames(
        self, prefix: str, cap: int = 5000
    ) -> tuple[list[dict], bool] | None:
        """List archived screen names starting with `prefix`.

        One CDX prefix query, collapsed to unique URLs — the archive's
        own index doubles as a username autocomplete.  Returns
        ([{name, pages, first, last}, ...], truncated) or None on
        transport failure.  `pages` counts distinct archived user-page
        URLs — a proxy for how substantial the account was.
        """
        rows = await self.cdx_search(
            f"community.webshots.com/user/{prefix}",
            match_type="prefix",
            collapse="urlkey",
            status_filter="200",
            limit=cap,
        )
        if rows is None:
            return None
        users: dict[str, dict] = {}
        for row in rows:
            ts, original = row[1], row[2]
            m = RE_USER_PAGE.match(original)
            if not m:
                continue
            # /user/NAME-date is the site's date-sorted view, not a user.
            # Strip URL-decoding artifacts (stray spaces, trailing dots)
            # or the same account shows up as two strips.
            cased = re.sub(r"-date$", "", unquote(m.group(1)), flags=re.IGNORECASE)
            cased = " ".join(cased.split()).strip(" .,")
            if not cased:
                continue
            u = users.setdefault(
                cased.lower(),
                {"casings": {}, "pages": 0, "first": ts, "last": ts},
            )
            u["casings"][cased] = u["casings"].get(cased, 0) + 1
            u["pages"] += 1
            u["first"] = min(u["first"], ts)
            u["last"] = max(u["last"], ts)
        results = [
            {
                "name": max(u["casings"], key=u["casings"].get),
                "pages": u["pages"],
                "first": u["first"],
                "last": u["last"],
            }
            for u in users.values()
        ]
        return results, len(rows) >= cap

    # ── Deep discovery (CDX prefix enumeration) ─────────────────────

    async def discover_profile_pages(
        self, username: str
    ) -> list[tuple[str, list[str]]] | None:
        """Enumerate every archived profile album-list page for a user.

        The raw freeze-frame megawarcs are access-restricted (401) and
        the old search index item is dark, but their contents were
        ingested into the Wayback Machine — a CDX prefix query surfaces
        profile pagination pages (/user/NAME/2) and the date-sorted
        variant (/user/NAME-date/0) from every site era, 2002-2013.

        Returns [(original_url, [timestamps...]), ...] or None on
        transport failure.
        """
        rows = await self.cdx_search(
            f"community.webshots.com/user/{username}",
            match_type="prefix",
            status_filter="200",
        )
        if rows is None:
            return None
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

    @staticmethod
    def sample_timestamps(ts_list: list[str], k: int = 4) -> list[str]:
        """First, last, and evenly-spaced middles — eras matter."""
        if len(ts_list) <= k:
            return list(dict.fromkeys(ts_list))
        idx = [round(i * (len(ts_list) - 1) / (k - 1)) for i in range(k)]
        return list(dict.fromkeys(ts_list[i] for i in idx))

    # ── URL derivation (legacy heuristic — fallback only) ───────────

    @staticmethod
    def thumb_candidates(thumb_url: str, suffix: str = "_fs.jpg") -> list[str]:
        """GUESS image URLs from a thumbnail URL, best-first.

        Crawl-era hosts are audit-confirmed non-derivable (thumb13
        photos live on image04, image12, image20...), so these are
        fallbacks when the photo detail page was never archived.

        Old era (2002-2005) IS derivable: /s/thumbN/ thumbnails map to
        community.webshots.com/sym/imageN/ using the PATH digit —
        verified against the one archived 2003 photo page
        (sym/image4/0/50/81/71105081mpCGrT_fs.jpg from /s/thumb4/...).
        """
        m_host = re.match(r"https?://thumb(\d+)\.webshots\.(?:net|com)/", thumb_url)
        if not m_host:
            return []
        host_n = m_host.group(1)

        m_s = re.search(r"/s/thumb(\d+)/(.+)_th\.jpg$", thumb_url)
        if m_s:
            path_n, tail = m_s.groups()
            return [
                f"http://community.webshots.com/sym/image{path_n}/{tail}{suffix}",
                f"http://image{host_n}.webshots.com/{host_n}/{tail}{suffix}",
            ]

        # /t/A/B/rest: drop the A/B pair (observed real form is
        # imageXX.webshots.com/XX/rest)
        m_t = re.search(r"/t/\d+/\d+/(.+)_th\.jpg$", thumb_url)
        if m_t:
            return [f"http://image{host_n}.webshots.com/{host_n}/{m_t.group(1)}{suffix}"]

        m_plain = re.search(r"/t/(.+)_th\.jpg$", thumb_url)
        if m_plain:
            return [f"http://image{host_n}.webshots.com/{host_n}/{m_plain.group(1)}{suffix}"]

        return []

    @staticmethod
    def photo_id(thumb_url: str) -> str | None:
        """Extract photo ID + hash from thumbnail filename."""
        m = re.search(r"/(\d+\w+)_th\.jpg$", thumb_url)
        return m.group(1) if m else None

    # ── Photo-page resolution ───────────────────────────────────────

    async def resolve_image_url(
        self, photo_page_url: str, timestamp: str
    ) -> tuple[str | None, str | None]:
        """Fetch the archived photo detail page; return (image_url, title).

        The page's <img src> carries the REAL imageNN server URL — the
        only trustworthy source for it.
        """
        html = await self.load_page(photo_page_url, timestamp)
        if not html:
            return None, None
        title = self.extract_page_title(html)
        m = RE_PAGE_IMAGE.search(html)
        if not m:
            return None, title
        return m.group(2), title

    # ── Downloading ─────────────────────────────────────────────────

    async def _try_image(
        self, ts: str, img_url: str, min_size: int
    ) -> tuple[bytes | None, bool]:
        """Fetch one image variant via Wayback.

        Returns (data|None, definitively_absent).
        """
        r, status = await self._get(f"{WAYBACK}/{ts}im_/{img_url}")
        if r is None:
            return None, status in ABSENT_STATUSES
        data = r.content
        if len(data) < min_size or data[:2] != JPEG_MAGIC:
            return None, True  # archived, but not a usable JPEG
        return data, False

    async def download_photo(
        self,
        thumb_ts: str,
        thumb_url: str,
        photo_page_url: str | None,
        output_dir: str,
        stats: Stats,
    ) -> dict:
        """Download one photo through the resolution chain.

        Returns a per-photo record dict for the manifest:
        {id, variant, size, file, title} — variant in
        fs | ph | th | skip | failed.
        """
        async with self._sem:
            pid = self.photo_id(thumb_url)
            if not pid:
                stats.failed += 1
                return {"id": None, "variant": "failed", "size": 0}

            record: dict = {"id": pid, "variant": "failed", "size": 0, "title": None}
            fs_path = os.path.join(output_dir, f"{pid}_fs.jpg")
            ph_path = os.path.join(output_dir, f"{pid}_ph.jpg")
            fs404_marker = os.path.join(output_dir, f"{pid}.fs404")

            def _ok(p):
                return os.path.isfile(p) and os.path.getsize(p) > 500

            # Resume: full-size on disk is final.
            if _ok(fs_path):
                stats.skipped += 1
                record.update(variant="skip", size=os.path.getsize(fs_path),
                              file=os.path.basename(fs_path))
                return record
            # _ph (or last-resort _th) on disk is final only if _fs is
            # known-absent; otherwise this run attempts an upgrade.
            had_ph = _ok(ph_path)
            th_path = os.path.join(output_dir, f"{pid}_th.jpg")
            if os.path.isfile(fs404_marker):
                for existing in (ph_path, th_path):
                    if os.path.isfile(existing) and os.path.getsize(existing) > 300:
                        stats.skipped += 1
                        record.update(variant="skip",
                                      size=os.path.getsize(existing),
                                      file=os.path.basename(existing))
                        return record

            # ── Resolve the real image URL from the photo page ──────
            real_url: str | None = None
            if photo_page_url:
                real_url, title = await self.resolve_image_url(
                    photo_page_url, thumb_ts
                )
                record["title"] = title

            candidates: list[str] = []
            for suffix in ("_fs.jpg", "_ph.jpg"):
                if real_url:
                    candidates.append(
                        re.sub(r"_(?:ph|fs)\.jpg$", suffix, real_url)
                    )
                for guess in self.thumb_candidates(thumb_url, suffix):
                    if guess not in candidates:
                        candidates.append(guess)

            fs_definitively_absent = True
            for img_url in candidates:
                is_fs = img_url.endswith("_fs.jpg")
                if had_ph and not is_fs:
                    break  # upgrade run: only _fs candidates matter
                data, absent = await self._try_image(
                    thumb_ts, img_url, 1000 if is_fs else 500
                )
                if data:
                    path = fs_path if is_fs else ph_path
                    with open(path, "wb") as f:
                        f.write(data)
                    if is_fs and had_ph:
                        stats.upgraded += 1
                        record["upgraded"] = True
                    else:
                        stats.downloaded += 1
                    stats.bytes += len(data)
                    record.update(
                        variant="fs" if is_fs else "ph",
                        size=len(data), file=os.path.basename(path),
                    )
                    return record
                if is_fs and not absent:
                    fs_definitively_absent = False

            # Every _fs candidate 404'd for real: stop future upgrade runs.
            if fs_definitively_absent and (had_ph or candidates):
                try:
                    open(fs404_marker, "w").close()
                except OSError:
                    pass

            if had_ph:
                stats.skipped += 1  # keep the _ph we already have
                record.update(variant="skip", size=os.path.getsize(ph_path),
                              file=os.path.basename(ph_path))
                return record

            # ── Last resort: save the archived thumbnail itself ─────
            data, _ = await self._try_image(thumb_ts, thumb_url, 300)
            if data:
                th_path = os.path.join(output_dir, f"{pid}_th.jpg")
                with open(th_path, "wb") as f:
                    f.write(data)
                stats.thumbs_only += 1
                stats.bytes += len(data)
                record.update(variant="th", size=len(data),
                              file=os.path.basename(th_path))
                return record

            stats.failed += 1
            return record
