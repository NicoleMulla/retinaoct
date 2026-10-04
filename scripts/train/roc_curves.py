#!/usr/bin/env python3
"""Plot genuine ROC and precision-recall curves for the v1 biomarker model.

The published checkpoint is fold 1's, so the only honest evaluation set is fold
1's validation split — 1,862 images from 17 patients the model never saw.
Scoring all 9,408 labelled images would fold its own training data into the
curves and inflate every number.

AUROC was already reported from training; this writes out the curves behind
those numbers, plus PR curves — which matter more here, because at 0.7%
prevalence a biomarker can post a respectable AUROC while being useless in
practice.

  python3 roc_curves.py --fold 1 --out evaluation/
"""
import argparse, json, os, sys
import numpy as np, torch, timm
from PIL import Image
from torch.utils.data import Dataset, DataLoader

MANIFEST = os.environ.get("OLIVES_MANIFEST", "/Users/nicolemulla/oct-data/train/manifest.csv")
ROOT     = os.environ.get("OLIVES_ROOT", "/Users/nicolemulla/oct-data/extracted/olives/OLIVES")
MEAN, STD = (0.485, 0.456, 0.406), (0.229, 0.224, 0.225)


def resolve(rel):
    rel = rel.lstrip("/")
    for pre in ("TREX_DME", "Prime_FULL"):
        f = os.path.join(ROOT, pre, rel)
        if os.path.exists(f): return f
    return None


class Val(Dataset):
    def __init__(self, rows, bm): self.rows, self.bm = rows, bm
    def __len__(self): return len(self.rows)
    def __getitem__(self, i):
        r = self.rows[i]
        im = Image.open(r["_f"]).convert("RGB").resize((224, 224), Image.BICUBIC)
        x = (np.asarray(im, dtype=np.float32)/255.0 - np.array(MEAN))/np.array(STD)
        y = np.array([float(r[b]) for b in self.bm], dtype=np.float32)
        return torch.from_numpy(x.transpose(2, 0, 1)).float(), torch.from_numpy(y)


def roc_points(y, s):
    """TPR/FPR at every distinct score, descending. Pure numpy — no sklearn."""
    o = np.argsort(-s); y = y[o]; s = s[o]
    tp = np.cumsum(y); fp = np.cumsum(1 - y)
    P, N = y.sum(), len(y) - y.sum()
    if P == 0 or N == 0: return None
    # keep one point per distinct score so ties don't create spurious steps
    keep = np.r_[np.diff(s) != 0, True]
    tpr = np.r_[0.0, tp[keep]/P]; fpr = np.r_[0.0, fp[keep]/N]
    auc = np.trapezoid(tpr, fpr) if hasattr(np, "trapezoid") else np.trapz(tpr, fpr)
    return fpr, tpr, float(auc)


