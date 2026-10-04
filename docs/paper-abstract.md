# Draft abstract

For a paper built on [`experiments.md`](experiments.md). Written 2026-10-04.

---

## Abstract

**Purpose.** Foundation models are increasingly applied to retinal OCT, and the
prevailing assumption is that larger encoders and more domain-specific
pretraining yield better downstream performance. We tested both assumptions on a
multi-label biomarker prediction task where the labelled cohort is small, a
regime typical of clinical-trial imaging datasets.

**Methods.** We fine-tuned RETFound (ViT-L/16, 303M parameters) with sixteen
independent sigmoid heads to predict sixteen retinal biomarkers from OCT B-scans
of the OLIVES dataset (9,408 expert-annotated images from 87 patients, 96 eyes,
two diabetic macular oedema trials, single-device Heidelberg Spectralis).
Evaluation used five-fold patient-grouped cross-validation with zero patient
overlap. Against this baseline we tested, as paired per-fold comparisons: encoder
capacity from 85.8M to 630.8M parameters with pretraining held constant; retinal
versus generic pretraining with capacity held constant; continued in-domain
masked-autoencoder pretraining on 153,045 unlabelled B-scans from the same
cohort; and adjacent-slice volumetric input. We report average precision
alongside AUROC throughout, and excluded four biomarkers whose positives
originated from one to five patients.

**Results.** The baseline reached mAUROC 0.8916 ± 0.0360 across twelve evaluable
biomarkers. Capacity improved performance from 85.8M to 303.3M parameters
(+0.0090, 5/5 folds, p = 0.012) and then saturated, with 630.8M offering no
further gain (−0.0031, p = 0.369). Retinal pretraining outperformed ImageNet
pretraining at matched capacity (+0.0110, 5/5 folds), an effect exceeding that of
3.5× more parameters. Continued in-domain MAE pretraining reduced reconstruction
loss by 10.7% yet produced no detectable downstream change (−0.0010, p = 0.836),
despite closing a documented device domain gap between the pretraining corpus
(Topcon) and the target data (Spectralis). Adjacent-slice input degraded
performance substantially (−0.0408, 0/5 folds, p = 0.001). AUROC and average
precision diverged severely on rare biomarkers: SHRM reached AUROC 0.974 at 0.7%
prevalence with average precision of 0.151.

**Conclusions.** In this setting, encoder capacity saturates near 300M parameters
and additional in-domain pretraining yields no measurable benefit, while
pretraining *domain* remains influential. Because 9,408 images derive from only 87
patients, the effective sample size is two orders of magnitude smaller than the
image count implies, and annotation breadth rather than model scale or
pretraining volume is the binding constraint. We further show that AUROC alone is
unsafe for reporting rare-biomarker performance, with AUROC-to-AP gaps reaching
0.823. The model was deployed to annotate 143,607 previously unlabelled scans with
per-image out-of-distribution gating and strict provenance separation from expert
annotation; all code, per-fold metrics and curves are released.

---

## Notes for drafting

**Honest framing.** This is primarily a negative-results and methodology paper.
The contribution is the controlled isolation of capacity from pretraining under
small-n, the demonstration that a *provably successful* representation adaptation
need not transfer, and the AUROC/AP warning — not a new architecture or a
state-of-the-art number.

**Claims that must not be overstated.** Single dataset, single device, 87
patients, no external validation. Five folds give weak power; direction unanimity
(5/5, 0/5) is the stronger evidence and should be reported as such alongside
p-values. Hyperparameters were not re-tuned per configuration. No retinal
foundation model above ViT-L was obtainable, so "ViT-H with retinal pretraining"
is untested and should be named as an open question.

**Likely reviewer objections, and where they are answered.**

| Objection | Answer |
|---|---|
| "Only 5 folds — underpowered" | Conceded in §8; unanimity reported alongside p |
| "LR not tuned per model size" | Conceded in §8; comparison is internally consistent |
| "MAE needed more than 50 epochs" | Loss converged by ~48 (`mae_history.json`) |
| "Why not a bigger retinal model?" | None reachable; gated or nonexistent above ViT-L |
| "Single device limits generality" | Stated; the deployed gate refuses other devices |
| "Image count looks large" | Effective n is 87 patients — the paper's central point |

**Venue fit.** Suited to a venue that publishes negative and methodological
results — a medical-imaging methods journal, or a MICCAI/ISBI-adjacent workshop
on validation and evaluation. Framing it as a performance paper would invite
rejection, since no configuration beats the baseline.

**Required additions before submission.** Confidence intervals on per-biomarker
AUROC/AP; a per-biomarker reliability statement derived from AP rather than AUROC;
and an explicit statement that four biomarkers were excluded, with the reason,
rather than silently reporting twelve.

**Licensing.** RETFound weights are CC-BY-NC-4.0 and that term propagates to the
fine-tuned model. Any release must state non-commercial use. OLIVES terms should
be re-checked before redistributing derived labels.
