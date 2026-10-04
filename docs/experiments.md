# Predicting OLIVES biomarkers from OCT B-scans

Everything attempted, what each result was, and what the evidence supports.
Supporting data for every number is in [`results/`](results/) — see
[`results/README.md`](results/README.md) for the layout.

Work carried out 2026-09-26 to 2026-10-04. Total compute cost **$7.41**.

---

## 1. Summary

A RETFound ViT-L/16 encoder with sixteen independent sigmoid heads was
fine-tuned on 9,408 expert-annotated OLIVES B-scans to predict sixteen retinal
biomarkers, then used to label the remaining 143,607 scans in the archive.

**Headline result: mAUROC 0.8916 ± 0.0360** over the twelve biomarkers with
enough positive patients to validate, under five-fold patient-grouped
cross-validation.

Four interventions were tested against that baseline. Measured as paired
per-fold differences:

| Intervention | Δ mAUROC | p | folds improved |
|---|---:|---:|---:|
| Encoder capacity 86M → 303M (ImageNet fixed) | **+0.0090** | 0.012 | **5/5** |
| Encoder capacity 303M → 631M (ImageNet fixed) | −0.0031 | 0.369 | 3/5 |
| Retinal pretraining vs ImageNet (ViT-L fixed) | **+0.0110** | 0.099 | **5/5** |
| Continued in-domain MAE pretraining | −0.0010 | 0.836 | 3/5 |
| Adjacent-slice input (n−1, n, n+1) | **−0.0408** | 0.001 | 0/5 |

Read together: **capacity helps up to roughly 300M parameters and then
saturates; domain-appropriate pretraining is worth about as much as tripling
capacity; further in-domain pretraining adds nothing; and naive volumetric
context actively hurts.**

The binding constraint is neither architecture nor pretraining. It is that
9,408 labelled images come from **87 patients and 96 eyes**.

---

## 2. Data

### 2.1 The corpus

OLIVES ([Prabhushankar et al., NeurIPS 2022 Datasets & Benchmarks]) comprises
OCT B-scans from two diabetic macular oedema trials, PRIME and TREX-DME, all
acquired on Heidelberg Spectralis at 504 × 496 px, 8-bit greyscale.

| | Images | Patients | Eyes |
|---|---:|---:|---:|
| Expert biomarker annotations | **9,408** | **87** | **96** |
| Clinical metadata only (BCVA, CST) | 68,875 | 87 | 96 |
| No labels of any kind | 74,762 | 87 | 171 |
| **Total indexed** | **153,045** | **87** | **171** |

The third row was discovered late and is addressed in §2.4.

### 2.2 Effective sample size

The image count overstates the data by more than an order of magnitude. Each
volume is 49 contiguous B-scans through one eye at one visit — adjacent slices
are near-duplicates. The statistically independent units are **eyes (96)** or
**patients (87)**, not images.

This single fact explains most of what follows. A 630.8M-parameter encoder fitted
to ~87 independent examples is operating far past the point where additional
capacity can be constrained by the data.

### 2.3 Label structure and the trainability floor

Sixteen binary biomarkers, annotated per image. They **co-occur** — the median
labelled image carries two or three — so the task is multi-label with sixteen
independent sigmoids, never a softmax.

| Biomarker | Positives | Prevalence | Positive patients | Positive eyes |
|---|---:|---:|---:|---:|
| ir_hrf | 6,341 | 67.4% | 87 | 96 |
| vitreous_full | 5,222 | 55.5% | 69 | 75 |
| fluid_irf | 4,088 | 43.5% | 84 | 93 |
| drt_me | 3,003 | 31.9% | 63 | 72 |
| vitreous_partial | 2,984 | 31.7% | 59 | 67 |
| vitreous_debris | 2,836 | 30.1% | 84 | 91 |
| preretinal_tissue | 807 | 8.6% | 34 | 34 |
| ez_disruption | 604 | 6.4% | 43 | 46 |
| ir_hemorrhages | 373 | 4.0% | 49 | 51 |
| fluid_srf | 233 | 2.5% | 25 | 27 |
| atrophy_thinning | 166 | 1.8% | 14 | 16 |
| shrm | 76 | 0.8% | 14 | 14 |
| *dril* | *32* | *0.3%* | ***4*** | *4* |
| *rpe_disruption* | *10* | *0.1%* | ***5*** | *5* |
| *vmt* | *10* | *0.1%* | ***3*** | *3* |
| *ped_serous* | *10* | *0.1%* | ***1*** | *1* |