def pr_points(y, s):
    o = np.argsort(-s); y = y[o]
    tp = np.cumsum(y); P = y.sum()
    if P == 0: return None
    prec = tp/np.arange(1, len(y)+1); rec = tp/P
    # AP = mean precision at each positive; y is already score-sorted here
    ap = float((prec*y).sum()/P)
    return rec, prec, ap


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--config", required=True)
    ap.add_argument("--fold", type=int, default=1)
    ap.add_argument("--out", default="/Users/nicolemulla/oct-data/train/final/evaluation")
    ap.add_argument("--bs", type=int, default=16)
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()

    cfg = json.load(open(a.config))
    BM, usable, thr = cfg["biomarkers"], cfg["usable"], cfg["thresholds"]

    hdr = None; rows = []
    for i, line in enumerate(open(MANIFEST)):
        p = line.rstrip("\n").split(",")
        if i == 0: hdr = p; continue
        d = dict(zip(hdr, p))
        if int(d["fold"]) == a.fold: rows.append(d)
    for r in rows: r["_f"] = resolve(r["path"])
    rows = [r for r in rows if r["_f"]]
    print(f"fold {a.fold} validation: {len(rows)} images, "
          f"{len({r['patient_id'] for r in rows})} patients")

    dev = "mps" if torch.backends.mps.is_available() else "cpu"
    ck = torch.load(a.model, map_location="cpu", weights_only=False)
    model = timm.create_model("vit_large_patch16_224", pretrained=False, num_classes=len(BM))
    model.load_state_dict(ck["model"]); model.eval().to(dev)
    # the published model.pt stores only weights + biomarker order; provenance of
    # which fold it came from lives in serving_config.json
    src = cfg.get("source_fold", "?"); mu = cfg.get("mauroc")
    print(f"loaded checkpoint from fold {src}"
          + (f" (cross-fold mAUROC {mu:.4f})" if isinstance(mu, (int, float)) else "")
          + f" on {dev}")
    if isinstance(src, int) and src != a.fold:
        print(f"  WARNING evaluating on fold {a.fold} but the checkpoint trained on all "
              f"folds except {src} — use --fold {src} for a clean held-out set")

    dl = DataLoader(Val(rows, BM), batch_size=a.bs, shuffle=False, num_workers=a.workers)
    P, Y = [], []
    import time; t0 = time.time()
    with torch.no_grad():
        for n, (x, y) in enumerate(dl, 1):
            P.append(torch.sigmoid(model(x.to(dev)).float()).cpu().numpy()); Y.append(y.numpy())
            if n % 20 == 0:
                done = n*a.bs
                print(f"  {done}/{len(rows)}  {done/(time.time()-t0):.1f} img/s", flush=True)
    P, Y = np.concatenate(P), np.concatenate(Y)
    os.makedirs(a.out, exist_ok=True)
    np.savez_compressed(f"{a.out}/fold{a.fold}_predictions.npz",
                        probs=P, labels=Y, biomarkers=np.array(BM))
    print(f"\npredictions saved ({P.shape[0]} x {P.shape[1]})")

    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    idx = [j for j, u in enumerate(usable) if u and Y[:, j].sum() > 0]
    order = sorted(idx, key=lambda j: -roc_points(Y[:, j], P[:, j])[2])
    stats = []

    for kind in ("roc", "pr"):
        ncol = 4; nrow = int(np.ceil(len(order)/ncol))
        fig, axes = plt.subplots(nrow, ncol, figsize=(3.3*ncol, 3.2*nrow))
        axes = np.atleast_1d(axes).ravel()
        for ax, j in zip(axes, order):
            y, s = Y[:, j], P[:, j]
            if kind == "roc":
                fpr, tpr, auc = roc_points(y, s)
                ax.plot(fpr, tpr, lw=1.8, color="#2f7ed8")
                ax.plot([0, 1], [0, 1], ls=":", lw=1, color="#999")
                ax.set_xlabel("false positive rate"); ax.set_ylabel("true positive rate")
                ax.set_title(f"{BM[j]}\nAUROC {auc:.3f}  (n+={int(y.sum())})", fontsize=8.5)
            else:
                rec, prec, apv = pr_points(y, s)
                ax.plot(rec, prec, lw=1.8, color="#e0962c")
                ax.axhline(y.mean(), ls=":", lw=1, color="#999")
                ax.set_xlabel("recall"); ax.set_ylabel("precision")
                ax.set_title(f"{BM[j]}\nAP {apv:.3f}  (prevalence {y.mean():.1%})", fontsize=8.5)
            ax.set_xlim(-.02, 1.02); ax.set_ylim(-.02, 1.02); ax.grid(alpha=.25)
        for ax in axes[len(order):]: ax.axis("off")
        fig.suptitle(f"v1 RETFound/OLIVES — {'ROC' if kind=='roc' else 'Precision-Recall'} curves"
                     f"  ·  fold {a.fold} held-out ({len(rows)} images, "
                     f"{len({r['patient_id'] for r in rows})} unseen patients)", fontsize=10.5)
        fig.tight_layout(rect=[0, 0, 1, 0.97])
        fig.savefig(f"{a.out}/v1_{kind}_curves.png", dpi=140)
        print(f"wrote {a.out}/v1_{kind}_curves.png")

    for j in order:
        y, s = Y[:, j], P[:, j]
        _, _, auc = roc_points(y, s); _, _, apv = pr_points(y, s)
        stats.append(dict(biomarker=BM[j], auroc=round(auc, 4), ap=round(apv, 4),
                          n_pos=int(y.sum()), prevalence=round(float(y.mean()), 4),
                          threshold=thr.get(BM[j])))
    json.dump(dict(fold=a.fold, n_images=len(rows),
                   n_patients=len({r["patient_id"] for r in rows}), per_biomarker=stats),
              open(f"{a.out}/v1_curve_stats.json", "w"), indent=2)
    print(f"\n{'biomarker':<20}{'AUROC':>8}{'AP':>8}{'n+':>7}{'prev':>8}")
    print("-"*51)
    for s in stats:
        print(f"{s['biomarker']:<20}{s['auroc']:>8.3f}{s['ap']:>8.3f}{s['n_pos']:>7}{s['prevalence']:>8.1%}")


if __name__ == "__main__":
    main()
