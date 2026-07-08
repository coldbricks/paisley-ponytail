# CLAUDE.md — Paisley Ponytail (the Webshots Resurrector)

> 105.9 TB of deleted Webshots photos live inside 2,437 megawarc blobs
> on archive.org. The raw blobs are 401-walled, the old index is dark —
> but everything was ingested into the Wayback Machine. We are the key.

---

## Prime Directives

1. **This is a data recovery project.** Given a username, find and download their Webshots photos. A false negative (missing recoverable photos) is worse than being slow.
2. **The Wayback Machine is the ONLY door.** Verified 2026-07-08: every freeze-frame collection item has `access-restricted-item: true` (raw downloads 401 for everyone), and the `webshots-freeze-frame-index` item is dark (`is_dark: true`). Do not build against raw megawarc/CDX-file access — it is gone.
3. **Never guess image URLs.** Audit-proven 2026-07-08: the image server number is NOT derivable from a thumbnail URL (thumb13 photos live on image04, image12, image20…). The photo detail page's `<img src>` is the only source of truth. Guessing is fallback-only.
4. **Be a guest at archive.org.** Global rate limiter (~1 req/s sustained), shared cooldown on 429/503, contact URL in the User-Agent. If a change could hammer their servers by default, it is wrong.
5. **Always leave the user with something.** Full-size → 800×600 → archived thumbnail. Resume must never lose work; interrupted runs must save manifests.

---

## Project Identity

| Field | Value |
|---|---|
| **Product name** | Paisley Ponytail (subtitle: the Webshots Resurrector) |
| **Repo** | `C:\Users\coldb\webshots-resurrector` → github.com/coldbricks/paisley-ponytail (PUBLIC; renamed from webshots-resurrector, old URL redirects) |
| **Stack** | Python 3.10+ (developed on 3.14/Windows 11), httpx + rich; requirements.txt |
| **Brand** | Tailstrike Studios × Ash Airfoil // coldbricks; WWII nose-art mascot (assets/nose_art.jpg); tower-cab terminal UI (Zulu clock, flight strips, LANDED/MISSED APCH callouts) |
| **Distribution** | Shared on Reddit threads for people seeking lost accounts — first-run UX on Windows matters |

## File Map (real, v1.2.0)

| Path | Purpose |
|---|---|
| `resurrector.py` | CLI: recon/scan/deep phases, search + pull commands, manifest v2 |
| `lib/engine.py` | Async engine: rate-limited transport, CDX API, extraction regexes, photo-page resolution, download chain |
| `lib/ui.py` | rich display layer (ATC aesthetic); forces UTF-8 stdout on Windows |
| `lib/gallery.py` | Self-contained gallery.html contact sheet written after every pull |
| `lib/__init__.py` | `__version__` — single source of truth |
| `assets/nose_art.jpg` | The pony. README hero + social preview art |

## Architecture — the recovery pipeline

```
username
  → CDX exact query (recon; distinguishes [] "no captures" from None "archive.org down")
  → latest profile + /user/NAME/N pagination pages (scan)
  → [--deep] CDX prefix query → every profile-page variant 2002–2013,
     sampled first/last/middles, capped at deep_probe_cap probes
  → per album: crawl pagination (?start=N crawl-era, /album/ID/N old-era),
     extract (thumb, photo-page) pairs + album title from plain <h1>;
     zero-thumb albums retry at their own CDX capture timestamps
  → per photo: fetch photo detail page → real imageNN URL + caption
     → try real _fs → real _ph → derived guess (legacy heuristic) → thumbnail
  → manifest.json (per-album + per-photo records) + gallery.html
```

Resume semantics: `_fs` on disk = final. `_ph` on disk = upgrade attempt next run, unless `<pid>.fs404` marker says full-size is definitively not archived (404), which stops future retries. Transient failures (5xx/network) never demote or mark — they stay failed and retryable.

## Domain Knowledge (verified)

### Webshots URL truths
```
community.webshots.com/user/NAME          profile (also /NAME/2, /NAME-date/0 pagination)
SUBDOMAIN.webshots.com/album/ID           album; crawl-era pagination ?start=N (grid ~42/page),
                                          2002-05 era pagination /album/ID/N
SUBDOMAIN.webshots.com/photo/LONGID       photo detail page — contains the REAL image URL
imageNN.webshots.com/...jpg               crawl-era image servers; NN unrelated to thumb host NN
community.webshots.com/sym/imageN/...jpg  OLD-ERA (2002-05) images; N = the /s/thumbN PATH digit
                                          (derivable! verified vs 2003 photo page; archive coverage patchy)
thumbNN.webshots.net/...  (crawl era)     thumbnails; .COM host + /s/thumbN/ paths in 2002-2005 era
                                          (old thumb HOST digit is a per-image load balancer — meaningless)
_fs.jpg = original resolution | _ph.jpg = 800×600 | _th.jpg = 100×75
Album grids: thumbs appear anchor-less in filmstrip widgets AND anchored in the
grid — pairing must prefer the anchored occurrence (cross-page too).
Album titles: attribute-less <h1>; <title> is a generic slogan.
```

### archive.org facts
- Wayback CDX API: `web.archive.org/cdx/search/cdx?url=...&output=json`. **Never pass a negative limit** — `limit=-N` means "last N rows" and silently truncates (this bug shipped in v1.0).
- `matchType=prefix` on `community.webshots.com/user/NAME` surfaces all profile-page variants; filter rows against an anchored regex — other users share prefixes.
- Image fetches through playback: `web.archive.org/web/<ts>im_/<original>`.
- Freeze-frame collection: 2,437 items; early items hold raw `.tar`, later ones megawarc+CDX — all irrelevant now (401).
- Forum history: warctozip.archive.org dead since ~2016 (no DNS); raw downloads were open until at least 2018, restricted later.

## Etiquette limits (do not loosen without cause)

- `rate_delay` 0.6s global; 429/503 triggers shared cooldown (backoff wait applies to ALL coroutines).
- Retry statuses: 429/500/502/503/504. Definitive-absent: 404/403/451 — never retried.
- `-j` capped at 8; `deep_probe_cap` 60; `album_page_cap` 50.

## Validation ledger

- **bexbee12** is the canonical test user. v1.0 found 538 photos; v1.1 pagination found 667; `--deep` adds +52 old-era albums (0 photos each until old-era extraction is proven — watch this).
- 2026-07-08 ultracode audit: 55 agents, 22 confirmed findings, 0 refuted. Highlights: image-server derivation empirically false (near-100% pull failure), `limit=-1` truncation, old-era thumb hosts `.com`, path-segment pagination, CDX error/empty conflation. All addressed in v1.2.
- Reproduce era evidence: thumb13→image12 (photo 149910057gOoGRH), thumb13→image04 (113686093oWWsjM), /t/ thumb13→image20 (331307972aadgQz).

## Working notes

- Windows first: UTF-8 stdout forced in `lib/ui.py` before rich binds (cp1252 crashed v1.0). Docs say `python`, not `python3`.
- Test extraction offline against saved album HTML before hitting archive.org (scratchpad keeps `album_test.html`).
- Known gaps: CDX enumeration of ?start pages (vs HTML-link following) not implemented; old-era photo detail pages are sparsely archived, so old-era captions are rare and recovery there leans on the sym/imageN derivation + thumbnail fallback.
