#!/usr/bin/env python3
"""Push the trained model and serving artefacts to a HuggingFace repo.

Creates the repo PRIVATE by default. This is a medical-prediction model under a
non-commercial licence trained on 87 patients — publishing is a deliberate act,
not a default, so --public must be passed explicitly.

  python3 push_to_hf.py --src serving/ --repo NicoleMulla/retfound-olives-16bm
  python3 push_to_hf.py --src serving/ --repo ... --public   # opt in
"""
import argparse, json, os, sys

TEMPLATE = """---
license: cc-by-nc-4.0
tags: [oct, retina, biomarkers, retfound, multi-label, vision-transformer]
library_name: timm
---

# RETFound / OLIVES — 16 retinal biomarkers

ViT-L/16 [RETFound]({enc}) encoder fine-tuned on the OLIVES dataset for
multi-label prediction of 16 OCT biomarkers. Sixteen independent sigmoids, not
a softmax — biomarkers co-occur.

## Results

{table}

Mean AUROC across usable biomarkers: **{mean:.4f}** ({nfolds}-fold, patient-grouped).

## Important limitations

**Not all 16 biomarkers are usable.** Four have too few positive patients in the
training data to learn or validate: {suppressed}. The serving handler suppresses
them rather than emitting fabricated probabilities.

**AUROC flatters the rare labels.** Read average precision (AP) alongside it —
a biomarker at 2% prevalence can score high AUROC while being near-useless in
practice.

**Trained on 87 patients / 96 eyes** (9,408 labelled B-scans, 49 per volume),
all Spectralis, all from the PRIME and TREX-DME trials. Effective sample size is
closer to 96 than 9,408.

**Out-of-distribution input.** Predictions on non-Spectralis OCT, or on anything
that is not an OCT B-scan, are unvalidated. `handler.py` gates inputs on
Mahalanobis distance in encoder-embedding space; use it.

## Input

504x496 grayscale OCT B-scan -> RGB -> 224x224, ImageNet mean/std.
Wide-aspect scans must be centre-cropped square first, never squashed.

## Licence

CC-BY-NC-4.0, inherited from RETFound. **Non-commercial use only.**

## Not a medical device

Research use only. Not for diagnostic use.
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="directory with model + config")
    ap.add_argument("--repo", required=True)
    ap.add_argument("--public", action="store_true", help="publish publicly (default: private)")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    tok = os.environ.get("HF_TOKEN")
    if not tok: sys.exit("HF_TOKEN not set — run under 'doppler run --'")

    cfgp = os.path.join(a.src, "serving_config.json")
    cfg = json.load(open(cfgp)) if os.path.exists(cfgp) else {}
    xf = cfg.get("cross_fold", [])
    if xf:
        table = ("| biomarker | AUROC | sd | AP |\n|---|---:|---:|---:|\n" +
                 "\n".join(f"| {r['biomarker']} | {r['auroc_mean']:.3f} | "
                           f"{r['auroc_sd']:.3f} | {r['ap_mean']:.3f} |" for r in xf))
    else:
        table = "_see final_metrics.csv_"
    sup = ", ".join(f"`{b}`" for b, u in zip(cfg.get("biomarkers", []), cfg.get("usable", [])) if not u) or "none"

    card = TEMPLATE.format(enc=cfg.get("encoder", "bitfount/RETFound_MAE_OCT"),
                           table=table, mean=cfg.get("mauroc") or 0.0,
                           nfolds=cfg.get("n_folds", 5), suppressed=sup)
    open(os.path.join(a.src, "README.md"), "w").write(card)

    files = sorted(os.listdir(a.src))
    print(f"repo     {a.repo}")
    print(f"privacy  {'PUBLIC' if a.public else 'private'}")
    print(f"files    {files}")
    if a.dry_run:
        print("\n(dry run — nothing uploaded)"); return

    from huggingface_hub import HfApi
    api = HfApi(token=tok)
    api.create_repo(a.repo, private=not a.public, exist_ok=True, repo_type="model")
    api.upload_folder(folder_path=a.src, repo_id=a.repo, repo_type="model",
                      commit_message="RETFound/OLIVES 16-biomarker multi-label model")
    print(f"\nhttps://huggingface.co/{a.repo}")


if __name__ == "__main__":
    main()