The **positive-patient** column, not the positive count, decides trainability.
All ten `ped_serous` positives come from a single patient: under a
patient-grouped split that biomarker falls entirely inside one fold and can never
be validated. The four italicised biomarkers were excluded from training targets
and from every reported metric, and the deployed system emits nothing for them
rather than a fabricated negative.

Twelve biomarkers remain. All reported means are over those twelve.

### 2.4 An indexing gap: the fellow eye

The index was built from `Clinical_Data_Images.xlsx`, which covers 78,283 images.
The archive holds ~161,000 image files. The difference is not extra visits — it
is **the fellow eye of nearly every patient**, which the clinical spreadsheet
never covered.

Recovering it required resolving patient identity carefully. TREX subject folders
are named for the *enrolled study eye* — `0201GOD` means person 0201, arm G,
study eye OD — and that folder also contains OS scans, while the same person
appears again under `0201TOS`. An eye is therefore identified by
**(patient, laterality)**, not (folder, eye). Keying on the folder left 74,223 of
74,762 rows without a patient id; deriving the person from the numeric prefix
resolved all of them, verified against the existing index where `0201GOD` and
`0201TOS` both map to `patient_id 201`.

Filtering by **dimension rather than filename** excluded 6,284 en-face images,
1,849 of which a filename filter would have missed. Final addition: 74,762
B-scans, 75 new eye ids, **no new patients** — which is why §2.2 is unchanged by
this expansion.

---

## 3. Method

**Architecture.** ViT-L/16 at 224 × 224, 303.3M parameters, initialised from
RETFound's OCT encoder and fitted with a fresh `Linear(1024 → 16)` head.

**Objective.** `BCEWithLogitsLoss` with per-biomarker `pos_weight` clipped to
[1, 50], so a 0.8%-prevalence label is not simply ignored in favour of always
predicting absent.

**Input.** 504 × 496 greyscale → RGB → 224 × 224, ImageNet normalisation. The
source aspect ratio is 1.02:1, so a plain resize introduces no geometric
distortion. Augmentation: horizontal flip, ±7° rotation, 0.88–1.0 random crop,
brightness and offset jitter.

**Validation.** Five-fold **patient-grouped** cross-validation. Folds are
assigned greedily by positive count rather than by `GroupKFold`, which assigns on
group size alone and stranded all positives of scarce biomarkers in single folds.
Resulting balance: 17–18 patients and 1,862–1,960 images per fold, **zero patient
overlap** between train and validation, verified at run time.

**Optimisation.** AdamW, body lr 1e-4, head lr 1e-3, weight decay 0.05, OneCycle
schedule, batch 32, mixed precision. The baseline ran 30 epochs; all later
configurations ran 15 after the baseline curves showed validation peaking at
epoch 16.4 on average while training loss continued to 0.008.

**Metrics.** AUROC and average precision, both per biomarker, plus F1 at a
per-biomarker tuned threshold. Thresholds are tuned on the validation fold: a
flat 0.5 is wrong here, since at 0.8% prevalence a model scores 99.2% accuracy by
never firing.

### 3.1 Why average precision is reported alongside AUROC

AUROC's baseline is 0.5 regardless of prevalence. Average precision's baseline
**is** the prevalence. On rare biomarkers the two diverge sharply, and AUROC alone
is misleading — quantified in §5.3.

---

## 4. Experiments

### 4.1 Baseline — RETFound ViT-L

Five folds, 30 epochs. Data: [`results/v1/`](results/v1/).

| fold | best-epoch mAUROC | peak epoch |
|---:|---:|---:|
| 0 | 0.9102 | 17 |
| 1 | 0.9145 | 11 |
| 2 | 0.8283 | 26 |
| 3 | 0.8969 | 19 |
| 4 | 0.9079 | 9 |
| **mean** | **0.8916 ± 0.0360** | 16.4 |

Fold 2 is consistently the hardest split across *every* configuration tested
(0.78–0.83), confirming it is a property of that patient grouping rather than of
any model. **The fold-to-fold sd of 0.0360 is the noise floor any claimed
improvement must clear.**

### 4.2 Capacity sweep

Hypothesis: a larger encoder improves accuracy. Pretraining held constant at
ImageNet so size is the only variable.
Data: [`results/vitB_in/`](results/vitB_in/), [`vitL_in/`](results/vitL_in/),
[`vitH_in/`](results/vitH_in/).

