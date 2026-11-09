#!/usr/bin/env python3
"""Confusion matrices and ROC curves for the 16-biomarker model.

    python3 scripts/plot_biomarker_eval.py

Reads the held-out fold-1 predictions in docs/results/evaluation/ and writes
biomarker_confusion_roc.png beside them.

Laid out like the multi-class figures in the AMD literature, but this task is
not multi-class: it is sixteen independent present/absent calls on one B-scan,
so a single 3x3 matrix has no meaning here. The analogue is one 2x2 matrix per
biomarker, at the threshold that biomarker is actually deployed with.

Only twelve are plotted. DRIL and serous PED have zero positives in this fold
and RPE disruption and VMT have five and four, which is too few to estimate
anything from; the served model suppresses exactly those four.
"""
import csv
import json
import pathlib

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec

EVAL = pathlib.Path(__file__).resolve().parent.parent / "docs" / "results" / "evaluation"
OUT = EVAL / "biomarker_confusion_roc.png"

PRETTY = {
    "atrophy_thinning": "Atrophy / thinning", "drt_me": "DRT / ME",
    "ez_disruption": "EZ disruption", "fluid_irf": "IRF", "fluid_srf": "SRF",
    "ir_hemorrhages": "IR haemorrhages", "ir_hrf": "IR HRF",
    "preretinal_tissue": "Preretinal tissue", "shrm": "SHRM",
    "vitreous_debris": "Vitreous debris", "vitreous_full": "Vitreous (full)",
    "vitreous_partial": "Vitreous (partial)",
}


def roc(y, p):
    """TPR/FPR sweep and trapezoidal AUC, so the figure needs no sklearn."""
    order = np.argsort(-p)
    y = y[order]
    tp = np.cumsum(y)
    fp = np.cumsum(1 - y)
    tpr = np.concatenate([[0.0], tp / max(tp[-1], 1), [1.0]])
    fpr = np.concatenate([[0.0], fp / max(fp[-1], 1), [1.0]])
    return fpr, tpr, float(np.trapezoid(tpr, fpr))


