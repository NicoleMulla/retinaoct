# Supporting data

Every number quoted in [`../experiments.md`](../experiments.md) comes from a file
here. All of it is small enough to version; the bulk artefacts it derives from
(1.72M prediction rows, 1.2 GB model weights, 10.6 GB of WebP derivatives) live
on HuggingFace and Backblaze B2 and are referenced by URL.

## Layout

| Path | Contents |
|---|---|
| `v1/` | production model: per-epoch curves, per-biomarker metrics, 5-fold means |
| `mae_olives/` | MAE-continued encoder, same shape, plus `mae_history.json` (50 pretraining epochs) |
| `vitB_in/` `vitL_in/` `vitH_in/` | capacity sweep, ImageNet pretraining held constant |
| `vitL_ret_slices/` | adjacent-slice input experiment |
| `evaluation/` | ROC and precision-recall curves for v1 on its held-out fold |
| `deployment/` | out-of-distribution gate counts for both inference batches |
| `comparison.csv` `comparison.png` | all six configurations together |
| `manifest_meta.json` | biomarker order, usable flags, positive counts per biomarker |

## File formats

`curves.csv` — `fold,epoch,total_epochs,train_loss,val_mauroc,seconds`
`final_metrics.csv` — `fold,biomarker,auroc,ap,f1,threshold,usable`
`cross_fold.csv` — `biomarker,auroc_mean,auroc_sd,ap_mean,n_folds`
`evaluation/v1_curve_stats.json` — per-biomarker AUROC, AP, positive count, prevalence, threshold
`deployment/*.json` — image counts and gate verdicts

## External artefacts

| What | Where |
|---|---|
| v1 weights, OOD reference, serving config, ROC/PR figures | `huggingface.co/NicoleMulla/retfound-olives-16bm` (private) |
| All six configurations' metrics | `huggingface.co/NicoleMulla/retfound-olives-16bm-scaling` (private) |
| 1.72M biomarker predictions | Cloudflare D1 `retinaoct-olives`, tables `biomarkers` and `biomarker_conf` |
| 153,045 source B-scans + WebP derivatives | B2 `retinaoct/datasets/olives/` and `retinaoct/web/olives/` |
| Searchable interface | https://retinaoct.com |

**Not recoverable:** the MAE-continued encoder weights. The instance was destroyed
after its metrics were copied off, so `mae_olives/` holds the measurements but not
the model. Reproducing it costs roughly $1.30 and about an hour.
