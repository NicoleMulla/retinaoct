#!/usr/bin/env bash
# Verify the live D1 schema still has every index the query paths depend on.
#
# Run after ANY rebuild or import. An index can disappear without a single
# error — queries just start reading the whole table, and the only symptom is
# the daily row-read allowance vanishing. That is how idx_img_sort_default was
# lost once already.
#
#   CLOUDFLARE_API_TOKEN= npx ... (needs a token with D1 read; the
#   retinaoct-deploy token does NOT have it and returns API code 7403)
#
#   ./scripts/check_schema.sh
set -euo pipefail
DB="${D1_NAME:-retinaoct-olives}"
REQUIRED=(idx_img_trial idx_img_eye idx_img_patient idx_img_eyeid idx_img_visit
          idx_img_hasbio idx_img_bcva idx_img_cst idx_img_sort_default)

out=$(npx wrangler d1 execute "$DB" --remote --json \
      --command "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='images'" 2>&1) || {
  echo "could not read the schema:"; echo "$out" | tail -5; exit 1; }

missing=0
for idx in "${REQUIRED[@]}"; do
  if grep -q "\"$idx\"" <<<"$out"; then printf '  ok       %s\n' "$idx"
  else printf '  MISSING  %s\n' "$idx"; missing=$((missing+1)); fi
done
echo
if [ "$missing" -gt 0 ]; then
  echo "$missing index(es) missing. Apply scripts/migrations/ and re-run."
  exit 1
fi
echo "all required indexes present"

# the cheap sanity check that needs no D1 permissions at all
echo
echo "runtime check (no credentials needed):"
echo "  curl -s 'https://retinaoct.com/api/search?debug=1&v=2' | python3 -m json.tool | grep -A3 _rows_read"
echo "  results_default_sort should be ~24; anything in the thousands means the index is gone"
