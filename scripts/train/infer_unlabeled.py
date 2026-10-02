#!/usr/bin/env python3
"""Predict the 16 OLIVES biomarkers for the unlabelled images using the v1 model.

Writes one row per (image, biomarker) for import into `biomarker_values` under a
separate source id, so model output never mixes with the OLIVES expert labels.

Only the biomarkers marked usable are emitted. The four with 1-5 positive
patients (dril, ped_serous, rpe_disruption, vmt) would produce confident
nonsense at scale, so they are recorded as NULL rather than fabricated.

Each image also gets a Mahalanobis distance to the training distribution, so
out-of-distribution scans can be flagged downstream rather than silently
trusted.

  python3 infer_unlabeled.py --model serving/model.pt --ref serving/reference.npz \
      --config serving/serving_config.json --map unlab_map.csv --out predictions.csv
"""
import argparse, csv, json, os, sys, time
import numpy as np, torch, timm
from PIL import Image
from torch.utils.data import Dataset, DataLoader

ROOT  = os.environ.get("OLIVES_UNLAB_ROOT", "/workspace/unlab")
MEAN, STD = (0.485, 0.456, 0.406), (0.229, 0.224, 0.225)


class Images(Dataset):
    def __init__(self, rows): self.rows = rows
    def __len__(self): return len(self.rows)
    def __getitem__(self, i):
        iid, rel = self.rows[i]
        im = Image.open(os.path.join(ROOT, rel)).convert("RGB").resize((224,224), Image.BICUBIC)
        x = (np.asarray(im, dtype=np.float32)/255.0 - np.array(MEAN))/np.array(STD)
        return torch.from_numpy(x.transpose(2,0,1)).float(), int(iid)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--ref", required=True)
    ap.add_argument("--config", required=True)
    ap.add_argument("--map", required=True, help="image_id,relpath CSV")
    ap.add_argument("--out", default="predictions.csv")
    ap.add_argument("--bs", type=int, default=64)
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()

    cfg = json.load(open(a.config))
    BM, usable, thr = cfg["biomarkers"], cfg["usable"], cfg["thresholds"]
    gate = cfg["gate"]
    ref = np.load(a.ref); mu, P = ref["mu"], ref["precision"]

    rows = [(r["image_id"], r["relpath"]) for r in csv.DictReader(open(a.map))]
    if a.limit: rows = rows[:a.limit]
    print(f"{len(rows)} images · {sum(usable)} usable biomarkers of {len(BM)}")

    dev = "cuda" if torch.cuda.is_available() else "cpu"
    ck = torch.load(a.model, map_location="cpu", weights_only=False)
    model = timm.create_model("vit_large_patch16_224", pretrained=False, num_classes=len(BM))
    model.load_state_dict(ck["model"]); model.eval().to(dev)
    print(f"model loaded on {dev}")

    dl = DataLoader(Images(rows), batch_size=a.bs, shuffle=False,
                    num_workers=a.workers, pin_memory=(dev=="cuda"))

    fh = open(a.out, "w", newline="")
    w = csv.writer(fh)
    w.writerow(["image_id","biomarker","value","confidence","ood_distance","verdict"])
    t0 = time.time(); done = 0; nrows = 0
    flags = {"ok":0, "out_of_domain":0, "rejected":0}

    with torch.no_grad():
        for x, ids in dl:
            x = x.to(dev, non_blocking=True)
            with torch.amp.autocast("cuda", enabled=(dev=="cuda")):
                f = model.forward_features(x)[:, 0]
                logits = model.head(model.fc_norm(f)) if hasattr(model, "fc_norm") else model.head(f)
            probs = torch.sigmoid(logits.float()).cpu().numpy()
            emb = f.float().cpu().numpy()
            d = emb - mu
            dist = np.sqrt(np.einsum('ij,jk,ik->i', d, P, d))

            for k, iid in enumerate(ids.tolist()):
                dd = float(dist[k])
                verdict = ("rejected" if dd > gate["loose"]
                           else "ok" if dd <= gate["strict"] else "out_of_domain")
                flags[verdict] += 1
                if verdict == "rejected":
                    continue                      # no predictions for far-OOD images
                for j, b in enumerate(BM):
                    if not usable[j]:
                        continue                  # too few training patients to mean anything
                    p = float(probs[k, j])
                    w.writerow([iid, b, int(p >= thr[b]), round(p, 5),
                                round(dd, 2), verdict])
                    nrows += 1
            done += len(ids)
            if done % (a.bs*40) == 0:
                el = time.time()-t0
                print(f"  {done}/{len(rows)}  {done/el:.0f} img/s  eta {(len(rows)-done)/(done/el)/60:.1f} min")
    fh.close()
    el = time.time()-t0
    print(f"\n{done} images in {el/60:.1f} min ({done/el:.0f} img/s) -> {nrows} rows in {a.out}")
    print(f"gate: ok {flags['ok']}  out_of_domain {flags['out_of_domain']}  rejected {flags['rejected']}")
    json.dump({"n_images":done,"n_rows":nrows,"gate_counts":flags,
               "model":os.path.basename(a.model),"usable":usable,"biomarkers":BM,
               "thresholds":thr,"gate":gate},
              open(a.out.replace(".csv","_summary.json"),"w"), indent=2)


if __name__ == "__main__":
    main()
