# Paisley Ponytail

![Paisley Ponytail nose art](assets/nose_art.jpg)

**The Webshots Resurrector — bring lost photos back to life.**

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-3c7a3c)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-3c7a3c)](LICENSE)
![Megawarcs on frequency](https://img.shields.io/badge/on%20frequency-2%2C437%20megawarcs%20%2F%20105.9%20TB-1f3d1f)

Webshots hosted 14 million users' photos from 1995 until December 2012, when its final owner deleted everything. Archive Team scrambled an emergency crawl in the last weeks and hauled 105.9 TB into the Internet Archive — then the extraction tooling died in 2016 and the wreckage sat locked in 2,437 fifty-gigabyte WARC blobs for a decade.

Whether you're about to solve a 20-year-old mystery or surfing for the most
devastating blackmail material for your 30th high school reunion, chances are
the 105.9 TB of compressed image data sitting in the Webshots archive has what
you're looking for.

The photos are still in there. This is the recovery aircraft.

---

## Preflight

```
pip install -r requirements.txt
```

Python 3.10+. Windows, macOS, Linux. No APIs. No logins. No encryption —
exactly how Webshots ran things, which you probably now regret.

## Cleared for departure

```
python resurrector.py find   cooldave           # half-remember the name? sweep for it
python resurrector.py search yourscreenname     # what's on the scope?
python resurrector.py pull   yourscreenname     # bring it home
```

`search` gives you the flight-strip board — every archived album, with its
original name and photo count. `pull` recovers everything and writes a
**`gallery.html`** contact sheet: open it in a browser and you're looking at
your albums again, original titles, original captions, twenty years later.
Yes, including the captions. You were very funny in 2004.

![a real pull, replayed from the actual logs](assets/demo.gif)

![search — the flight-strip board](assets/screenshot_search.png)


Interrupted mid-pull? Run the same command again. Finished photos hold at the
gate; photos that only landed at 800×600 get an automatic upgrade attempt to
full-size on every pass until the archive definitively says it isn't there.

### Extended operations

```
python resurrector.py search yourscreenname --deep      # dig back to 2002
python resurrector.py pull   yourscreenname --album ID  # one album only
python resurrector.py pull   yourscreenname -j 6        # more concurrency (max 8)
```

**Only half-remember the name?** `find` sweeps the archive's own index for
every screen name matching a prefix and boards them as numbered strips —
screen name, how many archived pages, first and last seen. Then just say
intentions: type `3` to search strip 3, `p3` to pull it on the spot. Spaces
are handled — `find cool dave` sweeps `cooldave`, `cool_dave`, and
`cool-dave` — because Webshots names never had spaces but memories do.

`--deep` runs a CDX prefix sweep over every archived variant of your profile —
pagination pages, the date-sorted view, every site redesign from 2002 to 2013 —
and resurrects albums you deleted years before the site died. You deleted them.
You moved on. The Wayback Machine did neither.

## How it actually works

The Wayback Machine is the only door: the raw freeze-frame megawarcs went
access-restricted (HTTP 401) years ago and the old username index is dark. But
everything Archive Team captured was ingested into Wayback, so recovery is a
CDX-navigation problem:

```
screen name
  └─▸ CDX API: every capture of community.webshots.com/user/NAME (2002–2013)
       └─▸ profile pages → album links (+ pagination: ?start=N and /album/ID/N)
            └─▸ album grids → (thumbnail, photo-page) pairs + album titles
                 └─▸ photo detail page → the photo's REAL image URL + caption
                      └─▸ _fs.jpg original → _ph.jpg 800×600 → thumbnail
```

Two hard-won facts drive the design, both established empirically against live
archive data — every claim below survived independent attempts to refute it:

- **You cannot guess a photo's image server.** A thumbnail on `thumb13` maps
  to full-size copies on `image04`, `image12`, `image20` — unrelated numbers.
  The only trustworthy source is the archived photo detail page, so the tool
  resolves every photo through its page. (Naive URL derivation — what every
  dead Webshots scraper attempted — silently misses almost everything.)
- **The 2002–2005 era is a different aircraft.** Old thumbnails ride
  `thumbN.webshots.com` with per-image load-balancer host digits (2002 was a
  lawless time), old albums paginate by path segment, and old full-size images
  live at `community.webshots.com/sym/imageN/…` — which *is* derivable, from
  the thumbnail's path digit. Paisley Ponytail speaks both eras.

Every photo descends a fallback ladder — real full-size, real 800×600, derived
guesses, and finally the archived thumbnail itself — so you always land with
*something*, and the manifest records exactly which rung each photo reached.

### Field notes from the wreckage

Things the archive will not tell you until you hit them:

- The CDX API interprets `limit=-1` as *"return only the last row."* An early
  version of this tool queried with `-1` for "unlimited" and silently saw 1 of
  33 snapshots for its own test user. If you build on the CDX API, know this.
- Some full-size images were archived **as their 404 pages** — the crawler
  arrived after the image server had already given up, and Wayback faithfully
  preserved the failure. Downloads are validated by JPEG magic bytes, never by
  HTTP status alone.
- Wayback playback rewrites the same `href` absolute on one page and
  host-relative on the next, depending on which rendering path served it.
  Every extractor here accepts both, because trusting one form loses photos.
- Album grids emit each thumbnail *twice* — anchor-less in a filmstrip widget,
  anchored in the photo grid. First-match pairing silently drops a third of
  the photo-page links; the parser prefers the anchored occurrence, including
  across pagination boundaries.
- A photo that fails today is retried in full on every future run, on purpose:
  the Internet Archive occasionally backfills. Definitive absence (a real 404
  on every candidate URL) is cached in a marker file; ambiguity is not.

## Reading the instruments

![pull — full-size originals landing, with the fallback ladder visible](assets/screenshot_pull.png)

| Callout | Meaning |
|---|---|
| `LANDED  FS` | Full-size original recovered — actual camera resolution |
| `LANDED  PH` | 800×600 copy recovered (full-size not archived) |
| `UPGRADED FS` | A previous 800×600 was replaced by the located original |
| `THUMB ONLY` | Only the 100×75 thumbnail survived the crawl |
| `AT GATE` | Already on disk from an earlier run |
| `MISSED APCH` | Genuinely not in the archive — you can't land a plane that never took off |

Everything lands in `output/yourname/` — one folder per album, named by the
album's original title, with `manifest.json` (per-photo records, variants,
captions) and the `gallery.html` contact sheet alongside.