def main():
    d = np.load(EVAL / "fold1_predictions.npz", allow_pickle=True)
    probs, labels = d["probs"], d["labels"]
    names = [str(x) for x in d["biomarkers"]]
    conf = {r["biomarker"]: r for r in csv.DictReader(open(EVAL / "v1_confusion_fold1.csv"))}
    meta = json.load(open(EVAL / "v1_curve_stats.json"))

    rows = []
    for b, r in conf.items():
        i = names.index(b)
        y = (labels[:, i] > 0.5).astype(int)
        p = probs[:, i].astype(float)
        thr = float(r["threshold"])
        pred = p >= thr
        fpr, tpr, auc = roc(y, p)
        rows.append(dict(
            key=b, name=PRETTY.get(b, b), thr=thr, fpr=fpr, tpr=tpr, auc=auc,
            n_pos=int(y.sum()),
            cm=np.array([[int((~pred & (y == 0)).sum()), int((pred & (y == 0)).sum())],
                         [int((~pred & (y == 1)).sum()), int((pred & (y == 1)).sum())]]),
        ))
    rows.sort(key=lambda r: -r["auc"])

    fig = plt.figure(figsize=(13.2, 12.8))
    # Top margin has to carry a two-line suptitle, a footnote, the panel
    # heading AND two-line matrix titles, so it is kept well clear.
    gs = GridSpec(2, 1, height_ratios=[1.52, 1], hspace=0.26, figure=fig,
                  left=0.062, right=0.918, top=0.858, bottom=0.052)

    # ---- A: one 2x2 matrix per biomarker ------------------------------------
    top = gs[0].subgridspec(3, 4, hspace=0.72, wspace=0.26)
    im = None
    for k, r in enumerate(rows):
        ax = fig.add_subplot(top[k // 4, k % 4])
        norm = r["cm"] / r["cm"].sum(axis=1, keepdims=True).clip(min=1)
        im = ax.imshow(norm, cmap="Blues", vmin=0, vmax=1)
        for (i, j), v in np.ndenumerate(r["cm"]):
            ax.text(j, i, f"{v:,}", ha="center", va="center", fontsize=9,
                    color="white" if norm[i, j] > 0.55 else "#1a2332",
                    fontweight="semibold")
        ax.set_xticks([0, 1]); ax.set_yticks([0, 1])
        ax.set_xticklabels(["Absent", "Present"], fontsize=7.5)
        ax.set_yticklabels(["Absent", "Present"], fontsize=7.5, rotation=90, va="center")
        ax.set_title(f"{r['name']}\nthr {r['thr']:.2f} · {r['n_pos']} pos",
                     fontsize=8.6, pad=4.5, linespacing=1.35)
        if k % 4 == 0:
            ax.set_ylabel("True", fontsize=8)
        if k // 4 == 2:
            ax.set_xlabel("Predicted", fontsize=8)
        ax.tick_params(length=0)

    cax = fig.add_axes([0.935, 0.49, 0.012, 0.31])
    cb = fig.colorbar(im, cax=cax)
    cb.set_label("fraction of true row", fontsize=8)
    cb.ax.tick_params(labelsize=7.5)

    fig.text(0.062, 0.884, "A", fontsize=15, fontweight="bold", va="bottom")
    fig.text(0.089, 0.886, "Confusion at each biomarker's deployed threshold",
             fontsize=11.5, va="bottom")

    # ---- B and C: ROC, split so twelve curves stay readable ------------------
    bot = gs[1].subgridspec(1, 2, wspace=0.18)
    halves = [("B", rows[:6], "Six highest AUROC"), ("C", rows[6:], "Six lowest AUROC")]
    palette = ["#d1472c", "#e8a33d", "#5b2d8e", "#1b7f4f", "#2066b8", "#b02f84"]

    for (tag, subset, sub), col in zip(halves, range(2)):
        ax = fig.add_subplot(bot[0, col])
        ax.plot([0, 1], [0, 1], ls="--", lw=0.9, color="#9aa4b2")
        for r, c in zip(subset, palette):
            ax.plot(r["fpr"], r["tpr"], lw=1.5, color=c,
                    label=f"{r['name']}, AUC = {r['auc']:.3f}")
        ax.set_xlim(0, 1); ax.set_ylim(0, 1.004)
        ax.set_xlabel("False Positive Rate (1 − Specificity)", fontsize=9.5)
        if col == 0:
            ax.set_ylabel("True Positive Rate (Sensitivity)", fontsize=9.5)
        ax.tick_params(labelsize=8.5)
        ax.grid(alpha=0.18, lw=0.6)
        ax.legend(loc="lower right", fontsize=8.1, framealpha=0.95,
                  borderpad=0.55, labelspacing=0.34)
        ax.set_title(sub, fontsize=10, pad=7)
        pos = ax.get_position()
        fig.text(pos.x0 - 0.034, pos.y1 + 0.012, tag, fontsize=15,
                 fontweight="bold", va="bottom")

    mean_auc = float(np.mean([r["auc"] for r in rows]))

    # Fold 1 is the BEST of the five, so its mean alone reads better than the
    # model is. The cross-validated figure belongs next to it.
    #
    # These are best-epoch numbers, matching the checkpoint that produced
    # fold1_predictions.npz and the 0.8916 the site reports. docs/scaling.md
    # also records a final-epoch mean of 0.8815; v1/final_metrics.csv holds
    # that one, so do not mix the two.
    CV_FOLDS = [0.9102, 0.9145, 0.8283, 0.8969, 0.9079]   # docs/scaling.md
    fig.suptitle(
        "RETFound ViT-L/16 fine-tuned on OLIVES — 12 predicted biomarkers\n"
        f"held-out fold 1: {meta['n_images']:,} B-scans from {meta['n_patients']} patients"
        f"  ·  mean AUROC {mean_auc:.4f}",
        fontsize=12.5, y=0.980, linespacing=1.5)
    fig.text(0.5, 0.923,
             f"Fold 1 is the best of the five folds, so it flatters the model. Five-fold mean "
             f"AUROC is {np.mean(CV_FOLDS):.4f} \u00b1 {np.std(CV_FOLDS, ddof=1):.4f} "
             f"(folds {min(CV_FOLDS):.3f}\u2013{max(CV_FOLDS):.3f}); it is plotted here because it is "
             f"the one fold whose per-scan predictions were kept.",
             fontsize=8.4, color="#5a6472", ha="center", va="bottom")

    assert abs(mean_auc - CV_FOLDS[1]) < 0.001, (
        f"fold-1 mean {mean_auc:.4f} disagrees with the {CV_FOLDS[1]} recorded in "
        "docs/scaling.md - the npz may be from a different checkpoint")

    fig.savefig(OUT, dpi=190, facecolor="white")
    print(f"wrote {OUT}")
    print(f"  mean AUROC over the 12: {mean_auc:.4f}")
    for r in rows:
        print(f"   {r['name']:<20} AUC {r['auc']:.3f}   {r['n_pos']:>4} pos")


if __name__ == "__main__":
    main()
