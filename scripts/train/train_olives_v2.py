#!/usr/bin/env python3
"""Scaling experiments for the OLIVES biomarker model. SEPARATE from the v1
baseline — scripts/train/train_olives.py is frozen at tag `baseline-v1`
(mAUROC 0.8815 +/- 0.0315) and must not be edited.

Three things v1 could not do:

  --encoder     swap ViT-B / ViT-L / ViT-H to measure whether capacity helps
  --weights     retfound | imagenet | none, so size and pretraining can be
                separated instead of confounded
  --slices 3    feed adjacent B-scans (n-1, n, n+1) as the three channels
                instead of triplicating one grayscale slice, which is what v1
                does and which wastes two thirds of the input

Log lines are byte-compatible with v1 so collect_curves.py parses both and the
runs compare directly.

  python3 train_olives_v2.py --tag vitB_in  --encoder vit_base_patch16_224 --weights imagenet
  python3 train_olives_v2.py --tag vitL_ret_slices --slices 3
"""
import argparse, json, os, time
import numpy as np, torch, torch.nn as nn, timm
from PIL import Image
from torch.utils.data import Dataset, DataLoader

ROOT     = os.environ.get("OLIVES_ROOT", "/workspace/data")
MANIFEST = os.environ.get("OLIVES_MANIFEST", "/workspace/manifest.csv")
OUTDIR   = os.environ.get("OLIVES_OUT", "/workspace/runs")
CACHE    = os.environ.get("HF_HOME_MODELS", "/workspace/models")
RETFOUND = os.environ.get("OLIVES_ENCODER", "bitfount/RETFound_MAE_OCT")
RETFILE  = os.environ.get("OLIVES_ENCODER_FILE", "pytorch_model.bin")
MEAN, STD = (0.485, 0.456, 0.406), (0.229, 0.224, 0.225)


def device():
    return "cuda" if torch.cuda.is_available() else ("mps" if torch.backends.mps.is_available() else "cpu")


def read_manifest(path):
    rows, hdr = [], None
    for i, line in enumerate(open(path)):
        p = line.rstrip("\n").split(",")
        if i == 0: hdr = p; continue
        rows.append(dict(zip(hdr, p)))
    return rows, json.load(open(path.replace(".csv", "_meta.json")))


def resolve(rel):
    rel = rel.lstrip("/")
    for pre in ("TREX_DME", "Prime_FULL"):
        f = os.path.join(ROOT, pre, rel)
        if os.path.exists(f): return f
    return None


class Olives(Dataset):
    """Labelled volumes are complete (all 49 B-scans present), so for slices=3
    the neighbours of any interior scan are on disk. Edges clamp to themselves."""

    def __init__(self, rows, biomarkers, train, slices=1, img_size=224, vol_index=None):
        self.rows, self.bm, self.train = rows, biomarkers, train
        self.slices, self.img = slices, img_size
        self.vol = vol_index or {}

    def __len__(self): return len(self.rows)

    def _neighbour(self, r, delta):
        key = (r["eye_id"], r["visit"])
        idx = int(r["scan_index"]) + delta
        f = self.vol.get(key, {}).get(idx)
        return f or r["_file"]          # clamp at volume edges

    def __getitem__(self, i):
        r = self.rows[i]
        if self.slices == 3:
            paths = [self._neighbour(r, -1), r["_file"], self._neighbour(r, +1)]
            chans = [Image.open(p).convert("L") for p in paths]
            im = Image.merge("RGB", [c.resize(chans[1].size) if c.size != chans[1].size else c
                                     for c in chans])
        else:
            im = Image.open(r["_file"]).convert("RGB")

        if self.train:
            if np.random.rand() < 0.5: im = im.transpose(Image.FLIP_LEFT_RIGHT)
            im = im.rotate(np.random.uniform(-7, 7), resample=Image.BILINEAR)
            s = np.random.uniform(0.88, 1.0)
            w, h = im.size; cw, ch = int(w*s), int(h*s)
            x0 = np.random.randint(0, w-cw+1); y0 = np.random.randint(0, h-ch+1)
            im = im.crop((x0, y0, x0+cw, y0+ch))
        im = im.resize((self.img, self.img), Image.BICUBIC)
        x = np.asarray(im, dtype=np.float32) / 255.0
        if self.train:
            x = np.clip(x * np.random.uniform(0.9, 1.1) + np.random.uniform(-0.05, 0.05), 0, 1)
        x = (x - np.array(MEAN)) / np.array(STD)
        y = np.array([float(r[b]) for b in self.bm], dtype=np.float32)
        return torch.from_numpy(x.transpose(2, 0, 1)).float(), torch.from_numpy(y)


