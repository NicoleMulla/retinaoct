#!/usr/bin/env python3
"""Index the OLIVES B-scans that the label spreadsheets never mentioned.

build_olives_index.py takes its image list from Clinical_Data_Images.xlsx
(78,185 rows) unioned with the biomarker CSV, which yields 78,283 images. The
archive actually holds ~161,000 image files, so roughly 78,000 B-scans were
never indexed — they carry no BCVA, CST or biomarker labels, only what the path
encodes.

They are still real Spectralis B-scans of the same 96 eyes, so they belong in
the archive. Rows are added with bcva/cst NULL and patient_id/eye_id carried
over from the same subject+eye where the index already knows them.

Only 504x496 images are accepted. Fundus photographs and other sizes are
en-face or derived products, not B-scans, and the biomarker model is not
meaningful on them.

  python3 extend_olives_index.py --keep /tmp/keep_rel.txt [--apply]
"""
import argparse, os, re, sqlite3, sys

DB = os.environ.get("OLIVES_DB", "/Users/nicolemulla/oct-data/olives.db")


def parse_path(p):
    """Mirror of build_olives_index.parse_path, so new rows match existing ones."""
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


def keys(db_path):
    """web/olives/{thumb,full}/<path>.webp — spaces become underscores, as the
    existing rows do (TREX paths contain spaces)."""
    stem = os.path.splitext(db_path.lstrip("/"))[0].replace(" ", "_")
    return f"web/olives/thumb/{stem}.webp", f"web/olives/full/{stem}.webp"


def person_key(trial, subject):
    """Patient identity.

    TREX subject folders are named for the *enrolled study eye* — 0201GOD is
    person 0201, arm G, study eye OD — and the same person appears under more
    than one code (0201GOD and 0201TOS both map to patient_id 201). The numeric
    prefix is the person. PRIME subject codes are already per-person.
    """
    if trial == "TREX_DME":
        m = re.match(r"(\d+)", subject or "")
        return ("TREX", m.group(1).lstrip("0") or "0") if m else None
    return ("PRIME", subject)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", required=True, help="file of archive-relative paths to add")
    ap.add_argument("--apply", action="store_true", help="write; otherwise dry run")
    a = ap.parse_args()

    db = sqlite3.connect(DB); db.row_factory = sqlite3.Row
    existing = {r["path"] for r in db.execute("SELECT path FROM images")}

    # person -> patient_id, and (patient_id, eye) -> eye_id. An eye is identified
    # by person + laterality, not by subject folder: 0201GOD/OS and 0201TOS/OS are
    # the same physical eye scanned under two study codes.
    pid_of, eye_of = {}, {}
    for r in db.execute("""SELECT trial, subject, eye, patient_id, eye_id FROM images
                           WHERE patient_id IS NOT NULL GROUP BY subject, eye"""):
        k = person_key(r["trial"], r["subject"])
        if k: pid_of.setdefault(k, r["patient_id"])
        if r["eye_id"] is not None:
            eye_of.setdefault((r["patient_id"], r["eye"]), r["eye_id"])
    next_eye = (db.execute("SELECT MAX(eye_id) m FROM images").fetchone()["m"] or 0) + 1
    print(f"index has {len(existing):,} images · {len(pid_of)} persons · "
          f"{len(eye_of)} eyes · next eye_id {next_eye}")

    rows, skipped, no_pid, new_eyes = [], 0, 0, {}
    for line in open(a.keep):
        rel = line.rstrip("\n")
        if not rel: continue
        db_path = "/" + rel
        if db_path in existing: skipped += 1; continue
        d = parse_path(db_path)
        if not d.get("subject") or not d.get("eye"): skipped += 1; continue

        pk = person_key(d["trial"], d["subject"])
        pid = pid_of.get(pk)
        if pid is None: no_pid += 1
        eid = eye_of.get((pid, d["eye"])) if pid is not None else None
        if eid is None and pid is not None:
            key = (pid, d["eye"])
            if key not in new_eyes:
                new_eyes[key] = next_eye; next_eye += 1
            eid = new_eyes[key]

        t, f = keys(db_path)
        rows.append((db_path, d["trial"], d.get("arm"), d["subject"], d["visit"],
                     d["eye"], d.get("scan_index"), d["file_name"], pid, eid,
                     None, None, 0, 0, t, f))

    print(f"to add {len(rows):,}   already present {skipped:,}   "
          f"without patient id {no_pid:,}   new eye_ids allocated {len(new_eyes)}")
    if rows: print("sample:", rows[0][0], "-> pid", rows[0][8], "eye_id", rows[0][9])
    if not a.apply:
        print("\n(dry run — pass --apply to write)"); return

    db.executemany("""INSERT OR IGNORE INTO images
        (path,trial,arm,subject,visit,eye,scan_index,file_name,patient_id,eye_id,
         bcva,cst,has_biomarkers,biomarker_count,thumb_key,full_key)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", rows)
    db.commit()
    n = db.execute("SELECT COUNT(*) c FROM images").fetchone()["c"]
    print(f"\nindex now holds {n:,} images")
    db.close()


if __name__ == "__main__":
    main()
