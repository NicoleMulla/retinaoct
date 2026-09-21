# Datasets

Public, de-identified retinal OCT research datasets staged into
`b2:retinaoct/datasets/`.

All sources are published research data. None contain patient-identifiable
information, which resolves the data-classification question that was open
during infrastructure setup.

---

## Status — 2026-09-20 ✅ complete

| # | Dataset | Objects | Size | State |
|---|---|---:|---:|---|
| 1 | OCTDL | 2,064 | 0.41 GB | ✅ |
| 2 | HCMS (JHU) | 72 | 3.68 GB | ✅ |
| 3 | Kermany OCT2017 **v2** | 84,484 | 5.81 GB | ✅ |
| 4 | Bissig / OHSU AD | 1,112 | 5.87 GB | ✅ |
| 5 | OLIVES | 162,871 | 52.15 GB | ✅ |
| 6 | OCTA-500 | — | — | ⏸️ skipped by request |

**Bucket total: 250,603 objects, 67.91 GB — roughly $0.41/month.**

### Verification

Every dataset's B2 object count matches its local file count exactly. A
random file from each was downloaded from B2 and SHA-256 compared against
local — 5 of 5 matched:

```
OK  octdl            amd_3071419_4.jpg                      413,384 B
OK  hcms             hc10_spectralis_macula_v1_s1_R.mat      71,094 B
OK  kermany-oct2017  CNV-2959614-3.jpeg                      60,234 B
OK  bissig-ohsu-ad   AD647_LIGHT_MARKED.hdr                     348 B
OK  olives           24.png                                 114,559 B
```

### File formats vary by dataset

Relevant when building the viewer — these are not uniformly JPEGs:

| Dataset | Format |
|---|---|
| OCTDL | `.jpg` |
| Kermany | `.jpeg` |
| OLIVES | `.png` |
| HCMS | `.mat` (MATLAB — volumes + layer delineations) |
| Bissig | `.hdr` / `.img` (ANALYZE 7.5 — volumetric) |

HCMS and Bissig are **not directly viewable in a browser**. They need
server-side conversion to render, unlike the three image-based sets.

### Kermany: v2 replaced v3

The partial v3 upload was purged and v2 chosen as canonical, per the T7 drive's
own README: *"version 3 is not substituted for the explicitly requested original
OCT2017 archive."* v2 extracts to **exactly 84,484 files**, matching the image
count published in the Kermany *Cell* paper. The v3 copy is retained locally as
a backup.

### Resolved: B2 storage cap

Uploads previously failed with `403 storage_cap_exceeded`. The cap has since
been lifted and writes now succeed. Worth remembering: **enabling billing does
not raise the storage cap** — it is a separate setting under
**Account → Caps & Alerts**, defaulting to 10 GB.

At ~65 GB stored, B2 costs roughly **$0.39/month**.

---

## ⚠️ Upload halted: B2 storage cap

The Kermany upload stopped mid-transfer:

```
403 storage_cap_exceeded — Cannot upload files, storage cap exceeded
```

Backblaze enforces an account storage cap independent of billing. It must be
raised in the B2 console under **Caps & Alerts** before the remaining ~23,884
files can be uploaded.

Once raised, resume with:

```bash
cd /Users/nicolemulla/oct-data
doppler run -- ./process.sh    # rclone copy is idempotent; it skips what exists
```

---

## Sources