def build_model(arch, weights, n_out, img_size):
    kw = dict(pretrained=False, num_classes=n_out)
    if img_size != 224: kw["img_size"] = img_size

    if weights == "retfound":
        if "large" not in arch:
            raise SystemExit(f"RETFound weights exist only for ViT-L; {arch} needs --weights imagenet")
        m = timm.create_model(arch, **kw)
        from huggingface_hub import hf_hub_download
        ck = hf_hub_download(RETFOUND, RETFILE, cache_dir=CACHE, token=os.environ.get("HF_TOKEN"))
        sd = torch.load(ck, map_location="cpu", weights_only=False)
        sd = sd.get("model", sd.get("state_dict", sd))
        sd = {k.replace("module.", ""): v for k, v in sd.items() if not k.startswith("head.")}
        missing, _ = m.load_state_dict(sd, strict=False)
        enc_missing = [k for k in missing if not k.startswith("head.")]
        if enc_missing: print(f"  WARNING {len(enc_missing)} encoder keys missing")
        src = RETFOUND
    elif weights == "mae_olives":
        # Encoder exported by mae_continue.py — RETFound after continued MAE
        # pretraining on OLIVES. Same ViT-L shape, so it loads like RETFound.
        m = timm.create_model(arch, **kw)
        path = os.environ.get("OLIVES_MAE_ENCODER", "/workspace/mae_out/mae_olives_encoder.pt")
        sd = torch.load(path, map_location="cpu", weights_only=False)
        sd = sd.get("model", sd)
        sd = {k.replace("module.", ""): v for k, v in sd.items() if not k.startswith("head.")}
        missing, _ = m.load_state_dict(sd, strict=False)
        enc_missing = [k for k in missing if not k.startswith("head.")]
        if enc_missing: print(f"  WARNING {len(enc_missing)} encoder keys missing")
        src = f"MAE-continued ({os.path.basename(path)})"
    elif weights == "imagenet":
        m = timm.create_model(arch, pretrained=True, num_classes=n_out,
                             **({"img_size": img_size} if img_size != 224 else {}))
        src = "timm/imagenet"
    else:
        m = timm.create_model(arch, **kw); src = "random init"

    p = sum(x.numel() for x in m.parameters())/1e6
    print(f"  encoder loaded from {src} — {arch}, {p:.1f}M params, "
          f"head re-initialised for {n_out} labels")
    return m


def auroc(y, p):
    pos, neg = p[y == 1], p[y == 0]
    if len(pos) == 0 or len(neg) == 0: return float("nan")
    order = np.argsort(np.concatenate([pos, neg]))
    ranks = np.empty(len(order), dtype=float); ranks[order] = np.arange(1, len(order)+1)
    return (ranks[:len(pos)].sum() - len(pos)*(len(pos)+1)/2) / (len(pos)*len(neg))


def avg_precision(y, p):
    if y.sum() == 0: return float("nan")
    o = np.argsort(-p); y = y[o]
    tp = np.cumsum(y); prec = tp/np.arange(1, len(y)+1)
    return float((prec*y).sum()/y.sum())


