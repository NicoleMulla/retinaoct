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

---

# Results — scaling sweep, 2026-10-01

Four configurations, same manifest and same patient-grouped folds as the v1
baseline, 15 epochs each (v1's curves showed epochs 17–30 contributed nothing).
A100-SXM4 40 GB, $0.68/hr.

Compared on **best-epoch** validation mAUROC, not final-epoch. v1 ran 30 epochs
and these ran 15, so comparing final epochs would have been confounded — the
first version of this table did exactly that and mildly flattered the new runs.

| Config | Params | Pretraining | Slices | peak ep | best mAUROC | vs v1 |
|---|---:|---|---:|---:|---:|---:|
| **v1 baseline** | 303.3M | RETFound | 1 | 16.4 | **0.8916** | — |
| vitL_in | 303.3M | ImageNet | 1 | 8.8 | 0.8806 | −0.0110 |
| vitH_in | 630.8M | ImageNet | 1 | 8.0 | 0.8775 | −0.0141 |
| vitB_in | 85.8M | ImageNet | 1 | 6.6 | 0.8716 | −0.0200 |
| vitL_ret_slices | 303.3M | RETFound | 3 | 8.0 | 0.8508 | −0.0408 |

**Nothing beat the baseline.** Fold 2 remained the hardest split in every
configuration (0.78–0.83), confirming it is a property of that patient grouping
rather than of any model.

## Why the larger model did not do better

### The operator's hypothesis, recorded

> "It didn't perform better because we didn't have enough images to produce a
> good outcome for such a high-scale model."

**This is correct, and it is the primary mechanism.** The evidence supports it
directly: holding pretraining fixed at ImageNet, going from 85.8M to 630.8M
parameters — a 7.4x increase — moved best mAUROC by **+0.0059**
(0.8716 -> 0.8775), with ViT-H actually *below* ViT-L. The entire spread across
3.5 orders of magnitude of capacity is smaller than the ±0.035 fold-to-fold
standard deviation. The curve is flat because every model tested is already far
past the point where capacity binds.

### Sharpening it: the real sample size is 87, not 9,408

The hypothesis is stronger than the image count suggests. The 9,408 labelled
images are **49 B-scans per volume** — adjacent slices through the same eye at
the same visit, which are near-duplicates. The statistically independent units
are patients (**87**) or eyes (**96**), not images.

So ViT-H was fitting 630.8M parameters to roughly 87 independent examples. Even
ViT-B at 85.8M is grossly over-parameterised on that basis. This is why the
curve is flat rather than rising: the binding constraint was reached long before
ViT-B.

### What actually carried the task: pretraining, not scale

The clearest signal in the sweep:

```
ViT-L + RETFound   303.3M   0.8916
ViT-H + ImageNet   630.8M   0.8775     <- 2x the parameters, worse
ViT-L + ImageNet   303.3M   0.8806
```

**RETFound's retinal pretraining is worth about +0.011, and it beats doubling
the parameter count.** A domain-specific prior substitutes for labelled data in
a way that raw capacity does not. That is the actionable finding: the lever is
better pretraining, not a bigger encoder.

### A hypothesis that the data did NOT support

Before running, the expectation was that larger models would overfit sooner —
peaking at an earlier epoch. They did not: peak epochs were 6.6 (ViT-B),
8.8 (ViT-L), 8.0 (ViT-H), which is not monotonic in size. So the mechanism is
not "bigger degrades faster"; it is simply that additional capacity is inert.
Recorded because it was wrong.

### Honest confounds

1. **ViT-H had no retinal pretraining available.** No RETFound variant above
   ViT-L is reachable — the DINOv2/DINOv3 checkpoints are gated. So the ViT-H
   run tested more capacity *minus* domain pretraining, two variables at once.
   A ViT-H with retinal pretraining might do better; this sweep cannot say.
2. **Hyperparameters were not re-tuned per model size.** Same 1e-4 body /
   1e-3 head learning rate, batch 32, 15 epochs for all four. Larger models
   typically want lower learning rates and longer warmup, so ViT-H was mildly
   disadvantaged. The flatness of B -> L -> H under *identical* settings still
   indicates the trend, but a per-size learning-rate sweep would make it
   airtight.
3. **A label ceiling independent of the encoder.** Seven of sixteen biomarkers
   sit below 0.5 average precision in every configuration. Those are limited by
   annotation scarcity — four have 1–5 positive patients — and no encoder can
   recover a label that appears in one patient.

### Why adjacent slices made it worse

The −0.0408 was the largest drop in the sweep, and it was predicted to be the
cheapest win. Most likely cause: the augmentation pipeline applies rotation and
random-crop jointly to all three channels, but neighbouring B-scans are already
slightly misaligned, so geometric augmentation smears genuinely different
anatomy together instead of reinforcing a signal. At 49 slices per volume,
*n±1* may also simply be different structure rather than context.

Worth one retry with augmentation applied per-channel, or with slice spacing
reduced — but it is not the free win it looked like.

## Decision

**Revert to v1 and use it for production labelling.** The baseline stands at
mAUROC 0.8916 best-epoch / 0.8815 final-epoch, and nothing in this sweep
improved on it. Scaling is closed as a direction at this data size.

Total sweep cost: ~$1.80. The result is negative, and it was worth buying — it
retires "try a bigger model" as an open question for about the price of a coffee.

## What would actually move the number

In descending order of expected value, none of which is "more parameters":

1. **More labelled patients.** 87 is the ceiling. A second annotated cohort
   would outperform everything in this document combined.
2. **Continue MAE pretraining on all 162,871 OLIVES images**, then fine-tune.
   The sweep showed pretraining is the effective lever; this is the way to get
   more of it without new labels. (Phase D above, ~$2.50, untested.)
3. **Volume-level aggregation** — pool predictions across the 49 B-scans of a
   volume to cut variance on the scarce biomarkers.
4. **Per-size learning-rate tuning**, if the capacity question is ever reopened.

---

# Results — MAE continuation, 2026-10-03

RETFound's MAE pretraining continued for 50 epochs on the full 153,045-B-scan
OLIVES corpus, then the biomarker head fine-tuned on the adapted encoder, same
folds as every other run.

Resumed from the official `YukunZhou/RETFound_mae_natureOCT` checkpoint, which
carries the complete MAE state — 398 tensors including 103 decoder tensors,
mask_token, optimiser and scaler — so there was no randomly-initialised decoder
to warm up. Hyperparameters came from the checkpoint's own `args`
(mask_ratio 0.85, norm_pix_loss, blr 1.5e-4), not from guesswork.

**The motivating observation:** those args record the pretraining corpus as
`oct/topcon_median_slice/`. RETFound's OCT stage was trained on **Topcon**
scans; OLIVES is **Spectralis**. A named, concrete device domain gap.

## The adaptation worked. It did not help.

```
MAE reconstruction loss   0.3832 -> 0.3422   (-10.7%, converged by epoch ~48)
```

| fold | v1 | MAE-continued | delta |
|---:|---:|---:|---:|
| 0 | 0.9102 | 0.9195 | +0.0093 |
| 1 | 0.9145 | 0.9220 | +0.0075 |
| 2 | 0.8283 | 0.8208 | -0.0075 |
| 3 | 0.8969 | 0.8812 | -0.0157 |
| 4 | 0.9079 | 0.9091 | +0.0012 |
| **mean** | **0.8916** | **0.8905** | **-0.0010** |
| sd | 0.0360 | 0.0422 | worse |

Three folds up, two down, mean unchanged, variance higher. The encoder
demonstrably learned Spectralis pixel statistics — a 10.7% reconstruction
improvement is not noise — and that learning **did not transfer to the task**.
The device gap was real at the pixel level and irrelevant at the biomarker
level.

### A process note worth keeping

Folds 0 and 1 were reported mid-run as +0.017, which read as a clear win. They
happened to be the two folds that improved. Fold 2 had already been identified
as the one that decides these comparisons, and the interim result was reported
anyway. **On five folds with sd ~0.04, two folds is not a result.**

## Both compute-side hypotheses are now closed

| Hypothesis | Test | Result |
|---|---|---|
| More capacity helps | ViT-B / ViT-L / ViT-H, 7.4x range | +0.0059 — inert |
| Better pretraining helps | 50 epochs MAE on 153,045 in-domain scans | -0.0010 — inert |

The operator's original explanation is the one left standing: **87 patients is
the ceiling.** Not the encoder, not the pretraining domain, not the parameter
count.

Total cost of closing both questions: ~$3.10.

## Decision

v1 remains the production model. No relabelling. Further GPU spend on this
dataset is not where the gains are — the next real improvement requires more
annotated patients, which is a data-collection problem, not a compute one.