### 1. OCTDL ✅
- 2,064 images, 821 patients — AMD, DME, ERM, RAO, RVO, VID
- [data.mendeley.com/datasets/sncdhf53xc/4](https://data.mendeley.com/datasets/sncdhf53xc/4)
- `OCTDL.zip` (380 MB) + `OCTDL_labels.csv`
- B2: `datasets/octdl/`

### 2. HCMS — Johns Hopkins ✅
- 35 Spectralis volumes: 14 healthy controls, 21 multiple sclerosis
- 49 B-scans each, nine manually delineated retinal boundaries
- `iacl.ece.jhu.edu/~aaron/data/OCT_Manual_Delineations-2018_June_29_b.zip` (1.8 GB)
- B2: `datasets/hcms/`
- Note: the JHU wiki hosting the link serves a self-signed certificate that
  expired in 2017. The download host itself is fine.

### 3. Kermany OCT2017 ⚠️ partial
- [data.mendeley.com/datasets/rscbjbr9sj/3](https://data.mendeley.com/datasets/rscbjbr9sj/3) — CC BY 4.0
- `ZhangLabData.zip` (8.44 GB)
- B2: `datasets/kermany-oct2017/`

**This version bundles non-retinal data.** Extracted contents:

| Directory | Files | Size | Relevant? |
|---|---:|---:|---|
| `OCT/` | 109,309 | 6.9 GB | ✅ train/test × CNV, DME, DRUSEN, NORMAL |
| `chest_xray/` | 5,861 | 1.2 GB | ❌ not retinal |
| `code/` | 9 | 68 KB | — |

5,861 chest X-ray files (1.27 GB) were uploaded before this was noticed. They
serve no purpose in a retinal archive and consume capped storage. Removing them:

```bash
doppler run -- rclone purge b2:$B2_BUCKET/datasets/kermany-oct2017/chest_xray
```

Future runs should exclude them:

```bash
rclone copy ... --exclude "chest_xray/**" --exclude "code/**"
```

### 4. Bissig / OHSU Alzheimer's ❌ blocked
- [datadryad.org/dataset/doi:10.5061/dryad.msbcc2ftc](https://datadryad.org/dataset/doi:10.5061/dryad.msbcc2ftc)
- 843.5 MB, single `.rar`, **CC0-1.0** (public domain)
- SHA-256: `8038097ef0979ad6b667165d9559bb7fb7ecb6a3231d9fc9da5c4fd56535a6c6`

**Dryad sits behind Anubis**, a JavaScript proof-of-work anti-scraper
challenge. Automated download returns an HTML "Validating…" interstitial
rather than the file. This is a deliberate access control and was not
circumvented.

**Download manually in a browser**, save to
`/Users/nicolemulla/oct-data/archives/bissig-ohsu-ad.rar`, verify the hash
above, then re-run `process.sh`. `unar` is installed to handle the `.rar`.

### 5. OLIVES ⏳ uploading
- From the T7 drive; not part of the original four. Approved for inclusion.
- `OLIVES.zip` (32 GB) + `OLIVES_Dataset_Labels.zip`
- SHA-256 **verified** against publisher value:
  `d7c7e0d9e0ed6143d7b332196563513b87f366efbd0fa43aed051f6f2417ee38`
- B2: `datasets/olives/`

**OLIVES.zip contains nested archives, not images.** Extracting it yields only
two zips plus label files:

| Nested archive | Extracts to |
|---|---|
| `TREX_DME.zip` (18 GB) | 96,051 files, 29 GB |
| `Prime_FULL.zip` (13 GB) | 66,813 files, 21 GB |

**162,871 files, 49 GB total.** A first upload attempt pushed the nested zips
as-is; that was stopped and redone after full extraction, since storing the
archives would neither be browsable nor searchable and would double storage.
Nested zips were deleted locally after extraction to reclaim disk.

Labels live in `OLIVES_Dataset_Labels/` (`Clinical_Data_Images.xlsx`,
`Biomarker_Clinical_Data_Images.csv`) in both `full_labels` and
`ml_centric_labels` variants.

### 6. OCTA-500 ⏸️ skipped
- [ieee-dataport.org/open-access/octa-500](https://ieee-dataport.org/open-access/octa-500)
- 500 subjects; OCT + OCTA volumes, vessel/FAZ/layer annotations
- Open access **but requires an IEEE DataPort account**.
- **Not present on the T7 drive** — the full volume was searched. Skipped by
  request; revisit by downloading manually into `oct-data/archives/`.

---

## Local staging

Outside the git repo, so dataset files can never be committed:

```
/Users/nicolemulla/oct-data/
├── archives/     downloaded archives
├── extracted/    decompressed contents
├── fetch.sh      resumable downloader
├── process.sh    extract + upload to B2
└── *.log
```

`process.sh` flattens redundant single top-level directories, so B2 paths stay
predictable. Both scripts are safe to re-run — downloads resume with `curl -C -`
and uploads skip existing objects.
