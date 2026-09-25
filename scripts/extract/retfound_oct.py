#!/usr/bin/env python3
"""RETFound (ViT-L, MAE-pretrained on retinal images) fine-tuned for OCT pathology.

Predicts four classes — CNV, DME, drusen, normal — with softmax confidences.
Weights: bitfount/RETFound_MAE_OCT_CNV_DME_DRU on HuggingFace (ungated).

The class index order is not recorded in the model config, so it is determined
empirically against Kermany images whose labels are known from their directory,
rather than assumed.

  python3 retfound_oct.py --calibrate     # work out the class order
  python3 retfound_oct.py --n 12          # run on OLIVES images
  python3 retfound_oct.py --n 12 --write  # ...and store with attribution
"""
import argparse, glob, json, os, random, sys
import numpy as np, torch, timm
from PIL import Image
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from _common import connect, register_source, write_values, resolve, sample_images

REPO   = "bitfount/RETFound_MAE_OCT_CNV_DME_DRU"
CACHE  = "/Users/nicolemulla/oct-data/models"
ORDER  = "/Users/nicolemulla/oct-data/models/retfound_class_order.json"
KERMANY= "/Users/nicolemulla/oct-data/extracted/kermany-oct2017-v2/OCT2017"
MEAN, STD = (0.485,0.456,0.406), (0.229,0.224,0.225)

SOURCE = dict(key="retfound_oct_cnv_dme_dru_v1",
              name="RETFound ViT-L (OCT pathology, 4-class)",
              kind="model", version="bitfount/RETFound_MAE_OCT_CNV_DME_DRU",
              notes="MAE-pretrained retinal foundation model fine-tuned for CNV/DME/drusen/normal. "
                    "Outputs softmax confidence per class. Class order calibrated against Kermany.")

def device():
    return "mps" if torch.backends.mps.is_available() else "cpu"

def load_model():
    from huggingface_hub import hf_hub_download
    w = hf_hub_download(REPO, "pytorch_model.bin", cache_dir=CACHE)
    m = timm.create_model("vit_large_patch16_224", pretrained=False, num_classes=4)
    sd = torch.load(w, map_location="cpu", weights_only=False)
    sd = sd.get("model", sd.get("state_dict", sd))
    sd = {k.replace("module.",""): v for k,v in sd.items()}
    missing, unexpected = m.load_state_dict(sd, strict=False)
    if len(missing) > 4:
        print(f"  warning: {len(missing)} missing keys, e.g. {missing[:3]}")
    return m.eval().to(device())

def prep(path_or_arr):
    im = Image.open(path_or_arr).convert("RGB").resize((224,224), Image.BICUBIC)
    x = np.asarray(im, dtype=np.float32)/255.0
    x = (x - np.array(MEAN))/np.array(STD)
    return torch.from_numpy(x.transpose(2,0,1)).float()

@torch.no_grad()
def predict(model, paths, bs=8):
    out=[]
    for i in range(0,len(paths),bs):
        batch=torch.stack([prep(p) for p in paths[i:i+bs]]).to(device())
        probs=torch.softmax(model(batch).float(), dim=1).cpu().numpy()
        out.extend(probs)
    return np.array(out)

def calibrate(model):
    """Infer which output index means which class, using Kermany's labelled dirs."""
    names=["CNV","DME","DRUSEN","NORMAL"]
    rows={}
    for n in names:
        fs=sorted(glob.glob(f"{KERMANY}/test/{n}/*.jpeg"))[:24]
        if not fs: print(f"  no Kermany images for {n}"); return None
        rows[n]=predict(model, fs).mean(axis=0)
    print("  mean softmax per true class (rows = truth, cols = output index)")
    print("          " + "".join(f"{i:>9}" for i in range(4)))
    for n in names:
        print(f"  {n:<8}" + "".join(f"{v:>9.3f}" for v in rows[n]))
    order=[None]*4
    for n in names:
        order[int(np.argmax(rows[n]))]=n
    if None in order:
        print("  ambiguous — two classes peak on the same index"); return None
    json.dump(order, open(ORDER,"w"))
    print("  resolved class order:", order)
    return order

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--calibrate", action="store_true")
    ap.add_argument("--n", type=int, default=12)
    ap.add_argument("--write", action="store_true")
    a=ap.parse_args()

    print(f"device: {device()}  — loading RETFound ViT-L (1.2 GB)...")
    model=load_model(); print("model loaded")

    if a.calibrate:
        calibrate(model); return
    if not os.path.exists(ORDER):
        print("no class order yet; calibrating first"); 
        if not calibrate(model): return
    order=json.load(open(ORDER))

    db=connect()
    rows=sample_images(db, a.n, labelled_only=True)
    paths=[resolve(r["path"]) for r in rows]
    keep=[(r,p) for r,p in zip(rows,paths) if p]
    probs=predict(model, [p for _,p in keep])

    print(f"\n{'image':>7}  {'prediction':>10} {'conf':>6}   {'expert IRF/SRF/DRT':>20}   CST")
    print("-"*68)
    vals=[]
    for (r,_),pr in zip(keep,probs):
        k=int(np.argmax(pr)); pred=order[k]
        ex=db.execute("""SELECT MAX(CASE WHEN biomarker='fluid_irf' THEN value END) irf,
                                MAX(CASE WHEN biomarker='fluid_srf' THEN value END) srf,
                                MAX(CASE WHEN biomarker='drt_me'    THEN value END) drt
                         FROM biomarker_values WHERE image_id=? AND source_id=1""",(r["id"],)).fetchone()
        tag=f"{int(ex['irf'] or 0)}/{int(ex['srf'] or 0)}/{int(ex['drt'] or 0)}"
        print(f"{r['id']:>7}  {pred:>10} {pr[k]:>6.3f}   {tag:>20}   {r['cst']:.0f}")
        for i,cls in enumerate(order):
            vals.append((r["id"], f"class_{cls.lower()}", float(pr[i]>=0.5), float(pr[i])))

    if a.write:
        sid=register_source(db, **SOURCE)
        write_values(db, sid, vals)
        print(f"\nwrote {len(vals)} values as source '{SOURCE['key']}' (id {sid})")
    db.close()

if __name__=="__main__":
    main()
