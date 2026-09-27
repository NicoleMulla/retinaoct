#!/usr/bin/env python3
"""Fine-tune RETFound (ViT-L/16) for the 16 OLIVES biomarkers — multi-label.

Sixteen independent sigmoids, not a softmax: biomarkers co-occur (the median
labelled image carries two or three). Splits come from the manifest and are
grouped by patient, never by image.

  python3 train_olives.py --fold 0 --epochs 30
  python3 train_olives.py --fold 0 --epochs 1 --limit 64 --smoke   # CPU/MPS check
"""
import argparse, json, os, time
import numpy as np, torch, torch.nn as nn, timm
from PIL import Image
from torch.utils.data import Dataset, DataLoader

ROOT     = os.environ.get("OLIVES_ROOT", "/Users/nicolemulla/oct-data/extracted/olives/OLIVES")
MANIFEST = os.environ.get("OLIVES_MANIFEST", "/Users/nicolemulla/oct-data/train/manifest.csv")
OUTDIR   = os.environ.get("OLIVES_OUT", "/Users/nicolemulla/oct-data/train/runs")
# Encoder repo. The official Nature weights (YukunZhou/RETFound_mae_natureOCT)
# are gated per-account; once access is granted, set OLIVES_ENCODER to swap.
REPO     = os.environ.get("OLIVES_ENCODER", "bitfount/RETFound_MAE_OCT")
WEIGHT_FILE = os.environ.get("OLIVES_ENCODER_FILE", "pytorch_model.bin")
CACHE    = os.environ.get("HF_HOME_MODELS", "/Users/nicolemulla/oct-data/models")
MEAN, STD = (0.485, 0.456, 0.406), (0.229, 0.224, 0.225)   # RETFound uses ImageNet stats


def device():
    if torch.cuda.is_available(): return "cuda"
    if torch.backends.mps.is_available(): return "mps"
    return "cpu"


def read_manifest(path):
    rows, hdr = [], None
    for i, line in enumerate(open(path)):
        p = line.rstrip("\n").split(",")
        if i == 0: hdr = p; continue
        rows.append(dict(zip(hdr, p)))
    meta = json.load(open(path.replace(".csv", "_meta.json")))
    return rows, meta


def resolve(rel):
    rel = rel.lstrip("/")
    for pre in ("TREX_DME", "Prime_FULL"):
        f = os.path.join(ROOT, pre, rel)
        if os.path.exists(f): return f
    return None


class Olives(Dataset):
    """504x496 grayscale B-scans -> 224x224x3. Aspect is already ~1:1, so a
    straight resize introduces no geometric distortion."""

    def __init__(self, rows, biomarkers, train):
        self.rows, self.bm, self.train = rows, biomarkers, train

    def __len__(self): return len(self.rows)

    def __getitem__(self, i):
        r = self.rows[i]
        im = Image.open(r["_file"]).convert("RGB")
        if self.train:
            if np.random.rand() < 0.5: im = im.transpose(Image.FLIP_LEFT_RIGHT)
            ang = np.random.uniform(-7, 7)
            im = im.rotate(ang, resample=Image.BILINEAR)
            s = np.random.uniform(0.88, 1.0)
            w, h = im.size; cw, ch = int(w*s), int(h*s)
            x0 = np.random.randint(0, w-cw+1); y0 = np.random.randint(0, h-ch+1)
            im = im.crop((x0, y0, x0+cw, y0+ch))
        im = im.resize((224, 224), Image.BICUBIC)
        x = np.asarray(im, dtype=np.float32) / 255.0
        if self.train:
            x = np.clip(x * np.random.uniform(0.9, 1.1) + np.random.uniform(-0.05, 0.05), 0, 1)
        x = (x - np.array(MEAN)) / np.array(STD)
        y = np.array([float(r[b]) for b in self.bm], dtype=np.float32)
        return torch.from_numpy(x.transpose(2, 0, 1)).float(), torch.from_numpy(y)


