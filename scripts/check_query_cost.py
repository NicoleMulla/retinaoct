#!/usr/bin/env python3
"""Show what every query the site runs will actually cost.

    python3 scripts/check_query_cost.py [sqlite-db]

WHY THIS EXISTS — read before touching any SQL in this repo.

The daily D1 read allowance has been exhausted FIVE times, every time for the
same underlying reason, and every time it was found by the site going down
rather than by anyone checking:

  976571d  facets recomputed per request
  2abef40  idx_img_sort_default missing, so every page load sorted 153,045 rows
  06d6f5e  three separate leaks: unindexed ORDER BY, no edge cache, four scans
  f16d480  a filtered search still running three full scans
  583f18d  LIKE '%term%' and negated biomarkers, 9,128,605 reads in one day

The single mistake behind all five: judging a query by how many rows it
RETURNS instead of how many it READS. D1 bills rows scanned. `LIMIT 24` costs
nothing off the bill. A WHERE clause costs nothing off the bill unless an
index can actually use it. 24 rows on screen can be 153,045 rows charged.

Patterns that always scan, none of which look expensive:

  WHERE col = 1                 no index on col
  WHERE a = ? ORDER BY b, c     index covers a but not the sort, so every
                                match is read and sorted before the LIMIT
  WHERE col LIKE '%x%'          leading wildcard, never indexable
  WHERE COALESCE(col,0) = 0     negation; a partial index covers the rows
  WHERE col NOT IN (...)        that are SET, which is the complement
  COUNT/SUM/GROUP BY over a filtered subset — always reads the whole subset
  any endpoint without an edge cache — pays again on every single view

So: before adding or editing a query, run this to see its plan, then get the
real figure from D1's own `rows_read` via ?debug=1 on a preview deploy. EXPLAIN
alone is not a verdict — it calls the default sort a SCAN though the index
stops it at 24 rows, and calls a negated biomarker a covering-index scan though
it reads every row. Only D1's own number settles it.
"""
import pathlib
import re
import sqlite3
import sys

# Representative shapes of every query the Functions actually run, with the
# bindings filled in. Keep in step with functions/api/*.js.
QUERIES = [
    ("search: default sort page 1", """
        SELECT i.id, i.thumb_key FROM images i
        ORDER BY i.has_biomarkers DESC, i.biomarker_count DESC, i.id LIMIT 24"""),
    ("search: global facets", "SELECT payload FROM facets_global WHERE id=1"),
    ("search: filter by trial", """
        SELECT i.id FROM images i WHERE i.trial = 'PRIME'
        ORDER BY i.has_biomarkers DESC, i.biomarker_count DESC, i.id LIMIT 24"""),
    ("search: filter by biomarker", """
        SELECT i.id FROM images i JOIN biomarkers b ON b.image_id = i.id
        WHERE b.drt_me = 1
        ORDER BY i.has_biomarkers DESC, i.biomarker_count DESC, i.id LIMIT 24"""),
    ("search: NEGATED biomarker", """
        SELECT i.id FROM images i JOIN biomarkers b ON b.image_id = i.id
        WHERE COALESCE(b.ir_hrf,0) = 0
        ORDER BY i.has_biomarkers DESC, i.biomarker_count DESC, i.id LIMIT 24"""),
    ("search: TEXT search", """
        SELECT i.id FROM images i WHERE i.path LIKE '%0209%'
        ORDER BY i.has_biomarkers DESC, i.biomarker_count DESC, i.id LIMIT 24"""),
    ("search: merged aggregates", """
        SELECT i.trial, i.eye, i.visit, COUNT(*), SUM(COALESCE(b.drt_me,0))
        FROM images i LEFT JOIN biomarkers b ON b.image_id = i.id
        WHERE i.trial = 'PRIME' GROUP BY i.trial, i.eye, i.visit"""),
    ("detail: the image", """
        SELECT i.*, p.age FROM images i
        LEFT JOIN patients p ON p.patient_id = i.subject WHERE i.id = 25795"""),
    ("detail: biomarkers", "SELECT * FROM biomarkers WHERE image_id = 25795"),
    ("detail: confidences", "SELECT * FROM biomarker_conf WHERE image_id = 100000"),
    ("detail: siblings", """
        SELECT id FROM images WHERE eye_id = 38 AND id != 25795 LIMIT 8"""),
    ("verify: the switch", "SELECT value FROM app_settings WHERE key = 'x'"),
    ("verify: this image", "SELECT biomarker, verdict FROM verifications WHERE image_id = 1"),
    ("verified count", "SELECT COUNT(DISTINCT image_id) FROM verifications"),
]


def main():
    db_path = sys.argv[1] if len(sys.argv) > 1 else "olives.db"
    if not pathlib.Path(db_path).exists():
        sys.exit(f"no database at {db_path}\n"
                 "Get one without spending read quota — export is a backup\n"
                 "operation and is NOT metered as row reads:\n"
                 "  npx wrangler d1 export retinaoct-olives --remote --output full.sql\n"
                 "  sqlite3 live.db < full.sql")
    db = sqlite3.connect(db_path)
    sizes = {t: db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
             for (t,) in db.execute("SELECT name FROM sqlite_master "
                                    "WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
    alias = {"i": "images", "b": "biomarkers", "p": "patients"}
    print("  table sizes: " + ", ".join(f"{t} {n:,}" for t, n in sorted(sizes.items()) if n))
    print()

    suspect = []
    for label, sql in QUERIES:
        plan = [r[3] for r in db.execute("EXPLAIN QUERY PLAN " + sql)]
        rows = 0
        for p in plan:
            if not p.startswith("SCAN"):
                continue
            for t in re.findall(r"SCAN (\w+)", p):
                rows = max(rows, sizes.get(alias.get(t, t), 0))
        flag = "  <-- scans" if rows > 1000 else ""
        print(f"  {label}{flag}")
        for p in plan:
            print(f"      {p}")
        if rows > 1000:
            suspect.append((label, rows))
        print()

    if suspect:
        print("  These scan a large table. That is not automatically wrong — an")
        print("  ordered scan stops at the LIMIT, and an edge-cached or")
        print("  corpus-served caller pays once or never. But EXPLAIN cannot tell")
        print("  you which, and guessing from it is how two of these outages were")
        print("  missed. Get the real number from D1 itself:")
        print()
        print("      curl -s 'https://retinaoct.com/api/search?<filters>&debug=1' \\")
        print("        | python3 -c 'import sys,json;print(json.load(sys.stdin)[\"_rows_read\"])'")
        print()
        print("  That is D1's own accounting. Budget: a query a user can trigger")
        print("  repeatedly should stay under ~1,000 rows. 153,000 means roughly")
        print("  thirty uses exhaust the day.")
        for label, rows in suspect:
            print(f"    - {label}: up to {rows:,} rows")
    else:
        print("  no query scans a large table")


if __name__ == "__main__":
    main()
