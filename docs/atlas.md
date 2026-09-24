# The atlas — retinaoct.com

Faceted search over the OLIVES dataset, backed by Cloudflare D1.

Built 2026-09-24. Replaces the placeholder landing page.

---

## Stack

```
browser ──▶ Cloudflare Pages ──┬── /            static UI (no framework, no build)
                               ├── /api/*       Pages Functions ──▶ D1 (retinaoct-olives)
                               └── /img/*       Pages Function ────▶ B2 (private, read-only key)
```

| Piece | Detail |
|---|---|
| Database | D1 `retinaoct-olives`, id `238aba91-eb38-4f2a-8580-484324ca1fd3`, region ENAM |
| Rows | 78,283 images · 9,408 biomarker sets · 40 patients |
| Images | 156,566 WebP derivatives in B2 `retinaoct/web/`, 5.38 GB |
| Hosting | Cloudflare Pages project `retinaoct` |

**The API runs as Pages Functions, not a Worker.** Functions deploy under the
`Pages: Edit` permission the scoped token already has, so the
`Workers Scripts: Edit` permission originally thought necessary was not needed.

---

## Endpoints

| Route | Returns |
|---|---|
| `GET /api/search` | results + facet counts + pagination |
| `GET /api/image/:id` | full metadata, 16 biomarkers, same-eye siblings |
| `GET /img/<key>` | WebP derivative, proxied from B2, edge-cached one year |

`/api/search` parameters: `q`, `trial`, `eye`, `visit`, `bio` (comma-separated
biomarker keys), `has_bio`, `bcva_min/max`, `cst_min/max`, `sort`, `page`,
`per_page`. Facet counts are recomputed against the active filter set.

---

## Image serving

OLIVES ships **TIFF**, which browsers cannot render, so every image has two
WebP derivatives:

| Size | Dimensions | Quality | Typical |
|---|---|---|---|
| thumb | 320px wide | 72 | ~11 KB |
| full | native 504×496 | 86 | ~44 KB |

78,283 images converted with zero errors — a 98% size reduction from the
244 KB TIFF originals.

### Why a proxy rather than a public bucket

The intended design was a separate **public** B2 bucket for derivatives, with
raw data staying private. Backblaze refused:

```
no_payment_history — Account has no payment history.
Please make a payment before making a public bucket.
```

A card on file is not sufficient; B2 requires a settled invoice. Cloudflare R2
was considered and rejected — its free tier would cover the current 5.38 GB,
but it costs ~2.5× B2 per TB as the archive grows.

So images are proxied instead. The Pages Function authenticates to B2 with an
application key restricted to:

```
capabilities : listFiles, readFiles     (read-only)
bucket       : retinaoct
namePrefix   : web/
```

That key cannot reach the raw datasets, cannot write, and cannot delete. It is
stored as an encrypted Pages secret (`B2_READ_KEY_ID`, `B2_READ_KEY`,
`B2_BUCKET_NAME`) — never in this repo. B2's auth token is cached for an hour
and image responses for a year, so B2 is hit about once per object per edge
location.

**To switch to the public bucket once B2 allows it:** create the bucket,
server-side copy `web/`, set `IMG_BASE` in `public/index.html` to the public
base URL, and delete `functions/img/`. Nothing else changes.

---

## Design decisions

**Facets reflect the data, not the mockup.** The original design showed
Location, Institution, Imaging device and "35+ data sources". OLIVES is two
trials from one group with uniform equipment, so none of those exist. The
sidebar uses what is real: biomarkers, trial, eye, visit, CST and BCVA ranges.

**78,283 images indexed, not just the 9,408 annotated.**
`Clinical_Data_Images.xlsx` holds 78,185 rows — every one with BCVA, CST,
patient and eye. Indexing only the biomarker subset would have discarded 88% of
the dataset. "Annotated only" is a filter.

**Biomarker prevalence is very uneven**, so the facet list is sorted by count
and hides zero-count entries:

```
IR HRF 6,341 · Fully attached vitreous 5,222 · IRF 4,088 · DRT/ME 3,003
Partially attached vitreous 2,984 · Vitreous debris 2,836 · EZ disruption 604
Preretinal tissue 807 · SRF 233 · Atrophy 166 · SHRM 76 · DRIL 32
VMT / RPE disruption / PED (serous) 10 each
```

**No authentication and no visual similarity.** Both were in the mockup; both
were explicitly dropped. The detail panel shows other scans of the same eye,
which is an ID lookup, not image comparison.

---

## Licence obligation

OLIVES is **CC BY 4.0** — redistribution and derivatives are permitted, with
attribution as the only condition. (The MIT licence on the OLIVES GitHub
repository covers the code, not the data.) The site footer carries the full
citation, the Zenodo DOI, the CC BY link, and a statement that displayed images
are downsampled derivatives.

**Do not remove that attribution** — it is the licence condition under which
this data may be published.

---

## Rebuilding

```bash
python3 scripts/build_olives_index.py            # -> olives.db
sqlite3 olives.db .dump | grep -v '^PRAGMA' > d1.sql
wrangler d1 execute retinaoct-olives --remote --file=d1.sql

python3 scripts/convert_olives_images.py         # TIFF -> WebP
doppler run -- rclone copy ~/oct-data/web/web b2:$B2_BUCKET/web --transfers 24

doppler run -- wrangler pages deploy public --project-name retinaoct --branch main
```