def build_model(n_out, ckpt=None):
    m = timm.create_model("vit_large_patch16_224", pretrained=False, num_classes=n_out)
    if ckpt is None:
        from huggingface_hub import hf_hub_download
        ckpt = hf_hub_download(REPO, WEIGHT_FILE, cache_dir=CACHE,
                               token=os.environ.get("HF_TOKEN"))
    sd = torch.load(ckpt, map_location="cpu", weights_only=False)
    sd = sd.get("model", sd.get("state_dict", sd))
    sd = {k.replace("module.", ""): v for k, v in sd.items()}
    sd = {k: v for k, v in sd.items() if not k.startswith("head.")}   # 1000-class head is irrelevant
    missing, unexpected = m.load_state_dict(sd, strict=False)
    enc_missing = [k for k in missing if not k.startswith("head.")]
    if enc_missing:
        print(f"  WARNING {len(enc_missing)} encoder keys missing, e.g. {enc_missing[:3]}")
    print(f"  encoder loaded from {REPO} — {len(sd)} tensors, "
          f"head re-initialised for {n_out} labels")
    return m


def auroc(y, p):
    """Rank-based AUROC; NaN when a fold contains only one class."""
    pos, neg = p[y == 1], p[y == 0]
    if len(pos) == 0 or len(neg) == 0: return float("nan")
    order = np.argsort(np.concatenate([pos, neg]))
    ranks = np.empty(len(order), dtype=float); ranks[order] = np.arange(1, len(order)+1)
    return (ranks[:len(pos)].sum() - len(pos)*(len(pos)+1)/2) / (len(pos)*len(neg))


def avg_precision(y, p):
    if y.sum() == 0: return float("nan")
    o = np.argsort(-p); y = y[o]
    tp = np.cumsum(y); prec = tp / np.arange(1, len(y)+1)
    return float((prec * y).sum() / y.sum())


