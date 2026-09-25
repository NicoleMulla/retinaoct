"""Shared helpers for biomarker extractors.

Every extractor registers itself as a row in `biomarker_sources` and writes to
`biomarker_values`, so any value in the database can be traced to the expert,
model or algorithm that produced it.
"""
import os, sqlite3
import numpy as np
from PIL import Image

DB   = os.environ.get("OLIVES_DB",   "/Users/nicolemulla/oct-data/olives.db")
ROOT = os.environ.get("OLIVES_ROOT", "/Users/nicolemulla/oct-data/extracted/olives")

def connect(db=DB):
    c = sqlite3.connect(db)
    c.row_factory = sqlite3.Row
    return c

def register_source(db, key, name, kind, version, notes):
    """Insert or update a source row; return its id."""
    db.execute(
        """INSERT INTO biomarker_sources (key,name,kind,version,notes) VALUES (?,?,?,?,?)
           ON CONFLICT(key) DO UPDATE SET name=excluded.name, kind=excluded.kind,
             version=excluded.version, notes=excluded.notes""",
        (key, name, kind, version, notes))
    db.commit()
    return db.execute("SELECT id FROM biomarker_sources WHERE key=?", (key,)).fetchone()["id"]

def write_values(db, source_id, rows):
    """rows: iterable of (image_id, biomarker, value, confidence)"""
    db.executemany(
        """INSERT INTO biomarker_values (image_id,source_id,biomarker,value,confidence)
           VALUES (?,?,?,?,?)
           ON CONFLICT(image_id,source_id,biomarker)
           DO UPDATE SET value=excluded.value, confidence=excluded.confidence""",
        [(r[0], source_id, r[1], float(r[2]), r[3]) for r in rows])
    db.commit()

def resolve(path):
    """Map a stored OLIVES path to a file on disk."""
    rel = path.lstrip("/")
    for pref in ("TREX_DME", "Prime_FULL"):
        f = f"{ROOT}/OLIVES/{pref}/{rel}"
        if os.path.exists(f): return f
    return None

def load_gray(path):
    f = resolve(path)
    if not f: return None
    return np.asarray(Image.open(f).convert("L"), dtype=np.float32)

def sample_images(db, n=20, labelled_only=False, seed=0):
    """A reproducible sample of images, preferring ones with recorded CST."""
    q = ("SELECT id, path, cst, bcva, has_biomarkers FROM images "
         "WHERE cst IS NOT NULL" + (" AND has_biomarkers=1" if labelled_only else "") +
         " ORDER BY (id * 2654435761) % 1000003 LIMIT ?")
    return db.execute(q, (n,)).fetchall()
