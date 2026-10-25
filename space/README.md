---
title: Retina OCT Biomarkers
emoji: 👁️
colorFrom: indigo
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
license: cc-by-nc-4.0
short_description: OLIVES retinal biomarkers from an OCT B-scan
---

# Retina OCT — OLIVES biomarkers

Serves the model behind [retinaoct.com](https://retinaoct.com): a RETFound
ViT-L/16 encoder fine-tuned on 9,408 expert-annotated OLIVES B-scans to predict
sixteen retinal biomarkers.

**Research use only. Not a medical device and not for diagnostic use.**

## Two surfaces

| Route | Purpose |
|---|---|
| `GET /` | Gradio UI — drop in a B-scan and see the raw verdict |
| `POST /api/analyse` | JSON API, used by retinaoct.com |
| `GET /api/health` | liveness check |

`POST /api/analyse` accepts either `{"inputs": "<base64>"}` or raw image bytes,
and returns the handler's verdict dictionary. The JSON shape deliberately
matches HuggingFace Inference Endpoints, so the website's proxy can point at
either without a code change.

## The gate

Public uploads are mostly not OLIVES-style Spectralis B-scans, so the model is
never reached unless the image passes a distance check in the encoder's
embedding space:

| Verdict | Meaning |
|---|---|
| `ok` | in distribution — full predictions |
| `out_of_domain` | OCT-like but off-distribution — predictions returned, explicitly unvalidated |
| `rejected` | far outside — no predictions at all |

A `rejected` result means the model declined to judge. It does **not** mean the
retina is normal.

Four of the sixteen biomarkers (`dril`, `rpe_disruption`, `ped_serous`, `vmt`)
had 1–5 positive patients in the 87-patient training set — too few to learn or
validate — so the model emits nothing for them rather than a fabricated
probability.

## Configuration

Weights are pulled at startup from the private model repo rather than vendored
here, so `handler.py`, the thresholds and the gate cannot drift from what was
validated.

| Secret | Purpose |
|---|---|
| `HF_TOKEN` | read access to the private model repo |
| `MODEL_REPO` | optional override (default `NicoleMulla/retfound-olives-16bm`) |

## Licence

Model weights derive from RETFound and inherit **CC BY-NC 4.0** — non-commercial
use only. Training images are from the OLIVES dataset (Prabhushankar et al.,
NeurIPS 2022), CC BY 4.0.
