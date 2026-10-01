#!/usr/bin/env python3
"""Parse the per-fold training logs into tidy CSVs plus a plot.

The training loop prints one line per epoch and a per-biomarker table at the
end; this turns both into something you can chart or diff later, without
needing the GPU box to still exist.

  python3 collect_curves.py --logs runs_logs/ --out runs_logs/
"""
import argparse, csv, glob, json, os, re

EPOCH = re.compile(r"ep\s+(\d+)/(\d+)\s+loss\s+([\d.]+)\s+mAUROC\(usable\)\s+([\d.nan]+)\s+(\d+)s")
ROW   = re.compile(r"^(\w+)\s+([\d.]+|nan)\s+([\d.]+|nan)\s+([\d.]+|nan)\s+([\d.]+)\s+(yes|NO)\s*$")
MEAN  = re.compile(r"mean AUROC over (\d+) usable biomarkers:\s+([\d.]+)")
SPLIT = re.compile(r"train (\d+) / val (\d+) images")
PATS  = re.compile(r"train patients (\d+) · val patients (\d+) · overlap (\d+)")


def num(s):
    try: return float(s)
    except ValueError: return float("nan")


def parse(path):
    fold = re.search(r"fold(\d+)", os.path.basename(path))
    fold = int(fold.group(1)) if fold else -1
    epochs, finals, meta = [], [], {"fold": fold}
    for line in open(path):
        m = EPOCH.search(line)
        if m:
            epochs.append(dict(fold=fold, epoch=int(m.group(1)), total_epochs=int(m.group(2)),
                               train_loss=num(m.group(3)), val_mauroc=num(m.group(4)),
                               seconds=int(m.group(5))))
            continue
        m = ROW.match(line.strip())
        if m:
            finals.append(dict(fold=fold, biomarker=m.group(1), auroc=num(m.group(2)),
                               ap=num(m.group(3)), f1=num(m.group(4)),
                               threshold=num(m.group(5)), usable=(m.group(6) == "yes")))
            continue
        m = MEAN.search(line)
        if m: meta["mean_auroc"] = float(m.group(2)); meta["n_usable"] = int(m.group(1))
        m = SPLIT.search(line)
        if m: meta["n_train"], meta["n_val"] = int(m.group(1)), int(m.group(2))
        m = PATS.search(line)
        if m:
            meta["train_patients"], meta["val_patients"] = int(m.group(1)), int(m.group(2))
            meta["patient_overlap"] = int(m.group(3))
    return epochs, finals, meta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--logs", default="runs_logs")
    ap.add_argument("--out", default="runs_logs")
    a = ap.parse_args()

    files = sorted(glob.glob(os.path.join(a.logs, "train_fold*.log")))
    if not files: raise SystemExit(f"no train_fold*.log under {a.logs}")

    all_ep, all_fin, all_meta = [], [], []
    for f in files:
        e, fi, me = parse(f)
        all_ep += e; all_fin += fi; all_meta.append(me)
        print(f"  {os.path.basename(f):<22} {len(e):>3} epochs, {len(fi):>2} biomarker rows, "
              f"mean AUROC {me.get('mean_auroc','--')}")

    os.makedirs(a.out, exist_ok=True)
    with open(f"{a.out}/curves.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["fold","epoch","total_epochs","train_loss","val_mauroc","seconds"])
        w.writeheader(); w.writerows(all_ep)
    with open(f"{a.out}/final_metrics.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["fold","biomarker","auroc","ap","f1","threshold","usable"])
        w.writeheader(); w.writerows(all_fin)
    json.dump(all_meta, open(f"{a.out}/fold_summary.json","w"), indent=2)
    print(f"\nwrote curves.csv ({len(all_ep)} rows), final_metrics.csv ({len(all_fin)} rows), fold_summary.json")

    # Cross-fold aggregate — the spread matters more than any single fold.
    import statistics as st
    by = {}
    for r in all_fin:
        if r["usable"]: by.setdefault(r["biomarker"], []).append(r)
    if by:
        print(f"\n{'biomarker':<20}{'AUROC mean':>12}{'sd':>8}{'AP mean':>10}{'folds':>7}")
        print("-"*57)
        rows=[]
        for b, rs in sorted(by.items(), key=lambda kv: -st.fmean([x['auroc'] for x in kv[1] if x['auroc']==x['auroc']] or [0])):
            au=[x["auroc"] for x in rs if x["auroc"]==x["auroc"]]
            aps=[x["ap"] for x in rs if x["ap"]==x["ap"]]
            if not au: continue
            sd = st.stdev(au) if len(au)>1 else 0.0
            print(f"{b:<20}{st.fmean(au):>12.3f}{sd:>8.3f}{st.fmean(aps):>10.3f}{len(au):>7}")
            rows.append(dict(biomarker=b, auroc_mean=round(st.fmean(au),4), auroc_sd=round(sd,4),
                             ap_mean=round(st.fmean(aps),4), n_folds=len(au)))
        with open(f"{a.out}/cross_fold.csv","w",newline="") as fh:
            w=csv.DictWriter(fh,fieldnames=["biomarker","auroc_mean","auroc_sd","ap_mean","n_folds"])
            w.writeheader(); w.writerows(rows)
        print(f"\nwrote cross_fold.csv")

    # Plot only if matplotlib is around; the CSVs are the real artefact.
    try:
        import matplotlib; matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4.5))
        for fold in sorted({r["fold"] for r in all_ep}):
            rs = [r for r in all_ep if r["fold"] == fold]
            xs = [r["epoch"] for r in rs]
            ax1.plot(xs, [r["train_loss"] for r in rs], label=f"fold {fold}")
            ax2.plot(xs, [r["val_mauroc"] for r in rs], label=f"fold {fold}")
        ax1.set_xlabel("epoch"); ax1.set_ylabel("train loss (BCE)"); ax1.set_title("Training loss")
        ax2.set_xlabel("epoch"); ax2.set_ylabel("val mAUROC (12 usable)"); ax2.set_title("Validation mAUROC")
        ax1.grid(alpha=.3); ax2.grid(alpha=.3); ax1.legend(); ax2.legend()
        fig.tight_layout(); fig.savefig(f"{a.out}/curves.png", dpi=130)
        print(f"wrote curves.png")
    except ImportError:
        print("(matplotlib not installed — skipped curves.png)")


if __name__ == "__main__":
    main()
