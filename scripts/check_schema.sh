#!/usr/bin/env bash
# Verify the live D1 schema still has every index the query paths depend on.
#
# Run after ANY rebuild or import, and in CI. An index can disappear without a
# single error — queries just start reading the whole table, and the only
# symptom is the daily row-read allowance vanishing. That is how
# idx_img_sort_default was lost once already.
#
# Needs no credentials. The check runs inside the Worker, which already holds
# the D1 binding; the one token this project has cannot read D1 at all, which
# is precisely why the drift went unnoticed for so long.
#
#   ./scripts/check_schema.sh
set -euo pipefail
BASE="${BASE_URL:-https://retinaoct.com}"

out=$(curl -sS --max-time 30 "$BASE/api/_schema?v=$(date +%s)") || {
  echo "could not reach $BASE/api/_schema"; exit 1; }

python3 - "$out" <<'PY'
import json, sys
try:
    d = json.loads(sys.argv[1])
except json.JSONDecodeError:
    print("  did not get JSON back:"); print(" ", sys.argv[1][:300]); sys.exit(1)

if "schema" not in d:
    print("  endpoint reported:", d.get("error", d)); sys.exit(1)

missing = d.get("missing_indexes") or []
unindexed = d.get("tables_filtering_image_id_without_an_index") or []

for t in ("table", "index"):
    names = sorted(r["name"] for r in d["schema"] if r["type"] == t)
    print(f"  {len(names)} {t + ('s' if t == 'table' else 'es')}: {', '.join(names)}")
print()
for m in missing:
    print(f"  MISSING INDEX  {m}")
for u in unindexed:
    print(f"  NO INDEX ON image_id  {u}  -> every lookup scans this table")

if missing or unindexed:
    print("\napply the matching file in scripts/migrations/ and re-run")
    sys.exit(1)
print("  all required indexes present; every image_id lookup is indexed")
PY

echo
echo "read-cost check:"
curl -s "$BASE/api/search?debug=1&v=$(date +%s)" | python3 -c '
import sys, json
d = json.load(sys.stdin)
r = d.get("_rows_read") or {}
print("  search:", r or "no debug payload")
for k, v in r.items():
    if isinstance(v, int) and v > 500:
        print(f"  WARNING {k} read {v} rows"); raise SystemExit(1)
' || exit 1
