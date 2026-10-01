# Scaling the biomarker model

How much accuracy is left on the table, what it costs to find out, and in what
order to spend. Written 2026-10-01, after the first five-fold run.

---

## The result this plan starts from

ViT-L/16 (303.3M), RETFound encoder, 9,408 labelled OLIVES B-scans,
five patient-grouped folds, 30 epochs each.

**mAUROC 0.8815 ± 0.0315** over the 12 biomarkers with enough positive patients
to validate. Cost $1.07, wall-clock ~3 h.

Four biomarkers are genuinely reliable — AP close to AUROC, fold-to-fold sd
under 0.03:

| Biomarker | AUROC | sd | AP |
|---|---:|---:|---:|
| drt_me | 0.975 | 0.014 | 0.948 |
| fluid_irf | 0.958 | 0.010 | 0.956 |
| ir_hrf | 0.879 | 0.023 | 0.943 |
| vitreous_full | 0.882 | 0.025 | 0.868 |

Three read well on AUROC and are near-useless in practice — `shrm` (AP 0.205),
`atrophy_thinning` (0.142), `ir_hemorrhages` (0.278). Four more are suppressed
entirely for having 1–5 positive patients.

---

## The finding that shapes everything below

Training loss falls to **0.008** while validation mAUROC *peaks at epoch 16 and
then declines*:

| fold | val peaks | mAUROC there | loss there | loss @ep30 |
|---:|---:|---:|---:|---:|
| 0 | 17 | 0.9102 | 0.0404 | 0.0080 |
| 1 | **11** | 0.9145 | 0.0833 | 0.0080 |
| 2 | 26 | 0.8283 | 0.0098 | 0.0074 |
| 3 | 19 | 0.8969 | 0.0287 | 0.0070 |
| 4 | **9** | 0.9079 | 0.1033 | 0.0080 |

Folds 1 and 4 reached their best at epochs 11 and 9 with loss still near 0.09 —
the model was already as good as it would get *before* it began fitting the
training set hard. It then spent twenty epochs memorising, for nothing.

**This is a data ceiling, not a capacity ceiling.** 87 patients / 96 eyes cannot
constrain 303M parameters, let alone more. Every prediction below follows from
this, and the plan is ordered to test it cheaply before spending on size.

---

## What "bigger" actually costs

Parameter counts and compute measured from `timm`, normalised against our one
real datapoint: **40 s/epoch for ViT-L/224 on an RTX 4090** (7,546 train +
1,862 val images).

| Encoder | Params | Compute | VRAM needed | 5 folds x 15 ep | Est. cost |
|---|---:|---:|---:|---:|---:|
| ViT-B/16 224 | 85.8M | 0.28x | 8 G | 0.2 h | **$0.10** |
| **ViT-L/16 224 (current)** | 303.3M | 1.00x | 11 G | 0.8 h | **$0.32** |
| ViT-H/14 224 | 630.8M | 2.72x | 40 G | 1.2 h (A100) | **$0.56** |
| ViT-L/16 384 | 303.7M | 2.93x | 20 G | 2.4 h | **$0.93** |
| DINOv2 ViT-g/14 @224 | 1136.5M | ~3.7x | 48 G | 1.6 h (A100) | **$0.77** |
| EVA-02 L/14 448 | 304.1M | 5.20x | 32 G | 2.3 h (A100) | **$1.07** |
| DINOv2 ViT-g/14 @518 native | 1136.5M | **26.1x** | 80 G+ | 11.4 h | **$5.40–11.45** |

Two corrections to earlier back-of-envelope figures:

- **ViT-g at its native 518 px is 26x our baseline, not ~4x.** It needs 80 GB
  and lands at $5–11 depending on card. Running it at 224 instead drops it to
  ~3.7x and under $1, but discards most of what makes it good.
- **The cheapest card is rarely the cheapest run.** RTX A6000 at $0.402/hr is
  Ampere and roughly half a 4090's throughput, so you rent it twice as long:
  ~$1.87 against the A100's $0.56 at $0.468/hr. Pick on $/FLOP, not $/hr.

Current GPU prices on Vast (verified, >=40 GB, reliability >=0.99):

```
A100 PCIE 40G   $0.468/hr   <- best value for the 600M-1.1B range
RTX 4090 48G    $0.442/hr
L40S 45G        $0.536/hr
RTX 6000Ada 48G $0.539/hr
RTX A6000 48G   $0.402/hr   <- avoid: cheap per hour, expensive per run
RTX PRO 6000 96G $1.004/hr  <- only if you go ViT-g at native resolution
```

### Licensing and availability constraint

**There is no retinal foundation model above ViT-L that you can reach.** Every
larger RETFound variant (`RETFound_dinov2_meh`, `retfound_dinov3`,
`RETFound_mae_meh`) returns 403 — gated, awaiting one click at each model page.
`RetFiner-RETFound` is 1.216 GB, i.e. also ViT-L.

So going above 303M today means a **generic** encoder with no retinal
pretraining. That makes any single big-model run a test of two variables at
once: more capacity, *minus* domain pretraining. Interpret accordingly, and
unlock the gated repos first if you want a clean comparison.

---

## Four phases, each gated on the previous

### Phase A — Diagnose before spending ($0.10, ~1 h)

Settle whether capacity is the limit at all. Scaling *down* answers it as
definitively as scaling up, and costs almost nothing.

1. **Tiny CNN, ~1M params** — runs locally on MPS, no rental. Free.
2. **ViT-B/16, 85.8M** — one instance, five folds. $0.10.
3. Compare against the ViT-L baseline we already have.

**Decision gate.** If ViT-B lands within ~0.02 of ViT-L's 0.8815, capacity is
not the binding constraint and Phase C is predicted to return nothing. Skip to
Phase D. If ViT-B is clearly worse (>0.05 below), capacity does matter and
Phase C is justified.