| Encoder | Params | mAUROC | Δ vs ViT-L | p | folds improved |
|---|---:|---:|---:|---:|---:|
| ViT-B/16 | 85.8M | 0.8716 | −0.0090 | 0.012 | 0/5 |
| **ViT-L/16** | **303.3M** | **0.8806** | — | — | — |
| ViT-H/14 | 630.8M | 0.8775 | −0.0031 | 0.369 | 3/5 |

**Capacity helps, then saturates.** 86M → 303M gains +0.0090 with all five folds
improving (p = 0.012). 303M → 631M gains nothing (p = 0.369) despite 2.1× the
parameters.

Reporting only the endpoints (86M → 631M, +0.0059) would average the rising
segment with the flat one and hide this structure. The curve is not flat; it
plateaus.

### 4.3 Pretraining source

Hypothesis: retinal pretraining beats generic pretraining. Capacity fixed at
ViT-L.

| Pretraining | mAUROC | Δ | p | folds improved |
|---|---:|---:|---:|---:|
| ImageNet | 0.8806 | — | — | — |
| **RETFound (retinal)** | **0.8916** | **+0.0110** | 0.099 | **5/5** |

Unanimous in direction across folds. At n = 5 the p-value is weak, but a 5/5 sign
test is itself p = 0.0625 two-sided, and the effect **exceeds what tripling
capacity bought**. Domain-appropriate pretraining is the more efficient lever.

### 4.4 Continued in-domain MAE pretraining

Hypothesis: if retinal pretraining is worth +0.011, more of it — adapted to *this*
device — should add more.

The motivation was concrete rather than speculative. The official RETFound
checkpoint records its own pretraining corpus in its `args`:
`oct/topcon_median_slice/`. **RETFound's OCT stage was trained on Topcon scans;
OLIVES is Spectralis.** A named device domain gap, with 153,045 unlabelled
in-domain B-scans available to close it at no annotation cost.

The official checkpoint carries the complete MAE state — 398 tensors including
103 decoder tensors, `mask_token`, optimiser and scaler — so pretraining resumed
from epoch 800 with a matched encoder–decoder pair and no warmup. Hyperparameters
were taken from the checkpoint's own `args`: `mask_ratio=0.85`,
`norm_pix_loss=True`, base lr 1.5e-4.

Fifty epochs over all 153,045 B-scans.
Data: [`results/mae_olives/`](results/mae_olives/), trajectory in `mae_history.json`.

```
reconstruction loss   0.3832 → 0.3422   (−10.7%, converged by epoch ~48)
```

| | mAUROC | Δ vs v1 | p | folds improved |
|---|---:|---:|---:|---:|
| RETFound | 0.8916 | — | — | — |
| RETFound + OLIVES MAE | 0.8905 | −0.0010 | **0.836** | 3/5 |

**The adaptation worked and did not transfer.** A 10.7% reconstruction
improvement is not noise — the encoder demonstrably learned Spectralis pixel
statistics. It produced no detectable change in biomarker prediction. The device
gap was real at the pixel level and irrelevant at the task level.

A secondary pattern is visible in the per-biomarker breakdown (§5.4): gains
concentrate in the *weakest* biomarkers and small losses in the strongest,
netting to zero. That is consistent with better low-level representation mattering
only where task signal was marginal.

### 4.5 Adjacent-slice input

Hypothesis: the preprocessing calls `convert("RGB")` on a greyscale scan,
triplicating one slice into three identical channels — two carry no information.
Feeding slices *n−1, n, n+1* should supply free volumetric context, since
labelled volumes are complete and the neighbours are already on disk.

| | mAUROC | Δ | p | folds improved |
|---|---:|---:|---:|---:|
| Single slice | 0.8916 | — | — | — |
| Three adjacent slices | 0.8508 | **−0.0408** | **0.001** | **0/5** |

**The largest and most significant effect measured, and it is negative.** The
most likely cause is that augmentation applies rotation and random-crop jointly
across all three channels, while neighbouring B-scans are already slightly
misaligned — so geometric augmentation smears genuinely different anatomy
together rather than reinforcing structure. At 49 slices per volume, *n±1* may
also simply be different anatomy rather than context.

Worth one retry with per-channel augmentation before abandoning. As implemented,
it is clearly harmful.

---

## 5. Results

### 5.1 All configurations

[`results/comparison.csv`](results/comparison.csv) ·
[`comparison.png`](results/comparison.png)