And because someone will ask why the terminal feels *right*: the UI palette
is **FAA HF-STD-010** — the standard color set certified for actual ATC
displays, as evaluated on ERAM/STARS in DOT/FAA/AM-20/08. When `LANDED`
prints in green, that is the exact green a controller sees. When you search,
the tool squawks ident. When nothing matches, no beacons correlate to the
flight plan. This is not a metaphor; we pulled the sRGB values out of the
FAA's human-factors reports.

## Honest expectations

- **Account public in fall 2012** — odds are genuinely good; often most photos
  at full resolution. The Archive Team crawl was systematic.
- **Account deleted before 2012** — sometimes. Regular Wayback crawls ran from
  2002 on; `--deep` finds those albums, but early-era image coverage is patchy.
  Expect partial albums and thumbnails.
- **Albums set to private** — never archived. No tool can recover them. Your
  secrets died with the site; the one privacy feature that actually worked.

## Etiquette (read before filing complaints about speed)

archive.org is the only reason any of this still exists. All traffic funnels
through one global rate limiter (~1 request/second sustained), a 429/503 from
the tower slows *every* coroutine, retries back off exponentially, and deep
sweeps are probe-capped. The pace is a feature. Fly the published procedure.

## The NTSB docket

The full accident investigation — what Webshots was, how fourteen million
photo libraries went down with it, why the wreckage sat locked for a decade,
and the complete reverse-engineering methodology that got it open: the
three eras of URL architecture, the image-server problem, the digicam-and-
dial-up physics behind `_fs`/`_ph`/`_th`, findings, probable cause, and
recommendations.

**[Read DOCKET.md →](DOCKET.md)**

> **Operator's statement:** *It took me 9+ years to put this together, but
> the biggest reverse engineering project in internet photo history has been
> achieved. Now, I just need everyone to break it again.*

The investigation remains open: if a screen name that should work comes back
empty, [file a report](../../issues). Every failure mode gets investigated.

## Why this exists

Between 1995 and 2012, millions of people uploaded the only copies of their
family photos to Webshots. The author spent years recovering his own, one
Wayback page at a time. Nobody should have to do that twice.

---

**Tailstrike Studios × Ash Airfoil** // coldbricks · MIT license ·
Not affiliated with the Internet Archive — just grateful guests on their frequency.
