#!/usr/bin/env python3
"""Build a SQLite index of the OLIVES dataset for shipping to Cloudflare D1.

Sources:
  Clinical_Data_Images.xlsx          78,185 images: BCVA, CST, patient, eye
  Biomarker_Clinical_Data_Images.csv  9,408 images: 16 expert biomarkers
  OCT-DR.xlsx                        patient-level demographics (PRIME)

Output: olives.db  (tables: images, biomarkers, patients)
"""
import os, re, sqlite3, sys, warnings
import pandas as pd
warnings.filterwarnings("ignore")

ROOT = "/Users/nicolemulla/oct-data/extracted/olives"
LAB  = f"{ROOT}/OLIVES_Dataset_Labels/full_labels"
OUT  = sys.argv[1] if len(sys.argv) > 1 else "/Users/nicolemulla/oct-data/olives.db"

# 16 biomarker columns, CSV header -> short key
BIOMARKERS = [
    ("Atrophy / thinning of retinal layers", "atrophy_thinning"),
    ("Disruption of EZ",                     "ez_disruption"),
    ("DRIL",                                 "dril"),
    ("IR hemorrhages",                       "ir_hemorrhages"),
    ("IR HRF",                               "ir_hrf"),
    ("Partially attached vitreous face",     "vitreous_partial"),
    ("Fully attached vitreous face",         "vitreous_full"),
    ("Preretinal tissue/hemorrhage",         "preretinal_tissue"),
    ("Vitreous debris",                      "vitreous_debris"),
    ("VMT",                                  "vmt"),
    ("DRT/ME",                               "drt_me"),
    ("Fluid (IRF)",                          "fluid_irf"),
    ("Fluid (SRF)",                          "fluid_srf"),
    ("Disruption of RPE",                    "rpe_disruption"),
    ("PED (serous)",                         "ped_serous"),
    ("SHRM",                                 "shrm"),
]

def parse_path(p):
    """/TREX DME/GILA/0234GOD/V1/OD/x.tif  or  /Prime_FULL/01-001/W0/OS/27.png"""
    parts = p.strip("/").split("/")
    if not parts: return {}
    trial = "TREX_DME" if parts[0].upper().startswith("TREX") else "PRIME"
    if trial == "TREX_DME" and len(parts) >= 6:
        arm, subject, visit, eye, fn = parts[1], parts[2], parts[3], parts[4], parts[-1]
    elif len(parts) >= 5:
        arm, subject, visit, eye, fn = None, parts[1], parts[2], parts[3], parts[-1]
    else:
        return {"trial": trial, "file_name": parts[-1]}
    m = re.search(r"(\d+)", os.path.splitext(fn)[0])
    return {"trial": trial, "arm": arm, "subject": subject, "visit": visit,
            "eye": eye if eye in ("OD", "OS") else None,
            "file_name": fn, "scan_index": int(m.group(1)) if m else None}

