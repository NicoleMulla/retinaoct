#!/usr/bin/env python3
"""The twelve per-biomarker matrices collapsed into single matrices.

    python3 scripts/plot_biomarker_pooled.py

Writes docs/results/evaluation/biomarker_pooled_confusion.png.

There is no one right way to do this, because the task is multi-label: a scan
carries up to twelve independent present/absent calls, not one class. Three
honest collapses, and they disagree in a way that matters:

  A  micro-pooled   every (scan, biomarker) decision thrown into one 2x2.
                    Dominated by the common biomarkers - IR HRF alone is 1,231
                    of the 5,313 positives - so it reads optimistically.
  B  macro-averaged each biomarker's row-normalised matrix weighted equally.
                    Sensitivity drops from 0.843 to 0.729 against A, which is
                    the honest measure of a typical biomarker.
  C  burden         true vs predicted NUMBER of biomarkers on a scan. The only
                    one that is a real square confusion matrix rather than a
                    2x2, and the closest analogue to a multi-class figure.

Fold 1 only, at each biomarker's deployed threshold. See
plot_biomarker_eval.py for the caveat about fold 1 being the best of five.
"""
import csv
import pathlib

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

EVAL = pathlib.Path(__file__).resolve().parent.parent / "docs" / "results" / "evaluation"
OUT = EVAL / "biomarker_pooled_confusion.png"
BINS = [(0, 0), (1, 1), (2, 2), (3, 3), (4, 4), (5, 12)]
BIN_LABELS = ["0", "1", "2", "3", "4", "5+"]


def load():
    d = np.load(EVAL / "fold1_predictions.npz", allow_pickle=True)
    names = [str(x) for x in d["biomarkers"]]
    conf = {r["biomarker"]: r for r in csv.DictReader(open(EVAL / "v1_confusion_fold1.csv"))}
    keys = list(conf)
    idx = [names.index(b) for b in keys]
    thr = np.array([float(conf[b]["threshold"]) for b in keys])
    return d["probs"][:, idx] >= thr, d["labels"][:, idx] > 0.5, keys


def cell_text(ax, M, fmt, norm):
    for (i, j), v in np.ndenumerate(M):
        ax.text(j, i, fmt(v), ha="center", va="center",
                fontsize=11 if M.shape[0] == 2 else 8.4,
                color="white" if norm[i, j] > 0.55 else "#16202e", fontweight="bold")


