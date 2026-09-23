# Biomarker extraction

How to derive biomarkers from the 250,603 staged OCT images.

Investigated 2026-09-23. Nothing here is built yet — this is the plan and the
inventory it rests on.

---

## Key finding: ~96,000 images are already labeled

Roughly 38% of the corpus carries expert labels shipped with the source
datasets. Extracting those is parsing, not machine learning, and should happen
before any model is trained.

| Dataset | Existing labels | Labeled |
|---|---|---:|
| **OLIVES** | 16 biomarkers + BCVA + CST, per image | 9,408 |
| **Kermany** | Disease class + patient ID, encoded in path/filename | 84,484 |
| **OCTDL** | Disease, subcategory, condition, patient, eye, sex, year, dimensions | 2,064 |
| **HCMS** | **9 expert-delineated retinal surfaces** per B-scan | ~1,715 B-scans |
| **Bissig** | Manually marked layers, reflectivity tables | 1,112 files |

### OLIVES — the richest source

`OLIVES_Dataset_Labels/{full_labels,ml_centric_labels}/Biomarker_Clinical_Data_Images.csv`
(9,408 rows) gives per-image binary labels for sixteen biomarkers:

```
Atrophy / thinning of retinal layers      Disruption of EZ
DRIL                                      IR hemorrhages
IR HRF                                    Partially attached vitreous face
Fully attached vitreous face              Preretinal tissue / hemorrhage
Vitreous debris                           VMT
DRT / ME                                  Fluid (IRF)
Fluid (SRF)                               Disruption of RPE
PED (serous)                              SHRM
```

Plus `Eye_ID`, `Patient_ID`, `BCVA` (visual acuity) and `CST` (central subfield
thickness). Path format:
`/TREX DME/GILA/0201GOD/V1/OD/TREXJ_000000.tif` — trial / arm / folder / visit /
eye / image, with a scan index (n of 49).

Additional clinical data in `Clinical_Data_Images.xlsx`, `OCT-DR.xlsx`,
`OCT-DME.xlsx`.

### HCMS — ground-truth layer boundaries

`delineation/*.mat` holds manual delineations of nine retinal surfaces per
B-scan; `vol/*.vol` the raw Spectralis volumes; plus a demographics CSV
(age, sex, MS vs. control). This is the ground truth others train against,
and it converts directly into thickness measurements.

### Kermany — labels in the path

`OCT2017/{train,test}/{CNV,DME,DRUSEN,NORMAL}/CNV-4283050-2.jpeg`
→ class, randomized patient ID, image index. Splits are patient-disjoint and
should be preserved.

---

## Three tiers

### Tier 1 — Harvest existing labels *(do this first)*

Parse what already exists into one index keyed by B2 object path: pandas over
the CSVs/XLSXs, path parsing for Kermany, `scipy.io.loadmat` for HCMS.

No ML, no GPU, minutes to run. **This is also exactly what the site's metadata
search needs** — not a detour but the feature itself. Output should include a
coverage report showing what is known and missing per image, which quantifies
how much Tier 3 actually has left to do.

### Tier 2 — Derive thickness from HCMS delineations

Nine surfaces yield eight layer thicknesses (RNFL, GCL+IPL, INL, OPL, ONL, IS,
OS, RPE). Add ETDRS grid sectors for standard clinical measurements.
Deterministic geometry over boundary arrays — numpy, no model.

### Tier 3 — Infer biomarkers for the unlabeled ~154,000

The real ML work, in two directions:

- **Layer segmentation → thickness.** Train on HCMS ground truth, or adopt a
  pretrained OCT segmentation model. Yields quantitative thickness everywhere.
- **Biomarker presence.** OLIVES' 9,408 labeled images are a ready-made
  training set for the sixteen binary biomarkers. Alternatively use
  **RETFound** (Moorfields retinal foundation model) as a frozen encoder with
  lightweight heads — far less data-hungry than training from scratch.

---

## Constraints

### Formats are not uniform

| Dataset | Format | Browser-renderable |
|---|---|---|
| OCTDL | `.jpg` | yes |
| Kermany | `.jpeg` | yes |
| OLIVES | `.png` / `.tif` | yes |
| HCMS | `.mat` + `.vol` | **no** — volumetric |
| Bissig | `.hdr` / `.img` (ANALYZE 7.5) | **no** — volumetric |

~249,000 files display directly; ~1,184 need server-side conversion. That
conversion is a Worker, and it is the point at which the Cloudflare token needs
`Workers Scripts: Edit` added.

### Hardware

Apple M5, 10 cores, 16 GB RAM. Installed: numpy 2.4.6, scipy 1.18.0,
pandas 3.0.3, pyarrow 23.0.1, scikit-learn 1.9.0, Pillow 12.3.0.
**Not installed: torch, torchvision, cv2.**

Tiers 1 and 2 run comfortably. Tier 3 works via PyTorch MPS, but 16 GB is tight
— batch carefully, and expect inference across 250k images to take many hours.
Cloud GPU is worth considering for training runs specifically.

### Where results belong

Biomarkers are metadata and belong somewhere queryable, not as files in B2.
**Cloudflare D1** fits the existing stack — build the index as SQLite locally,
ship it to D1, let a Worker serve the site's search. Wrangler's OAuth session
already carries `d1 (write)`. Parquet in B2 is the fallback if the table
outgrows D1's limits.

---

## Recommended order

1. **Tier 1 index** — a day's work, no new dependencies, turns the bucket from
   250,603 anonymous objects into a searchable catalogue and unblocks the site.
2. **Tier 2 thicknesses** — small, deterministic, high-value.
3. **Tier 3** — a genuine ML project. Should not start until the coverage
   report from Tier 1 shows what is actually missing.
