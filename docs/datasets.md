# Datasets

Public, de-identified retinal OCT research datasets staged into
`b2:retinaoct/datasets/`.

All sources are published research data. None contain patient-identifiable
information, which resolves the data-classification question that was open
during infrastructure setup.

---

## Status — 2026-09-20

| # | Dataset | Objects in B2 | Size | State |
|---|---|---:|---:|---|
| 1 | OCTDL | 2,064 | 0.41 GB | ✅ complete |
| 2 | HCMS (JHU) | 72 | 3.68 GB | ✅ complete |
| 3 | Kermany OCT2017 v2 | 0 | — | ⬜ staged locally, blocked on cap |
| 4 | Bissig / OHSU AD | 0 | — | ⬜ staged locally, blocked on cap |
| 5 | OLIVES | 0 | — | ⬜ on T7, not yet extracted |
| 6 | OCTA-500 | 0 | — | ⏸️ skipped by request |

**Bucket total: 2,136 objects, 4.09 GB.**

### Staged locally, ready to upload

| Dataset | Files | Size | Location |
|---|---:|---:|---|
| Kermany v2 | 84,484 | 5.6 GB | `oct-data/extracted/kermany-oct2017-v2/` |
| Bissig | 1,112 | 5.5 GB | `oct-data/extracted/bissig-ohsu-ad/` |
| Kermany v3 (backup) | 115,179 | 8.1 GB | `oct-data/extracted/kermany-oct2017/` |
| OLIVES | — | 32 GB zip | `/Volumes/T7/ret-dataset/OLIVES/` |

### Kermany: v2 replaced v3

The partial v3 upload was purged and v2 chosen as canonical, per the T7 drive's
own README: *"version 3 is not substituted for the explicitly requested original
OCT2017 archive."* v2 extracts to **exactly 84,484 files**, matching the image
count published in the Kermany *Cell* paper. The v3 copy is retained locally as
a backup.

### ⚠️ Blocker: B2 storage cap still enforced

Uploads fail with `403 storage_cap_exceeded` even after account changes were
made. Note that **enabling billing does not raise the storage cap** — it is a
separate setting at **B2 Console → Account → Caps & Alerts → Storage Cap**,
defaulting to 10 GB.

Full set needs roughly **60 GB** of cap (~$0.33/month at B2 rates).

Resume once raised:

```bash
cd /Users/nicolemulla/oct-data
doppler run -- ./upload_t7.sh      # Bissig + Kermany v2
```

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

### 5. OLIVES ⬜ pending
- Found on the T7 drive; not part of the original four.
- `OLIVES.zip` (32 GB) + `OLIVES_Dataset_Labels.zip`
- Published SHA-256: `d7c7e0d9e0ed6143d7b332196563513b87f366efbd0fa43aed051f6f2417ee38`
- Retinal OCT paired with clinical/biomarker labels. Approved for upload;
  blocked on the storage cap.

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