def main():
    pred, true, keys = load()

    tp = int((pred & true).sum()); fp = int((pred & ~true).sum())
    fn = int((~pred & true).sum()); tn = int((~pred & ~true).sum())
    micro = np.array([[tn, fp], [fn, tp]])
    n = micro.sum()

    macro = np.mean([
        np.array([[int((~pred[:, j] & ~true[:, j]).sum()), int((pred[:, j] & ~true[:, j]).sum())],
                  [int((~pred[:, j] & true[:, j]).sum()), int((pred[:, j] & true[:, j]).sum())]])
        / np.array([[max(int((~true[:, j]).sum()), 1)], [max(int(true[:, j].sum()), 1)]])
        for j in range(len(keys))], axis=0)

    tc, pc = true.sum(1), pred.sum(1)
    def which(v):
        return next(i for i, (lo, hi) in enumerate(BINS) if lo <= v <= hi)
    burden = np.zeros((len(BINS), len(BINS)), int)
    for a, b in zip(tc, pc):
        burden[which(a), which(b)] += 1

    fig, axes = plt.subplots(1, 3, figsize=(15.4, 6.9))
    fig.subplots_adjust(left=0.058, right=0.975, top=0.655, bottom=0.175, wspace=0.42)

    # A ---------------------------------------------------------------------
    ax = axes[0]
    nrm = micro / micro.sum(axis=1, keepdims=True)
    ax.imshow(nrm, cmap="Blues", vmin=0, vmax=1)
    cell_text(ax, micro, lambda v: f"{v:,}", nrm)
    ax.set_title("A  Micro-pooled\nall %s scan x biomarker decisions" % format(n, ","),
                 fontsize=10.5, pad=9, linespacing=1.5)
    ax.set_xlabel("Predicted"); ax.set_ylabel("True")
    sens, spec = tp / (tp + fn), tn / (tn + fp)
    ax.text(0.5, -0.255, f"sensitivity {sens:.3f}  ·  specificity {spec:.3f}  ·  "
                        f"accuracy {(tp+tn)/n:.3f}",
            transform=ax.transAxes, ha="center", fontsize=9)

    # B ---------------------------------------------------------------------
    ax = axes[1]
    ax.imshow(macro, cmap="Blues", vmin=0, vmax=1)
    cell_text(ax, macro, lambda v: f"{v:.3f}", macro)
    ax.set_title("B  Macro-averaged\neach biomarker weighted equally",
                 fontsize=10.5, pad=9, linespacing=1.5)
    ax.set_xlabel("Predicted"); ax.set_ylabel("True")
    ax.text(0.5, -0.255, f"sensitivity {macro[1,1]:.3f}  ·  specificity {macro[0,0]:.3f}"
                        f"   (sensitivity {sens - macro[1,1]:.3f} below A)",
            transform=ax.transAxes, ha="center", fontsize=9)

    for ax in axes[:2]:
        ax.set_xticks([0, 1]); ax.set_yticks([0, 1])
        ax.set_xticklabels(["Absent", "Present"])
        ax.set_yticklabels(["Absent", "Present"], rotation=90, va="center")
        ax.tick_params(length=0)

    # C ---------------------------------------------------------------------
    ax = axes[2]
    nrm = burden / burden.sum(axis=1, keepdims=True).clip(min=1)
    ax.imshow(nrm, cmap="Blues", vmin=0, vmax=1)
    cell_text(ax, burden, lambda v: f"{v:,}" if v else "·", nrm)
    ax.set_xticks(range(6)); ax.set_yticks(range(6))
    ax.set_xticklabels(BIN_LABELS); ax.set_yticklabels(BIN_LABELS)
    ax.tick_params(length=0)
    ax.set_title("C  Burden\nhow many biomarkers on the scan",
                 fontsize=10.5, pad=9, linespacing=1.5)
    ax.set_xlabel("Predicted count"); ax.set_ylabel("True count")
    exact = 100 * np.trace(burden) / burden.sum()
    near = 100 * sum(burden[i, j] for i in range(6) for j in range(6)
                     if abs(i - j) <= 1) / burden.sum()
    ax.text(0.5, -0.255, f"exact {exact:.1f}%  ·  within one {near:.1f}%  ·  "
                        f"mean {tc.mean():.2f} true vs {pc.mean():.2f} predicted",
            transform=ax.transAxes, ha="center", fontsize=9)

    fig.suptitle("Twelve biomarkers collapsed into one matrix — three ways, fold 1",
                 fontsize=13, y=0.965)
    fig.text(0.5, 0.878,
             "A and B are the same 22,344 decisions. They differ only in weighting, and that alone moves "
             "sensitivity by %.3f:\nthe common biomarkers carry A, while B lets the rare ones — SHRM at 13 "
             "positives, atrophy at 12 — count as much as IR HRF at 1,231."
             % (sens - macro[1, 1]),
             ha="center", va="top", fontsize=9.2, color="#55606e", linespacing=1.6)

    fig.savefig(OUT, dpi=190, facecolor="white")
    print(f"wrote {OUT}")
    print(f"  micro  sens {sens:.3f}  spec {spec:.3f}")
    print(f"  macro  sens {macro[1,1]:.3f}  spec {macro[0,0]:.3f}")
    print(f"  burden exact {exact:.1f}%  within-one {near:.1f}%")


if __name__ == "__main__":
    main()
