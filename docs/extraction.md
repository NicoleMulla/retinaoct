# Biomarker extraction

Running models over the images and recording what each one found, with
attribution.

Phase 1 (setup and small-scale testing) — 2026-09-24.

---

## Provenance model

Every biomarker value is attributed to whatever produced it.

```sql
biomarker_sources(id, key, name, kind, version, notes)   -- kind: expert | model | algorithm
biomarker_values(image_id, source_id, biomarker, value, confidence)
```

`value` is 0/1 for binary findings and a measurement for continuous ones.
`confidence` holds the model's probability and is NULL for expert labels.
Multiple sources coexist per image, so model output never overwrites or is
confused with human annotation.

The wide `biomarkers` table is retained as a materialised view for fast
faceting — D1 bills per row read (see `docs/atlas.md`).

### Registered sources

| id | key | kind | Values | Images |
|---:|---|---|---:|---:|
| 1 | `olives_expert` | expert | 150,528 | 9,408 |
| 2 | `thickness_classical_v1` | algorithm | 30 | 15 |
| 3 | `retfound_oct_cnv_dme_dru_v1` | model | 48 | 12 |

---

## Method 1 — classical ILM/RPE thickness

`scripts/extract/thickness_classical.py`

No model, no training. Locates the inner limiting membrane and the retinal
pigment epithelium per A-scan and measures the distance between them; the
central-subfield median is directly comparable to the CST already recorded for
every OLIVES image, which makes the method **self-validating**.

| Metric | Value |
|---|---|
| Pearson r vs recorded CST | **0.636** |
| MAE | 64.3 µm |
| Fitted scale | 3.53 µm/px |

The fitted scale landing near Spectralis's true 3.87 µm/px is independent
evidence the geometry is roughly right. This is real signal, **not clinical
accuracy** — treat it as a baseline.

**One non-obvious fix mattered.** The first implementation took the RPE to be
the brightest row, which collapsed on pathology: an image with CST 602 µm
measured 48 px, because in oedema the global intensity maximum is often a
hyperreflective focus well above the RPE. Taking the *deepest* hyperreflective
band instead fixed it, and removed all segmentation failures.

Outputs `thickness_central_um`, `thickness_mean_um`.

---

## Method 2 — RETFound (ViT-L, OCT pathology)

`scripts/extract/retfound_oct.py`

MAE-pretrained retinal foundation model fine-tuned for four classes: CNV, DME,
drusen, normal. Weights `bitfount/RETFound_MAE_OCT_CNV_DME_DRU` (1.2 GB,
ungated). Runs on Apple MPS.

**Class order is calibrated, not assumed.** The config records no label
mapping, so the script infers it from Kermany test images whose class is known
from their directory:

```
            idx0     idx1     idx2     idx3
CNV        0.899    0.047    0.030    0.024
DME        0.044    0.885    0.026    0.044
DRUSEN     0.121    0.040    0.797    0.042
NORMAL     0.024    0.078    0.041    0.857
```

A clean diagonal — order is `[CNV, DME, DRUSEN, NORMAL]`, and mean confidence
of 0.80–0.90 on held-out Kermany images confirms the weights load correctly.

On OLIVES the predictions track the expert labels sensibly. Image 4245: experts
marked DRT/ME and IRF positive with CST 667 µm; RETFound independently predicts
DME at 0.898.

Outputs `class_cnv`, `class_dme`, `class_drusen`, `class_normal`, each with a
softmax confidence.

---

## Not yet available

**Official RETFound weights are gated.** `YukunZhou/RETFound_mae_natureOCT` —
the encoder from the Nature paper — returns 401 without an authenticated
HuggingFace account that has accepted the model terms. Needed for fine-tuning
heads on the 16 OLIVES biomarkers. To enable: create a HF account, request
access on the model page, then `huggingface-cli login`.

**Layer-segmentation software** (Iowa Reference Algorithms / OCTExplorer, AURA)
expects volumetric input — `.vol`, `.oct`, DICOM. It cannot run on OLIVES,
Kermany or OCTDL, which are exported 2D B-scans. It **can** run on HCMS `.vol`
volumes, which also ship expert delineations to validate against.

**The 16 OLIVES biomarkers are not yet predicted by any model.** The 4-class
RETFound output is a different label set. Predicting IRF, SRF, DRIL and the
rest requires fine-tuning on the 9,408 expert-labelled images — the natural
next step, and the reason the gated encoder matters.

---

## Running

```bash
python3 scripts/extract/thickness_classical.py --n 20            # report only
python3 scripts/extract/thickness_classical.py --n 20 --write    # store

python3 scripts/extract/retfound_oct.py --calibrate              # class order
python3 scripts/extract/retfound_oct.py --n 12 --write           # predict + store
```

Both are idempotent — re-running updates values in place rather than
duplicating them.

Environment: torch 2.14.0, torchvision 0.29.0, timm 1.0.30, MPS enabled on
Apple M5. Model cache at `~/oct-data/models/`.

---

## Still to do

1. Fine-tune heads on the 9,408 expert labels to predict the actual 16 OLIVES
   biomarkers — needs the gated RETFound encoder, or the OLIVES authors'
   baseline at `olivesgatech/SupCon_OCT_Clinical`.
2. Run HCMS `.vol` volumes through Iowa or AURA for layer thicknesses.
3. Scale up: run chosen models across all 78,283 images and write results.
4. Push `biomarker_sources` / `biomarker_values` to D1 and surface source
   attribution in the detail panel.