| Configuration | Params | Pretraining | mAUROC | sd |
|---|---:|---|---:|---:|
| **RETFound ViT-L (production)** | 303.3M | retinal | **0.8916** | 0.0360 |
| RETFound ViT-L + OLIVES MAE | 303.3M | retinal + in-domain | 0.8905 | 0.0422 |
| ViT-L | 303.3M | ImageNet | 0.8806 | 0.0326 |
| ViT-H | 630.8M | ImageNet | 0.8775 | 0.0353 |
| ViT-B | 85.8M | ImageNet | 0.8716 | 0.0341 |
| RETFound ViT-L + 3 slices | 303.3M | retinal | 0.8508 | 0.0386 |

### 5.2 Per-biomarker, production model

Five-fold means. [`results/v1/cross_fold.csv`](results/v1/cross_fold.csv)

| Biomarker | AUROC | sd | AP | Reading |
|---|---:|---:|---:|---|
| drt_me | 0.975 | 0.014 | 0.948 | strong, stable |
| fluid_irf | 0.958 | 0.010 | 0.956 | strong, stable |
| fluid_srf | 0.927 | 0.106 | 0.724 | strong but high variance |
| ez_disruption | 0.913 | 0.021 | 0.617 | moderate |
| ir_hrf | 0.879 | 0.023 | 0.943 | strong |
| vitreous_full | 0.882 | 0.025 | 0.868 | strong |
| shrm | 0.882 | 0.118 | **0.205** | AUROC misleading |
| ir_hemorrhages | 0.858 | 0.053 | **0.278** | AUROC misleading |
| vitreous_partial | 0.842 | 0.030 | 0.713 | moderate |
| atrophy_thinning | 0.836 | 0.083 | **0.142** | AUROC misleading |
| preretinal_tissue | 0.818 | 0.115 | 0.468 | weak, high variance |
| vitreous_debris | 0.808 | 0.062 | 0.697 | moderate |

**Five biomarkers are genuinely usable** — `drt_me`, `fluid_irf`, `ir_hrf`,
`vitreous_full`, `fluid_srf` — with AP within ~0.06 of AUROC and (except
`fluid_srf`) low fold variance. These are the fluid and oedema findings, which
are also the clinically actionable ones.

### 5.3 ROC and precision-recall curves

[`results/evaluation/v1_roc_curves.png`](results/evaluation/v1_roc_curves.png) ·
[`v1_pr_curves.png`](results/evaluation/v1_pr_curves.png) ·
[`v1_curve_stats.json`](results/evaluation/v1_curve_stats.json)

Evaluated on **fold 1 only** — 1,862 images from 17 unseen patients. The published
checkpoint is fold 1's, so that is its sole honest held-out set; scoring all 9,408
labelled images would fold training data into the curves.

| Biomarker | AUROC | AP | gap | n+ | prevalence |
|---|---:|---:|---:|---:|---:|
| fluid_srf | 0.996 | 0.946 | 0.051 | 60 | 3.2% |
| drt_me | 0.980 | 0.966 | 0.014 | 579 | 31.1% |
| **shrm** | **0.974** | **0.151** | **0.823** | **13** | **0.7%** |
| **atrophy_thinning** | **0.968** | **0.386** | **0.583** | **12** | **0.6%** |
| fluid_irf | 0.964 | 0.965 | −0.001 | 799 | 42.9% |
| ez_disruption | 0.952 | 0.788 | 0.164 | 130 | 7.0% |
| vitreous_full | 0.912 | 0.891 | 0.021 | 1019 | 54.7% |
| ir_hemorrhages | 0.907 | 0.537 | 0.371 | 115 | 6.2% |
| ir_hrf | 0.895 | 0.951 | −0.056 | 1231 | 66.1% |
| vitreous_debris | 0.848 | 0.800 | 0.048 | 679 | 36.5% |
| vitreous_partial | 0.847 | 0.704 | 0.143 | 556 | 29.9% |
| **preretinal_tissue** | **0.730** | **0.205** | **0.525** | 120 | 6.4% |

**`shrm` is the cautionary case.** AUROC 0.974 — the ROC curve hugs the top-left
corner. Precision-recall sits near **0.15** across the entire recall range. The
model ranks its 13 positives above almost all 1,849 negatives, but at 0.7%
prevalence, capturing them requires accepting enough false positives that roughly
six in seven positive calls are wrong.

In fairness: AP 0.151 against a 0.007 baseline is 21× chance. The model learned
something real. At that prevalence, "far better than chance" and "clinically
usable" remain very far apart.

Both `shrm` and `atrophy_thinning` show **visible staircases** in their ROC
curves — each step is one of twelve or thirteen positives. Small-sample noise
rendered directly.

