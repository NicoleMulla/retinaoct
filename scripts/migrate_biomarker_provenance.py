#!/usr/bin/env python3
"""Add source attribution to biomarker values.

The original schema stored 16 binary columns per image with no indication of
where they came from. Every value is now attributed to a source — the OLIVES
expert annotations, or a named model/algorithm with a version.

  biomarker_sources   one row per annotator or model
  biomarker_values    (image_id, source_id, biomarker) -> value + confidence

The wide `biomarkers` table is kept as a materialised view over the preferred
source, because faceting reads it on every filtered search and D1 bills per
row read (see docs/atlas.md).
"""
import sqlite3, sys

DB = sys.argv[1] if len(sys.argv) > 1 else "/Users/nicolemulla/oct-data/olives.db"
OUT = sys.argv[2] if len(sys.argv) > 2 else "/Users/nicolemulla/oct-data/provenance.sql"

BIO_KEYS = ["atrophy_thinning","ez_disruption","dril","ir_hemorrhages","ir_hrf",
            "vitreous_partial","vitreous_full","preretinal_tissue","vitreous_debris",
            "vmt","drt_me","fluid_irf","fluid_srf","rpe_disruption","ped_serous","shrm"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS biomarker_sources (
  id       INTEGER PRIMARY KEY,
  key      TEXT UNIQUE NOT NULL,   -- 'olives_expert', 'retfound_irf_v1', ...
  name     TEXT NOT NULL,          -- human-readable
  kind     TEXT NOT NULL,          -- 'expert' | 'model' | 'algorithm'
  version  TEXT,
  notes    TEXT
);

CREATE TABLE IF NOT EXISTS biomarker_values (
  image_id   INTEGER NOT NULL,
  source_id  INTEGER NOT NULL,
  biomarker  TEXT    NOT NULL,     -- 'fluid_irf', 'thickness_total_um', ...
  value      REAL    NOT NULL,     -- 0/1 for binary, measurement for continuous
  confidence REAL,                 -- model probability; NULL for expert labels
  PRIMARY KEY (image_id, source_id, biomarker)
);

CREATE INDEX IF NOT EXISTS idx_bv_image  ON biomarker_values(image_id);
CREATE INDEX IF NOT EXISTS idx_bv_source ON biomarker_values(source_id, biomarker);
"""

SOURCES = [
    (1, "olives_expert", "OLIVES expert annotation", "expert", "2022",
     "16 binary biomarkers labelled by clinicians; shipped with the dataset (CC BY 4.0)"),
]

def main():
    db = sqlite3.connect(DB)
    db.executescript(SCHEMA)
    db.executemany("INSERT OR REPLACE INTO biomarker_sources VALUES (?,?,?,?,?,?)", SOURCES)

    existing = db.execute("SELECT COUNT(*) FROM biomarker_values WHERE source_id=1").fetchone()[0]
    if existing:
        print(f"olives_expert already migrated ({existing:,} values)")
    else:
        rows = db.execute(f"SELECT image_id, {','.join(BIO_KEYS)} FROM biomarkers").fetchall()
        vals = [(r[0], 1, k, float(r[i+1]), None)
                for r in rows for i, k in enumerate(BIO_KEYS)]
        db.executemany("INSERT INTO biomarker_values VALUES (?,?,?,?,?)", vals)
        print(f"migrated {len(rows):,} images x {len(BIO_KEYS)} biomarkers = {len(vals):,} values")
    db.commit()

    c = db.cursor()
    print("\nsources:")
    for r in c.execute("SELECT id,key,name,kind FROM biomarker_sources"):
        n = c.execute("SELECT COUNT(*) FROM biomarker_values WHERE source_id=?", (r[0],)).fetchone()[0]
        print(f"  [{r[0]}] {r[1]:<22} {r[3]:<10} {n:>9,} values   {r[2]}")
    print(f"\ntotal values: {c.execute('SELECT COUNT(*) FROM biomarker_values').fetchone()[0]:,}")
    print("positive    :", f"{c.execute('SELECT COUNT(*) FROM biomarker_values WHERE value=1').fetchone()[0]:,}")

    # emit the same thing as SQL for D1
    with open(OUT, "w") as f:
        f.write(SCHEMA)
        for s in SOURCES:
            f.write("INSERT OR REPLACE INTO biomarker_sources VALUES ({});\n".format(
                ",".join("NULL" if x is None else (str(x) if isinstance(x,int) else "'"+str(x).replace("'","''")+"'") for x in s)))
        f.write("DELETE FROM biomarker_values WHERE source_id=1;\n")
        rows = c.execute("SELECT image_id, biomarker, value FROM biomarker_values WHERE source_id=1").fetchall()
        for i in range(0, len(rows), 500):
            chunk = rows[i:i+500]
            f.write("INSERT INTO biomarker_values (image_id,source_id,biomarker,value,confidence) VALUES "
                    + ",".join(f"({r[0]},1,'{r[1]}',{r[2]},NULL)" for r in chunk) + ";\n")
    print(f"\nwrote {OUT}")
    db.close()

if __name__ == "__main__":
    main()