def main():
    print("reading sources...")
    clin = pd.read_excel(f"{LAB}/Clinical_Data_Images.xlsx")
    bio  = pd.read_csv(f"{LAB}/Biomarker_Clinical_Data_Images.csv")
    bpath = bio.columns[0]
    print(f"  clinical {len(clin):,}   biomarker {len(bio):,}")

    # union of all known image paths
    rows = {}
    for r in clin.itertuples(index=False):
        rows[r.File_Path] = dict(path=r.File_Path, bcva=r.BCVA, cst=r.CST,
                                 eye_id=r.Eye_ID, patient_id=r.Patient_ID)
    for r in bio.to_dict("records"):
        p = r[bpath]
        d = rows.setdefault(p, dict(path=p, bcva=None, cst=None,
                                    eye_id=None, patient_id=None))
        if d.get("bcva") is None: d["bcva"] = r.get("BCVA")
        if d.get("cst")  is None: d["cst"]  = r.get("CST")
        if d.get("eye_id") is None: d["eye_id"] = r.get("Eye_ID")
        if d.get("patient_id") is None: d["patient_id"] = r.get("Patient_ID")

    bio_by_path = {r[bpath]: r for r in bio.to_dict("records")}

    if os.path.exists(OUT): os.remove(OUT)
    db = sqlite3.connect(OUT)
    db.executescript("""
    PRAGMA journal_mode=MEMORY;
    CREATE TABLE images (
      id INTEGER PRIMARY KEY, path TEXT UNIQUE NOT NULL,
      trial TEXT, arm TEXT, subject TEXT, visit TEXT, eye TEXT,
      scan_index INTEGER, file_name TEXT,
      patient_id INTEGER, eye_id INTEGER,
      bcva REAL, cst REAL,
      has_biomarkers INTEGER NOT NULL DEFAULT 0,
      biomarker_count INTEGER NOT NULL DEFAULT 0,
      thumb_key TEXT, full_key TEXT
    );
    CREATE TABLE biomarkers (
      image_id INTEGER PRIMARY KEY REFERENCES images(id),
      """ + ",\n      ".join(f"{k} INTEGER NOT NULL DEFAULT 0" for _, k in BIOMARKERS) + """
    );
    CREATE TABLE patients (
      patient_id TEXT PRIMARY KEY, trial TEXT, treatment_arm TEXT, study_eye TEXT,
      age REAL, gender TEXT, ethnicity TEXT, race TEXT,
      diabetes_type TEXT, years_diabetes REAL, hba1c_baseline REAL,
      bmi REAL, drss TEXT, leakage_index REAL
    );
    """)

    img_rows, bio_rows, next_id = [], [], 1
    for p, d in rows.items():
        meta = parse_path(p)
        stem = os.path.splitext(p.strip("/"))[0]
        b = bio_by_path.get(p)
        flags = [int(b[c]) if b and pd.notna(b.get(c)) else 0 for c, _ in BIOMARKERS] if b else None
        img_rows.append((next_id, p, meta.get("trial"), meta.get("arm"), meta.get("subject"),
                         meta.get("visit"), meta.get("eye"), meta.get("scan_index"),
                         meta.get("file_name"),
                         int(d["patient_id"]) if pd.notna(d.get("patient_id")) else None,
                         int(d["eye_id"]) if pd.notna(d.get("eye_id")) else None,
                         float(d["bcva"]) if pd.notna(d.get("bcva")) else None,
                         float(d["cst"]) if pd.notna(d.get("cst")) else None,
                         1 if b else 0, sum(flags) if flags else 0,
                         f"web/olives/thumb/{stem}.webp", f"web/olives/full/{stem}.webp"))
        if flags: bio_rows.append(tuple([next_id] + flags))
        next_id += 1

    db.executemany(f"INSERT INTO images VALUES ({','.join('?'*17)})", img_rows)
    db.executemany(f"INSERT INTO biomarkers VALUES ({','.join('?'*(len(BIOMARKERS)+1))})", bio_rows)

    # patient demographics (PRIME / OCT-DR)
    try:
        dr = pd.read_excel(f"{LAB}/OCT-DR.xlsx", header=1)
        dr.columns = [re.sub(r"\s+", " ", str(c)).strip() for c in dr.columns]
        def col(*names):
            for n in names:
                for c in dr.columns:
                    if n.lower() in c.lower(): return c
            return None
        cid = col("Patient ID")
        if cid:
            prows = []
            for r in dr.itertuples(index=False):
                g = lambda c: (getattr(r, dr.columns.get_loc(c) and "_"+str(dr.columns.get_loc(c)+1), None) if c else None)
                d = dict(zip(dr.columns, r))
                pid = d.get(cid)
                if pid is None or str(pid).strip() in ("", "nan"): continue
                def v(*n):
                    c = col(*n); x = d.get(c) if c else None
                    return None if (x is None or str(x).strip() in ("", "nan")) else x
                prows.append((str(pid).strip(), "PRIME", str(v("Treatment Arm") or ""),
                              str(v("Study Eye") or ""),
                              pd.to_numeric(v("Age"), errors="coerce"),
                              str(v("Gender") or ""), str(v("Ethnicity") or ""), str(v("Race") or ""),
                              str(v("Type of Diab") or ""),
                              pd.to_numeric(v("Number of Year"), errors="coerce"),
                              pd.to_numeric(v("Baseline HbA1c"), errors="coerce"),
                              pd.to_numeric(v("BMI"), errors="coerce"),
                              str(v("DRSS") or ""),
                              pd.to_numeric(v("Leakage Index"), errors="coerce")))
            db.executemany(f"INSERT OR REPLACE INTO patients VALUES ({','.join('?'*14)})", prows)
            print(f"  patients: {len(prows)}")
    except Exception as e:
        print(f"  patients: skipped ({e})")

    db.executescript("""
    CREATE INDEX idx_img_trial ON images(trial);
    CREATE INDEX idx_img_eye ON images(eye);
    CREATE INDEX idx_img_patient ON images(patient_id);
    CREATE INDEX idx_img_eyeid ON images(eye_id);
    CREATE INDEX idx_img_visit ON images(visit);
    CREATE INDEX idx_img_hasbio ON images(has_biomarkers);
    CREATE INDEX idx_img_bcva ON images(bcva);
    CREATE INDEX idx_img_cst ON images(cst);
    """)
    db.commit()

    c = db.cursor()
    print("\n=== built ===")
    for t in ("images", "biomarkers", "patients"):
        print(f"  {t:12} {c.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]:,}")
    print("\n  by trial:", dict(c.execute("SELECT trial,COUNT(*) FROM images GROUP BY trial").fetchall()))
    print("  by eye  :", dict(c.execute("SELECT eye,COUNT(*) FROM images GROUP BY eye").fetchall()))
    print("\n  biomarker prevalence:")
    for label, k in BIOMARKERS:
        n = c.execute(f"SELECT SUM({k}) FROM biomarkers").fetchone()[0] or 0
        print(f"    {label:40.40} {n:5,}")
    db.close()
    print(f"\nwrote {OUT} ({os.path.getsize(OUT)/1e6:.1f} MB)")

if __name__ == "__main__":
    main()