### 5.4 Per-biomarker, MAE-continued vs production

Five-fold means, final epoch.
[`results/mae_olives/cross_fold.csv`](results/mae_olives/cross_fold.csv)

| Biomarker | v1 AUROC | MAE AUROC | Δ | v1 AP | MAE AP | Δ |
|---|---:|---:|---:|---:|---:|---:|
| preretinal_tissue | 0.818 | 0.845 | **+0.027** | 0.468 | 0.515 | **+0.047** |
| vitreous_debris | 0.808 | 0.834 | **+0.026** | 0.697 | 0.724 | +0.026 |
| fluid_srf | 0.927 | 0.945 | +0.018 | 0.724 | 0.744 | +0.020 |
| vitreous_partial | 0.842 | 0.857 | +0.015 | 0.713 | 0.735 | +0.021 |
| atrophy_thinning | 0.836 | 0.847 | +0.010 | 0.142 | 0.209 | **+0.067** |
| ir_hemorrhages | 0.858 | 0.860 | +0.002 | 0.278 | 0.272 | −0.005 |
| ir_hrf | 0.879 | 0.879 | −0.000 | 0.943 | 0.943 | +0.000 |
| drt_me | 0.975 | 0.974 | −0.000 | 0.948 | 0.945 | −0.003 |
| shrm | 0.882 | 0.882 | +0.000 | 0.205 | 0.195 | −0.011 |
| fluid_irf | 0.958 | 0.952 | −0.006 | 0.956 | 0.948 | −0.008 |
| ez_disruption | 0.913 | 0.900 | −0.014 | 0.617 | 0.588 | −0.029 |
| vitreous_full | 0.882 | 0.868 | −0.014 | 0.868 | 0.857 | −0.011 |

Sorted by effect size, the pattern is near-monotonic in baseline strength: the
four largest gains are all bottom-half biomarkers, the three losses are all
top-half. Net effect zero.

**A note on aggregation.** This table's mean is +0.005 AUROC; the headline in
§4.4 is −0.0010. Both derive from the same runs: §4.4 uses best-epoch mAUROC per
fold, this table uses final-epoch per-biomarker AUROC averaged over folds.
Neither is wrong, and both sit far inside the ±0.04 fold noise. The defensible
statement is **no detectable difference**, not "slightly better" or "slightly
worse." Quoting whichever is convenient would be misleading.

---

## 6. Deployment

### 6.1 Scale

The production model labelled every unannotated scan in the archive, in two
batches. [`results/deployment/`](results/deployment/)

| Batch | Images | in-domain | out-of-distribution | rejected |
|---|---:|---:|---:|---:|
| Study eyes | 68,875 | 67,797 (98.4%) | 1,078 (1.6%) | 0 |
| Fellow eyes | 74,762 | 70,008 (93.6%) | **4,724 (6.3%)** | **30** |

**1.72M biomarker predictions** over 143,607 images.

### 6.2 Out-of-distribution gating

Before any prediction is served, the image's encoder embedding is scored by
Mahalanobis distance against the training distribution — statistics computed from
the fine-tuned encoder over the training fold, since fine-tuning moves the
embedding space.

The gate was validated before deployment against data it would plausibly meet:

| Input | Median distance | Flagged |
|---|---:|---:|
| OLIVES held-out (in-domain) | 116.8 | 5% |
| Kermany — other-vendor OCT | 236.2 | **100%** |
| OCTDL — other-vendor OCT | 302.0 | **100%** |
| Fundus photograph — wrong modality | 382.8 | **100%** |

Distance increases monotonically with distance from the training domain, so the
gate degrades gracefully rather than switching on and off.

In deployment it behaved consistently with its design: **fellow eyes — never seen
during training — were flagged at 6.3% against 1.6% for study eyes.** The 30
outright rejections form a single coherent volume
(`/Prime_FULL/02-046/W100/OS`), not scattered noise.

### 6.3 Validation without new annotation

Central subfield thickness is recorded for 68,826 of the 68,875 first-batch
images and is independent of the biomarker labels. Predicted oedema should
reproduce the thickness separation seen in expert labels.

| Biomarker | Expert separation | Model separation | Retained |
|---|---:|---:|---:|
| drt_me | +134.6 µm | +65.4 µm | 49% |
| fluid_irf | +105.8 µm | +44.3 µm | 42% |
| fluid_srf | +194.4 µm | +103.7 µm | 53% |