This is the single highest-value hour in the plan: it either saves the Phase C
spend or earns it.

### Phase B — Cheap wins that are not about size ($1.30, ~3 h)

Run regardless of Phase A's outcome. None of these add parameters.

1. **Adjacent-slice context.** Preprocessing currently does `convert("RGB")`,
   which triplicates one grayscale B-scan into three identical channels — two
   are wasted. Feed slices *n-1, n, n+1* instead and the model gets real
   volumetric context for free. The data is already on disk; `scan_index` is
   already in the manifest. **~$0.35.** Best expected value per dollar here.
2. **Stop at 15 epochs.** The curves show epochs 17–30 contributed nothing.
   Halves the cost of every run below. **Saves money, costs nothing.**
3. **Resolution 384 or 448, same ViT-L.** Targets a specific identified
   weakness: `ir_hrf` are hyperreflective foci a few pixels across, and 504x496
   -> 224 discards ~80% of the pixels. This is capacity where it is actually
   missing — spatial, not parametric. **~$0.93.**
4. **Five-fold ensemble.** sd 0.0315 says there is variance worth averaging.
   Needs a retrain: only fold 1's checkpoint survived the first run.
   **~$0.32.**

### Phase C — Actually go bigger ($0.56–1.10, ~3 h)

Only if Phase A's gate opens.

1. **ViT-H/14 224, 630.8M** on an A100 40 GB. Closest reachable model to the
   800M target. **$0.56.**
2. **EVA-02 L/14 448** — 304M params but 5.2x compute; tests capacity and
   resolution together. **$1.07.**
3. Three-point scaling curve: ViT-B (86M) / ViT-L (303M) / ViT-H (631M), same
   folds, same epochs. A flat curve closes the size question permanently.

**Prediction, recorded so it can be checked:** ViT-H lands at or slightly below
0.8815, peaking earlier than epoch 16. If that is wrong, this document is wrong
about the data ceiling and Phase D should be reweighted.

### Phase D — Attack the actual ceiling ($3–4, ~8 h)

What the evidence says to spend on. All of it uses data you already hold.

1. **Continue MAE pretraining on all 162,871 OLIVES images**, then fine-tune on
   the 9,408. Domain-adaptive pretraining is the principled use of the
   unlabelled corpus and the only item here that plausibly moves 0.88 -> 0.92.
   **~$2.50**, several hours of self-supervised training.
2. **Semi-supervised pseudo-labelling** of the 68,875 unlabelled images, with
   confidence thresholds and human spot-checks. Riskier — it amplifies the
   model's own errors, and with 87 patients there is no independent signal to
   correct them. Do it after (1), never instead of.
3. **Volume-level aggregation.** Labels are per-image but come at 49 B-scans per
   volume. Pooling predictions across a volume should cut variance on the scarce
   biomarkers where single-slice calls are noisiest. Nearly free.

### Not now — Phase E

**DINOv2 ViT-g at native 518 px: $5.40–11.45 and 11+ hours**, needing an 80–96 GB
card. It exceeds the remaining $8.93 at the high end and is the weakest bet in
the document: maximum capacity, zero retinal pretraining, against 87 patients.
Revisit only if Phase C's scaling curve rises steeply, which is not expected.

---

## Budget and schedule

| Phase | Spend | GPU time | Wall-clock |
|---|---:|---:|---|
| A — diagnostics | $0.10 | 0.3 h | ~1 h |
| B — cheap wins | $1.30 | 3 h | ~4 h |
| C — bigger (if gated open) | $0.60 | 1.5 h | ~2.5 h |
| D — data ceiling | $3.00 | 6 h | ~8 h |
| **Total** | **~$5.00** | **~11 h** | **~15 h** |

Remaining credit $8.93, so the whole programme fits with ~$4 spare. GPU time is
roughly 70% of wall-clock; the rest is provisioning (~15 min/instance), data
pull (~2 min from B2), and artefact export.

Realistically this is **two working sessions**: Phases A+B in one (~5 h), C+D in
another (~10 h). Phase D's MAE run is long enough to leave unattended with a
completion watcher.

---

## Process fixes for the next run

Learned the hard way the first time.

1. **Preserve every fold checkpoint.** Only fold 1 survived; folds 0, 2, 3, 4
   died with the instance, so the ensemble in Phase B needs a retrain that
   should have been unnecessary.
2. **Pick hosts on reliability, not price.** The first instance scored 0.958,
   reached `running`, then lost SSH permanently — $0.40 wasted. Filters are now
   `reliability2 >= 0.99`.
3. **Use `runtime` Docker images, not `devel`.** ~3 GB against ~9 GB; the devel
   image cost 22 minutes of billed boot time.
4. **Never pipe remote job output through `tail`.** It buffers until EOF, which
   made a running bootstrap look dead. Log on the remote side and poll the file.
5. **Keep secrets out of argv.** The Vast key appeared in `ps` output. Scripts
   now pass it via a 0600 curl config file.
6. **Destroy, never stop.** A stopped instance still bills storage — $0.0222/hr
   on an 80 GB disk, $16/month, indefinitely.

---

## Expected outcome, stated plainly

Phases A–C most likely leave accuracy where it is, and their value is in
*closing* the size question for about $2 rather than leaving it open.

Phase B's adjacent-slice change and Phase D's MAE pretraining are the two items
with real upside — perhaps **0.88 -> 0.91** combined, concentrated in the
scarce biomarkers whose AP is currently poor.

Nothing here reaches 0.95. The intervention that would is **more labelled
patients**; 87 is the ceiling, and a second labelled cohort would outperform
every compute option in this document combined.
