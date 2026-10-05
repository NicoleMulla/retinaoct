#!/usr/bin/env python3
"""Check that the numbers in docs/experiments.md still match docs/results/.

A long results document drifts: a table gets edited, an experiment is re-run, a
figure is rounded differently. This recomputes every headline claim from the
versioned data and fails loudly on any mismatch, so the prose cannot quietly
diverge from the evidence.

  python3 scripts/verify_docs.py
"""
import csv, json, statistics as st, sys, os

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
R = lambda *p: os.path.join(ROOT, "docs", "results", *p)
failures = []


def check(label, claimed, actual, tol=0.0005):
    ok = abs(claimed - actual) <= tol
    if not ok: failures.append(label)
    print(f"  {'ok  ' if ok else 'FAIL'} {label:<48} doc={claimed:<10} data={actual:.4f}")


def best_per_fold(path):
    by = {}
    for r in csv.DictReader(open(path)):
        by.setdefault(int(r["fold"]), []).append(float(r["val_mauroc"]))
    return [max(v) for _, v in sorted(by.items())]


print("configurations (best-epoch mAUROC, mean over 5 folds)")
v1 = best_per_fold(R("v1", "curves.csv"))
check("v1 baseline mean", 0.8916, st.fmean(v1))
check("v1 baseline sd", 0.0360, st.stdev(v1), 0.0002)
for name, claimed in [("mae_olives", 0.8905), ("vitL_in", 0.8806),
                      ("vitH_in", 0.8775), ("vitB_in", 0.8716),
                      ("vitL_ret_slices", 0.8508)]:
    check(name, claimed, st.fmean(best_per_fold(R(name, "curves.csv"))))

print("\npaired effects (claimed in §1 and §4)")
L = best_per_fold(R("vitL_in", "curves.csv"))
B = best_per_fold(R("vitB_in", "curves.csv"))
H = best_per_fold(R("vitH_in", "curves.csv"))
M = best_per_fold(R("mae_olives", "curves.csv"))
S = best_per_fold(R("vitL_ret_slices", "curves.csv"))
check("capacity 86M->303M", 0.0090, st.fmean([a-b for a, b in zip(L, B)]))
check("capacity 303M->631M", -0.0031, st.fmean([a-b for a, b in zip(H, L)]))
check("pretraining ImageNet->RETFound", 0.0110, st.fmean([a-b for a, b in zip(v1, L)]))
check("MAE continuation", -0.0010, st.fmean([a-b for a, b in zip(M, v1)]))
check("adjacent slices", -0.0408, st.fmean([a-b for a, b in zip(S, v1)]))

print("\ndataset")
meta = json.load(open(R("manifest_meta.json")))
check("usable biomarkers", 12, sum(meta["usable"]), 0)
check("labelled images", 9408, meta["n_images"], 0)
check("patients", 87, meta["n_patients"], 0)

print("\nheld-out evaluation (§5.3, §5.5, §5.6)")
cs = json.load(open(R("evaluation", "v1_curve_stats.json")))
check("fold-1 images", 1862, cs["n_images"], 0)
check("fold-1 patients", 17, cs["n_patients"], 0)
per = {s["biomarker"]: s for s in cs["per_biomarker"]}
check("shrm AUROC", 0.974, per["shrm"]["auroc"], 0.001)
check("shrm AP", 0.151, per["shrm"]["ap"], 0.001)
check("shrm AUROC-AP gap", 0.823, per["shrm"]["auroc"]-per["shrm"]["ap"], 0.001)

cm = {r["biomarker"]: r for r in csv.DictReader(open(R("evaluation", "v1_confusion_fold1.csv")))}
check("shrm PPV", 0.189, float(cm["shrm"]["ppv"]), 0.001)
check("shrm TP", 7, int(cm["shrm"]["tp"]), 0)
check("shrm FP", 30, int(cm["shrm"]["fp"]), 0)
check("preretinal accuracy", 0.886, float(cm["preretinal_tissue"]["accuracy"]), 0.001)
check("preretinal majority baseline", 0.936, float(cm["preretinal_tissue"]["majority_class_accuracy"]), 0.001)
check("atrophy sensitivity", 0.333, float(cm["atrophy_thinning"]["sensitivity"]), 0.001)
below = [b for b, r in cm.items() if float(r["accuracy_gain_over_majority"]) < 0]
check("biomarkers below majority baseline", 2, len(below), 0)

print("\ndeployment (§6)")
tot = 0
for f, imgs, ood in [("batch1_summary.json", 68875, 1078), ("batch2_summary.json", 74762, 4724)]:
    d = json.load(open(R("deployment", f)))
    check(f"{f.split('_')[0]} images", imgs, d["n_images"], 0)
    check(f"{f.split('_')[0]} out-of-distribution", ood, d["gate_counts"]["out_of_domain"], 0)
    tot += d["n_rows"]
check("total predictions (1.72M)", 1723284, tot, 1)

print(f"\n{'ALL CHECKS PASS' if not failures else 'FAILED: ' + ', '.join(failures)}")
sys.exit(1 if failures else 0)
