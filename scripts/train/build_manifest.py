#!/usr/bin/env python3
"""Export the OLIVES biomarker training manifest with patient-grouped folds.

Reads the expert labels from olives.db (source_id=1) and writes one row per
labelled image: relative path, the 16 binary labels, and grouping keys.

Splits are grouped by patient_id. The 9,408 images come from only 87 patients
at 49 B-scans per volume, so an image-level split would leak the same eye into
both train and test and inflate every metric.

  python3 build_manifest.py                 # write manifest + fold report
  python3 build_manifest.py --folds 5
"""
import argparse, json, os, sqlite3, sys
import numpy as np

DB   = os.environ.get("OLIVES_DB", "/Users/nicolemulla/oct-data/olives.db")
OUT  = os.environ.get("OLIVES_MANIFEST", "/Users/nicolemulla/oct-data/train/manifest.csv")

# Canonical order — fixed here so the model's output columns never drift.
BIOMARKERS = [
    "atrophy_thinning", "dril", "drt_me", "ez_disruption",
    "fluid_irf", "fluid_srf", "ir_hemorrhages", "ir_hrf",
    "ped_serous", "preretinal_tissue", "rpe_disruption", "shrm",
    "vitreous_debris", "vitreous_full", "vitreous_partial", "vmt",
]

# Below this many distinct positive patients a label cannot be validated under a
# patient-grouped split: its positives fall entirely inside one or two folds.
MIN_POS_PATIENTS = 8


def load(db):
    c = sqlite3.connect(db)
    c.row_factory = sqlite3.Row
    cols = ",".join(
        f"MAX(CASE WHEN bv.biomarker='{b}' THEN bv.value END) AS {b}" for b in BIOMARKERS
    )
    rows = c.execute(f"""
        SELECT i.id, i.path, i.patient_id, i.eye_id, i.subject, i.visit, i.eye,
               i.scan_index, i.trial, i.cst, i.bcva, {cols}
        FROM images i JOIN biomarker_values bv ON bv.image_id = i.id
        WHERE i.has_biomarkers = 1 AND bv.source_id = 1
        GROUP BY i.id ORDER BY i.id
    """).fetchall()
    c.close()
    return rows


def grouped_folds(patients, y_by_patient, k, seed=0):
    """Greedy patient-grouped split balancing positives of the rarest usable label.

    GroupKFold assigns by group size alone, which can strand every positive of a
    scarce biomarker in one fold. Sorting patients by positive-count and dealing
    them to the currently-lightest fold keeps rare labels spread.
    """
    rng = np.random.default_rng(seed)
    order = sorted(patients, key=lambda p: (-y_by_patient[p].sum(), rng.random()))
    folds = {p: 0 for p in patients}
    load_ = np.zeros((k, len(BIOMARKERS)))
    count = np.zeros(k)
    for p in order:
        score = load_.sum(axis=1) + count * 0.5
        f = int(np.argmin(score))
        folds[p] = f
        load_[f] += y_by_patient[p]
        count[f] += 1
    return folds


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--out", default=OUT)
    a = ap.parse_args()

    rows = load(DB)
    if not rows:
        sys.exit("no labelled rows found — check OLIVES_DB")

    y = np.array([[float(r[b] or 0) for b in BIOMARKERS] for r in rows])
    pid = np.array([r["patient_id"] for r in rows])
    patients = sorted(set(pid.tolist()))

    y_by_patient = {p: y[pid == p].sum(axis=0) for p in patients}
    pos_patients = np.array(
        [len({p for p in patients if y_by_patient[p][j] > 0}) for j in range(len(BIOMARKERS))]
    )
    usable = pos_patients >= MIN_POS_PATIENTS

    folds = grouped_folds(patients, y_by_patient, a.folds)
    fold_of = np.array([folds[p] for p in pid])

    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w") as f:
        f.write("image_id,path,patient_id,eye_id,visit,scan_index,trial,cst,bcva,fold,"
                + ",".join(BIOMARKERS) + "\n")
        for r, yy, fo in zip(rows, y, fold_of):
            f.write(f"{r['id']},{r['path']},{r['patient_id']},{r['eye_id']},{r['visit']},"
                    f"{r['scan_index']},{r['trial']},{r['cst'] if r['cst'] is not None else ''},"
                    f"{r['bcva'] if r['bcva'] is not None else ''},{fo},"
                    + ",".join(str(int(v)) for v in yy) + "\n")

    meta = dict(biomarkers=BIOMARKERS, usable=[bool(u) for u in usable],
                pos_patients=pos_patients.tolist(),
                pos_counts=y.sum(axis=0).astype(int).tolist(),
                n_images=len(rows), n_patients=len(patients), folds=a.folds,
                min_pos_patients=MIN_POS_PATIENTS)
    json.dump(meta, open(a.out.replace(".csv", "_meta.json"), "w"), indent=2)

    print(f"{len(rows)} images · {len(patients)} patients · {a.folds} folds → {a.out}\n")
    print(f"{'biomarker':<20}{'pos':>7}{'%':>7}{'pts':>6}  {'per-fold positives':<28} usable")
    print("-" * 78)
    for j, b in enumerate(BIOMARKERS):
        per = [int(y[fold_of == k, j].sum()) for k in range(a.folds)]
        flag = "yes" if usable[j] else "NO — too few patients"
        print(f"{b:<20}{int(y[:,j].sum()):>7}{100*y[:,j].mean():>6.2f}%{pos_patients[j]:>6}  "
              f"{str(per):<28} {flag}")
    print("-" * 78)
    print(f"images per fold: {[int((fold_of==k).sum()) for k in range(a.folds)]}")
    print(f"patients per fold: {[sum(1 for p in patients if folds[p]==k) for k in range(a.folds)]}")
    print(f"\n{usable.sum()} of {len(BIOMARKERS)} biomarkers have >= {MIN_POS_PATIENTS} positive patients")


if __name__ == "__main__":
    main()