def best_f1(y, p):
    if y.sum() == 0: return float("nan"), 0.5
    bf, bt = 0.0, 0.5
    for t in np.unique(np.round(p, 3)):
        pred = p >= t
        tp = float((pred & (y == 1)).sum()); fp = float((pred & (y == 0)).sum())
        fn = float((~pred & (y == 1)).sum())
        f1 = 2*tp/max(2*tp+fp+fn, 1e-9)
        if f1 > bf: bf, bt = f1, float(t)
    return bf, bt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fold", type=int, default=0)
    ap.add_argument("--epochs", type=int, default=15)   # v1 curves peaked at ep 16; 30 was waste
    ap.add_argument("--bs", type=int, default=32)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--head-lr", type=float, default=1e-3)
    ap.add_argument("--wd", type=float, default=0.05)
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--encoder", default="vit_large_patch16_224")
    ap.add_argument("--weights", default="retfound",
                    choices=["retfound","imagenet","none","mae_olives"],
                    help="mae_olives = encoder from mae_continue.py, i.e. RETFound "
                         "further pretrained on the OLIVES corpus")
    ap.add_argument("--slices", type=int, default=1, choices=[1,3])
    ap.add_argument("--img-size", type=int, default=224)
    ap.add_argument("--grad-ckpt", action="store_true", help="trade speed for VRAM")
    ap.add_argument("--tag", default="v2")
    a = ap.parse_args()

    dev = device()
    rows, meta = read_manifest(MANIFEST)
    BM, usable = meta["biomarkers"], meta["usable"]
    for r in rows: r["_file"] = resolve(r["path"])
    missing = sum(1 for r in rows if not r["_file"])
    if missing: print(f"WARNING {missing} images unresolved")
    rows = [r for r in rows if r["_file"]]

    vol = {}
    if a.slices == 3:
        for r in rows:
            vol.setdefault((r["eye_id"], r["visit"]), {})[int(r["scan_index"])] = r["_file"]
        sizes = [len(v) for v in vol.values()]
        # One TREX volume uses two-part filenames (TREXA_000004_000028.tif) and the
        # original indexer read the first number as scan_index, so its 49 scans all
        # share index 4. Those images clamp to themselves and fall back to v1
        # behaviour. The manifest is left untouched so run-to-run comparison holds.
        orphan = sum(1 for r in rows
                     if len(vol.get((r["eye_id"], r["visit"]), {})) < 2)
        print(f"volume index: {len(vol)} volumes, {min(sizes)}-{max(sizes)} scans each")
        print(f"  {orphan} images ({100*orphan/len(rows):.2f}%) have no neighbours — "
              f"these fall back to single-slice input")

    tr = [r for r in rows if int(r["fold"]) != a.fold]
    va = [r for r in rows if int(r["fold"]) == a.fold]
    print(f"device {dev} · fold {a.fold} · train {len(tr)} / val {len(va)} images")
    print(f"train patients {len({r['patient_id'] for r in tr})} · "
          f"val patients {len({r['patient_id'] for r in va})} · "
          f"overlap {len({r['patient_id'] for r in tr} & {r['patient_id'] for r in va})}")
    print(f"config: {a.encoder} · weights={a.weights} · slices={a.slices} · img={a.img_size}")

    ytr = np.array([[float(r[b]) for b in BM] for r in tr])
    pos = ytr.sum(0); neg = len(ytr)-pos
    pw = torch.tensor(np.clip(neg/np.maximum(pos,1),1,50), dtype=torch.float32, device=dev)

    dl_tr = DataLoader(Olives(tr, BM, True, a.slices, a.img_size, vol), batch_size=a.bs,
                       shuffle=True, num_workers=a.workers, pin_memory=(dev=="cuda"), drop_last=True)
    dl_va = DataLoader(Olives(va, BM, False, a.slices, a.img_size, vol), batch_size=a.bs,
                       shuffle=False, num_workers=a.workers, pin_memory=(dev=="cuda"))

    print("loading encoder...")
    model = build_model(a.encoder, a.weights, len(BM), a.img_size).to(dev)
    if a.grad_ckpt:
        model.set_grad_checkpointing(True); print("  gradient checkpointing on")

    head = [p for n,p in model.named_parameters() if n.startswith("head.")]
    body = [p for n,p in model.named_parameters() if not n.startswith("head.")]
    opt = torch.optim.AdamW([{"params":body,"lr":a.lr},{"params":head,"lr":a.head_lr}],
                            weight_decay=a.wd)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=[a.lr,a.head_lr],
                                                total_steps=max(a.epochs*len(dl_tr),1), pct_start=0.1)
    lossf = nn.BCEWithLogitsLoss(pos_weight=pw)
    amp = dev == "cuda"
    scaler = torch.amp.GradScaler("cuda", enabled=amp)

    os.makedirs(OUTDIR, exist_ok=True)
    best = -1.0
    for ep in range(1, a.epochs+1):
        model.train(); t0=time.time(); tot=0.0; n=0
        for x,y in dl_tr:
            x,y = x.to(dev,non_blocking=True), y.to(dev,non_blocking=True)
            opt.zero_grad(set_to_none=True)
            with torch.amp.autocast("cuda", enabled=amp):
                loss = lossf(model(x), y)
            scaler.scale(loss).backward(); scaler.step(opt); scaler.update(); sched.step()
            tot += loss.item()*len(x); n += len(x)
        model.eval(); P,Y=[],[]
        with torch.no_grad():
            for x,y in dl_va:
                with torch.amp.autocast("cuda", enabled=amp):
                    o = model(x.to(dev))
                P.append(torch.sigmoid(o.float()).cpu().numpy()); Y.append(y.numpy())
        P,Y = np.concatenate(P), np.concatenate(Y)
        aucs = np.array([auroc(Y[:,j],P[:,j]) for j in range(len(BM))])
        mu = np.nanmean(aucs[np.array(usable)])
        # format matches v1 exactly so collect_curves.py reads both
        print(f"ep {ep:>3}/{a.epochs}  loss {tot/max(n,1):.4f}  "
              f"mAUROC(usable) {mu:.4f}  {time.time()-t0:.0f}s")
        if mu > best:
            best = mu
            torch.save({"model":model.state_dict(),"biomarkers":BM,"fold":a.fold,
                        "epoch":ep,"mauroc":float(mu),"encoder":a.encoder,
                        "weights":a.weights,"slices":a.slices,"img_size":a.img_size},
                       f"{OUTDIR}/{a.tag}_fold{a.fold}_best.pt")

    print(f"\n{'biomarker':<20}{'AUROC':>8}{'AP':>8}{'F1':>8}{'thr':>7}  usable")
    print("-"*62)
    thr={}
    for j,b in enumerate(BM):
        f1,t = best_f1(Y[:,j],P[:,j]); thr[b]=t
        print(f"{b:<20}{aucs[j]:>8.3f}{avg_precision(Y[:,j],P[:,j]):>8.3f}{f1:>8.3f}{t:>7.2f}  "
              f"{'yes' if usable[j] else 'NO'}")
    print("-"*62)
    print(f"mean AUROC over {sum(usable)} usable biomarkers: {np.nanmean(aucs[np.array(usable)]):.4f}")
    json.dump({"thresholds":thr,"auroc":aucs.tolist(),"biomarkers":BM,"usable":usable,
               "fold":a.fold,"config":vars(a)},
              open(f"{OUTDIR}/{a.tag}_fold{a.fold}_metrics.json","w"), indent=2)


if __name__ == "__main__":
    main()
