# Datasets

Public, de-identified retinal OCT research datasets staged into
`b2:retinaoct/datasets/`.

All sources are published research data. None contain patient-identifiable
information, which resolves the data-classification question that was open
during infrastructure setup.

---

## Status — 2026-09-19

| # | Dataset | Objects in B2 | Size | State |
|---|---|---:|---:|---|
| 1 | OCTDL | 2,064 | 0.41 GB | ✅ complete |
| 2 | HCMS (JHU) | 72 | 3.68 GB | ✅ complete |
| 3 | Kermany OCT2017 | 91,295 / 115,179 | 6.96 GB | ⚠️ **partial** |
| 4 | Bissig / OHSU AD | 0 | — | ❌ blocked |
| 5 | OCTA-500 | 0 | — | ❌ blocked |

**Bucket total: 93,431 objects, 11.05 GB.**

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

### 5. OCTA-500 ❌ blocked
- [ieee-dataport.org/open-access/octa-500](https://ieee-dataport.org/open-access/octa-500)
- 500 subjects; OCT + OCTA volumes, vessel/FAZ/layer annotations
- Open access **but requires an IEEE DataPort account**. Log in and download
  manually, then stage into `oct-data/archives/`.

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