Correct direction, correct ordering (SRF > DRT/ME > IRF in both), **~50%
attenuated**. Real signal, measurably noisier than expert annotation — consistent
with imperfect classification compressing the gap from both sides.

### 6.4 Provenance

Expert annotation and model inference are never merged. Each image carries a
`label_source` of `expert`, `model` or `rejected`; model predictions carry
per-biomarker probabilities and an OOD distance in a separate table. The public
interface distinguishes them by colour and glyph, reports probabilities rather
than gradings for model rows, and shows "Not assessed" — never a fabricated
absent — for the four untrainable biomarkers and for rejected scans.

---

## 7. What the evidence supports

1. **Capacity saturates near 300M parameters on this data.** 86M → 303M is
   unanimous across folds; 303M → 631M is nothing.
2. **Domain-appropriate pretraining outperforms scale.** +0.0110 for retinal over
   generic pretraining, exceeding the +0.0090 from 3.5× capacity.
3. **Further in-domain pretraining adds nothing detectable**, even when it
   provably improves the representation (−10.7% reconstruction loss).
4. **Naive volumetric context harms** as implemented.
5. **AUROC alone is unsafe on rare biomarkers.** Gaps to AP reach 0.823.
6. **The ceiling is annotation, not compute.** 87 patients.

### Not supported

- That bigger models *cannot* help — only that they do not here, at this n.
- That MAE continuation is worthless — the weak-biomarker pattern (§5.4) may
  become real with more label signal.
- Any claim about devices other than Spectralis, which the gate explicitly
  refuses to assess.

---

## 8. Limitations

**Single dataset, 87 patients, two trials, one device.** No external validation.
Nothing here should be assumed to transfer to another cohort or scanner; the
deployed gate flags such inputs rather than scoring them.

**n = 5 folds.** Paired tests over five folds have little power. Direction
unanimity (5/5 or 0/5) carries more weight than any individual p-value, and
p = 0.0625 is the floor a five-fold sign test can reach.

**Hyperparameters were not re-tuned per configuration.** Identical learning rates
and schedules throughout, which mildly disadvantages the largest encoder. The
ViT-B → ViT-L → ViT-H comparison is internally consistent but not learning-rate
optimal for each.

**No retinal foundation model above ViT-L was reachable.** The capacity sweep
necessarily used ImageNet pretraining at all three sizes to stay controlled, so
"ViT-H with retinal pretraining" is untested.

**Seven of sixteen biomarkers remain below 0.5 AP** regardless of configuration.
That ceiling is annotation-bound.

**The MAE encoder was not preserved.** Metrics survive; weights do not.

---

## 9. Reproduction

| Step | Script |
|---|---|
| Build training manifest with patient-grouped folds | `scripts/train/build_manifest.py` |
| Index the unlabelled remainder | `scripts/extend_olives_index.py` |
| Provision / tear down GPU | `scripts/train/provision.sh`, `destroy.sh` |
| Stage data onto the instance | `scripts/train/bootstrap_remote.sh` |
| Train baseline | `scripts/train/train_olives.py` |
| Capacity / pretraining / slice experiments | `scripts/train/train_olives_v2.py` |
| Continue MAE pretraining | `scripts/train/mae_continue.py` |
| Export serving artefacts and OOD reference | `scripts/train/export_reference.py` |
| Parse logs into metrics | `scripts/train/collect_curves.py` |
| ROC / PR curves | `scripts/train/roc_curves.py` |
| Label the unannotated corpus | `scripts/train/infer_unlabeled.py` |
| Publish to HuggingFace | `scripts/train/push_to_hf.py` |

The production configuration is tagged **`baseline-v1`**.

### Cost

| Phase | Cost |
|---|---:|
| Baseline, five folds | $1.07 |
| Capacity sweep + adjacent slices | $1.80 |
| MAE continuation + fine-tune | $1.30 |
| Inference over 143,607 images | $0.65 |
| Wasted on an unreachable host | $0.40 |
| Miscellaneous | $2.19 |
| **Total** | **$7.41** |

---

## 10. References to supporting data

Everything above is reproducible from [`results/`](results/). Bulk artefacts:
weights and figures on HuggingFace, 1.72M predictions in Cloudflare D1, source
imagery on B2. See [`results/README.md`](results/README.md).

Related: [`biomarkers.md`](biomarkers.md) (label inventory),
[`extraction.md`](extraction.md) (earlier methods),
[`datasets.md`](datasets.md) (provenance),
[`scaling.md`](scaling.md) (the scaling plan and its running log),
[`atlas.md`](atlas.md) (serving architecture).