def best_f1(y, p):
    """Tune the operating point per biomarker; 0.5 is wrong under this imbalance."""
    if y.sum() == 0: return float("nan"), 0.5
    ts = np.unique(np.round(p, 3)); bf, bt = 0.0, 0.5
    for t in ts:
        pred = p >= t
        tp = float((pred & (y == 1)).sum()); fp = float((pred & (y == 0)).sum())
        fn = float((~pred & (y == 1)).sum())
        f1 = 2*tp / max(2*tp + fp + fn, 1e-9)
        if f1 > bf: bf, bt = f1, float(t)
    return bf, bt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fold", type=int, default=0)
    ap.add_argument("--epochs", type=int, default=30)
    ap.add_argument("--bs", type=int, default=32)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--head-lr", type=float, default=1e-3)
    ap.add_argument("--wd", type=float, default=0.05)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--limit", type=int, default=0, help="cap images (smoke test)")
    ap.add_argument("--smoke", action="store_true", help="tiny run, no checkpoint")
    ap.add_argument("--ckpt", default=None)
    ap.add_argument("--tag", default="")
    a = ap.parse_args()

    dev = device()
    rows, meta = read_manifest(MANIFEST)
    BM = meta["biomarkers"]; usable = meta["usable"]

    for r in rows: r["_file"] = resolve(r["path"])
    missing = [r for r in rows if not r["_file"]]
    if missing: print(f"WARNING {len(missing)} images unresolved on disk")
    rows = [r for r in rows if r["_file"]]

    tr = [r for r in rows if int(r["fold"]) != a.fold]
    va = [r for r in rows if int(r["fold"]) == a.fold]
    if a.limit: tr, va = tr[:a.limit], va[:max(a.limit//2, 8)]

    print(f"device {dev} · fold {a.fold} · train {len(tr)} / val {len(va)} images")
    print(f"train patients {len({r['patient_id'] for r in tr})} · "
          f"val patients {len({r['patient_id'] for r in va})} · "
          f"overlap {len({r['patient_id'] for r in tr} & {r['patient_id'] for r in va})}")

    ytr = np.array([[float(r[b]) for b in BM] for r in tr])
    pos = ytr.sum(0); neg = len(ytr) - pos
    pos_weight = torch.tensor(np.clip(neg/np.maximum(pos, 1), 1, 50), dtype=torch.float32, device=dev)

    dl_tr = DataLoader(Olives(tr, BM, True), batch_size=a.bs, shuffle=True,
                       num_workers=a.workers, pin_memory=(dev == "cuda"), drop_last=True)
    dl_va = DataLoader(Olives(va, BM, False), batch_size=a.bs, shuffle=False,
                       num_workers=a.workers, pin_memory=(dev == "cuda"))

    print("loading RETFound encoder...")
    model = build_model(len(BM), a.ckpt).to(dev)

    head = [p for n, p in model.named_parameters() if n.startswith("head.")]
    body = [p for n, p in model.named_parameters() if not n.startswith("head.")]
    opt = torch.optim.AdamW([{"params": body, "lr": a.lr},
                             {"params": head, "lr": a.head_lr}], weight_decay=a.wd)
    steps = max(a.epochs * len(dl_tr), 1)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=[a.lr, a.head_lr],
                                                total_steps=steps, pct_start=0.1)
    lossf = nn.BCEWithLogitsLoss(pos_weight=pos_weight)
    amp = dev == "cuda"
    scaler = torch.amp.GradScaler("cuda", enabled=amp)

    os.makedirs(OUTDIR, exist_ok=True)
    tag = a.tag or f"fold{a.fold}"
    best = -1.0
    for ep in range(1, a.epochs+1):
        model.train(); t0 = time.time(); tot = 0.0; n = 0
        for x, y in dl_tr:
            x, y = x.to(dev, non_blocking=True), y.to(dev, non_blocking=True)
            opt.zero_grad(set_to_none=True)
            with torch.amp.autocast("cuda", enabled=amp):
                loss = lossf(model(x), y)
            scaler.scale(loss).backward(); scaler.step(opt); scaler.update(); sched.step()
            tot += loss.item()*len(x); n += len(x)
        tr_loss = tot/max(n, 1)

        model.eval(); P, Y = [], []
        with torch.no_grad():
            for x, y in dl_va:
                with torch.amp.autocast("cuda", enabled=amp):
                    o = model(x.to(dev))
                P.append(torch.sigmoid(o.float()).cpu().numpy()); Y.append(y.numpy())
        P, Y = np.concatenate(P), np.concatenate(Y)
        aucs = np.array([auroc(Y[:, j], P[:, j]) for j in range(len(BM))])
        mu = np.nanmean(aucs[np.array(usable)])
        print(f"ep {ep:>3}/{a.epochs}  loss {tr_loss:.4f}  "
              f"mAUROC(usable) {mu:.4f}  {time.time()-t0:.0f}s")

        if mu > best and not a.smoke:
            best = mu
            torch.save({"model": model.state_dict(), "biomarkers": BM,
                        "fold": a.fold, "epoch": ep, "mauroc": float(mu)},
                       f"{OUTDIR}/{tag}_best.pt")

    print(f"\n{'biomarker':<20}{'AUROC':>8}{'AP':>8}{'F1':>8}{'thr':>7}  usable")
    print("-"*62)
    thr = {}
    for j, b in enumerate(BM):
        f1, t = best_f1(Y[:, j], P[:, j]); thr[b] = t
        print(f"{b:<20}{aucs[j]:>8.3f}{avg_precision(Y[:,j],P[:,j]):>8.3f}"
              f"{f1:>8.3f}{t:>7.2f}  {'yes' if usable[j] else 'NO'}")
    print("-"*62)
    print(f"mean AUROC over {sum(usable)} usable biomarkers: {np.nanmean(aucs[np.array(usable)]):.4f}")
    if not a.smoke:
        json.dump({"thresholds": thr, "auroc": aucs.tolist(), "biomarkers": BM,
                   "usable": usable, "fold": a.fold},
                  open(f"{OUTDIR}/{tag}_metrics.json", "w"), indent=2)
        print(f"saved -> {OUTDIR}/{tag}_best.pt")


if __name__ == "__main__":
    main()
