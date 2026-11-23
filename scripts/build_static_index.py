#!/usr/bin/env python3
"""Pack the searchable corpus into one static file the browser holds in memory.

    python3 scripts/build_static_index.py <sqlite-db> [out.json]

Why. The corpus is static — 153,045 rows that never change — yet every filter
click recomputed aggregates over all of them in D1, which bills per row read.
A filtered search cost ~460,000 reads against a 5,000,000 daily allowance, so
roughly a dozen searches took the site down. Scanning a fixed dataset at query
time was the wrong shape; shipping it once is the right one.

It fits because the data is almost entirely enumerated: 2 trials, 4 arms, 96
subjects, 48 visits, 2 eyes. Everything except the path packs into a few
integers per row, and the whole thing gzips to ~580 KB — smaller than two of
the OCT images on the page, downloaded once and cached at the edge.

Not included: per-biomarker model confidences (another ~1.2 MB) and patient
demographics. Those are only needed once a detail panel is open, and the
panel still asks D1 for them — a handful of rows, which the allowance can
absorb in a way that full scans never could.

Get a fresh database to build from without spending read quota:
    npx wrangler d1 export retinaoct-olives --remote --output full.sql
    sqlite3 live.db < full.sql
Export is a backup operation and is not metered as row reads, which is what
makes this recoverable even with the allowance already exhausted.
"""
import json
import pathlib
import re
import sqlite3
import sys

BM = ["fluid_irf", "fluid_srf", "ir_hrf", "drt_me", "ez_disruption", "dril",
      "ir_hemorrhages", "atrophy_thinning", "rpe_disruption", "ped_serous",
      "shrm", "preretinal_tissue", "vitreous_partial", "vitreous_full",
      "vitreous_debris", "vmt"]
SOURCES = ["", "expert", "model", "rejected"]


def main():
    db = sqlite3.connect(sys.argv[1])
    out = pathlib.Path(sys.argv[2] if len(sys.argv) > 2 else "public/data/corpus.json")
    out.parent.mkdir(parents=True, exist_ok=True)

    rows = db.execute(f"""
        SELECT i.id, i.trial, COALESCE(i.arm,''), COALESCE(i.subject,''),
               COALESCE(i.visit,''), COALESCE(i.eye,''), i.path, i.bcva, i.cst,
               i.biomarker_count, COALESCE(i.label_source,''), i.patient_id, i.eye_id,
               i.thumb_key, {','.join('COALESCE(b.'+k+',0)' for k in BM)}
        FROM images i LEFT JOIN biomarkers b ON b.image_id = i.id
        ORDER BY i.id""").fetchall()

    if [r[0] for r in rows] != list(range(1, len(rows) + 1)):
        sys.exit("ids are not contiguous 1..N; the client indexes by position")

    enum = lambda vals: sorted({v for v in vals})
    trial, arm = enum(r[1] for r in rows), enum(r[2] for r in rows)
    sub, visit = enum(r[3] for r in rows), enum(r[4] for r in rows)
    eye = enum(r[5] for r in rows)
    ix = lambda L: {v: i for i, v in enumerate(L)}
    ti, ai, si, vi, ei = ix(trial), ix(arm), ix(sub), ix(visit), ix(eye)
    if len(arm) > 8 or len(visit) > 64 or len(sub) > 512:
        sys.exit("an enumerated field outgrew its bit field in `pk`")

    # thumb_key and full_key are mechanically derivable from the path: swap the
    # prefix and replace whatever extension it has with .webp. Paths carry
    # spaces that the keys do not. Checked against every row rather than
    # assumed — an earlier version of this derivation was wrong for 4,900 rows
    # that are .jpg rather than .tif.
    def key(path, kind):
        return re.sub(r"\.[^./]+$", ".webp", f"web/olives/{kind}" + path.replace(" ", "_"))
    bad = [r[0] for r in rows if key(r[6], "thumb") != r[13]]
    if bad:
        sys.exit(f"thumb_key is not derivable for {len(bad)} rows, e.g. id {bad[0]}")

    flags, pk, bc, bcva, cst, eye_id, paths = [], [], [], [], [], [], []
    for r in rows:
        f = 0
        for b, k in enumerate(BM):
            if r[14 + b]:
                f |= 1 << b
        flags.append(f)
        # trial:1 | eye:1 | source:2 | visit:6 | arm:3 | subject:9
        pk.append(ti[r[1]] | (ei[r[5]] << 1) | (SOURCES.index(r[10]) << 2)
                  | (vi[r[4]] << 4) | (ai[r[2]] << 10) | (si[r[3]] << 13))
        bc.append(r[9] or 0)
        bcva.append(0 if r[7] is None else int(round(r[7])))
        cst.append(0 if r[8] is None else int(round(r[8])))
        eye_id.append(r[12] or 0)
        paths.append(r[6])

    doc = {"n": len(rows), "trial": trial, "arm": arm, "subject": sub, "visit": visit,
           "eye": eye, "sources": SOURCES, "biomarkers": BM,
           "flags": flags, "pk": pk, "bc": bc, "bcva": bcva, "cst": cst,
           "eye_id": eye_id, "paths": paths}
    out.write_text(json.dumps(doc, separators=(",", ":")))
    print(f"  {out}  {out.stat().st_size / 1e6:.2f} MB raw ({len(rows):,} images)")


if __name__ == "__main__":
    main()
