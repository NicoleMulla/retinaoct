#!/usr/bin/env python3
"""Export serving artefacts from a trained checkpoint. RUN THIS ON THE GPU BOX.

Writes everything the inference endpoint needs and cannot reconstruct later
without re-renting a GPU:

  model.safetensors   fine-tuned weights
  reference.npz       embedding mean + inverse covariance over the training
                      images, for the out-of-distribution gate
  serving_config.json per-biomarker thresholds, usable flags, gate cut-offs

The OOD reference must come from the FINE-TUNED encoder — fine-tuning moves the
embedding space, so statistics from the pretrained weights do not transfer.

  python3 export_reference.py --ckpt runs/fold0_best.pt --out serving/
"""
import argparse, json, os, sys
import numpy as np, torch
from PIL import Image
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import train_olives as T


def embed_and_predict(model, files, dev, bs=32):
    embs, preds = [], []
    for i in range(0, len(files), bs):
        xs = []
        for p in files[i:i+bs]:
            im = Image.open(p).convert("RGB").resize((224, 224), Image.BICUBIC)
            x = np.asarray(im, dtype=np.float32) / 255.0
            x = (x - np.array(T.MEAN)) / np.array(T.STD)
            xs.append(torch.from_numpy(x.transpose(2, 0, 1)).float())
        b = torch.stack(xs).to(dev)
        with torch.no_grad():
            f = model.forward_features(b)[:, 0]          # CLS token
            logits = model.head(model.fc_norm(f)) if hasattr(model, "fc_norm") else model.head(f)
        embs.append(f.float().cpu().numpy())
        preds.append(torch.sigmoid(logits.float()).cpu().numpy())
        if (i // bs) % 20 == 0:
            print(f"    {min(i+bs, len(files))}/{len(files)}")
    return np.concatenate(embs), np.concatenate(preds)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt", required=True)
    ap.add_argument("--out", default="serving")
    ap.add_argument("--gate-pct", type=float, default=95.0,
                    help="in-domain percentile that defines the strict gate")
    a = ap.parse_args()

    dev = T.device()
    ck = torch.load(a.ckpt, map_location="cpu", weights_only=False)
    BM = ck["biomarkers"]
    rows, meta = T.read_manifest(T.MANIFEST)
    for r in rows: r["_file"] = T.resolve(r["path"])
    rows = [r for r in rows if r["_file"]]

    model = T.build_model(len(BM)).to(dev)
    model.load_state_dict(ck["model"]); model.eval()
    print(f"loaded {a.ckpt} (fold {ck.get('fold')}, mAUROC {ck.get('mauroc'):.4f})")

    # Reference statistics come from the TRAINING split only — including the
    # validation fold would make the gate look tighter than it is.
    tr = [r for r in rows if int(r["fold"]) != ck["fold"]]
    va = [r for r in rows if int(r["fold"]) == ck["fold"]]
    print(f"embedding {len(tr)} training images for the OOD reference")
    Etr, _ = embed_and_predict(model, [r["_file"] for r in tr], dev)
    print(f"embedding {len(va)} held-out images to calibrate the gate")
    Eva, Pva = embed_and_predict(model, [r["_file"] for r in va], dev)

    mu = Etr.mean(0)
    C = np.cov(Etr.T) + np.eye(Etr.shape[1]) * 1e-3
    P = np.linalg.inv(C)
    d_held = np.sqrt(np.einsum('ij,jk,ik->i', Eva-mu, P, Eva-mu))
    strict = float(np.percentile(d_held, a.gate_pct))
    loose  = float(np.percentile(d_held, 99.5) * 1.5)   # beyond this: refuse outright

    # Per-biomarker thresholds tuned on the held-out fold.
    Yva = np.array([[float(r[b]) for b in BM] for r in va])
    thr, f1s = {}, {}
    for j, b in enumerate(BM):
        f, t = T.best_f1(Yva[:, j], Pva[:, j]); thr[b] = t; f1s[b] = f

    os.makedirs(a.out, exist_ok=True)
    np.savez_compressed(f"{a.out}/reference.npz", mu=mu, precision=P,
                        held_distances=d_held)
    torch.save({"model": model.state_dict(), "biomarkers": BM}, f"{a.out}/model.pt")
    json.dump({"biomarkers": BM, "usable": meta["usable"],
               "pos_patients": meta["pos_patients"],
               "thresholds": thr, "val_f1": f1s,
               "gate": {"strict": strict, "loose": loose,
                        "in_domain_median": float(np.median(d_held))},
               "source_fold": ck["fold"], "mauroc": ck.get("mauroc"),
               "license": "cc-by-nc-4.0 (inherited from RETFound) — non-commercial",
               },
              open(f"{a.out}/serving_config.json", "w"), indent=2)

    print(f"\ngate: in-domain median {np.median(d_held):.1f} · "
          f"strict {strict:.1f} · refuse above {loose:.1f}")
    print(f"wrote {a.out}/{{model.pt, reference.npz, serving_config.json}}")


if __name__ == "__main__":
    main()
