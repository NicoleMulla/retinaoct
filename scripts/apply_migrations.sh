#!/usr/bin/env bash
# Apply every file in scripts/migrations/ to the live D1 database.
#
# Needs a Cloudflare API token with "D1: Edit" on this account. The
# retinaoct-deploy token does NOT have it: `wrangler d1 execute` returns API
# code 7403 with it, though `wrangler d1 insights` works, so read-only
# analytics can mislead you into thinking the token is sufficient.
#
# Two ways to run it:
#
#   1. With a D1-capable token in Doppler (preferred -- keeps the secret out of
#      any transcript; add it in the Doppler dashboard, not here):
#        doppler run -p retinaoct -c dev -- ./scripts/apply_migrations.sh
#
#   2. Without one: this script prints the combined SQL, which you can paste
#      into the D1 console at
#        dash.cloudflare.com -> Workers & Pages -> D1 -> retinaoct-olives -> Console
#      That path needs no token at all.
#
# Every statement is CREATE INDEX IF NOT EXISTS, so re-running is harmless.
# Afterwards verify with ./scripts/check_schema.sh
set -euo pipefail
cd "$(dirname "$0")/.."
DB="${D1_NAME:-retinaoct-olives}"

combined=$(mktemp)
trap 'rm -f "$combined"' EXIT
cat scripts/migrations/*.sql > "$combined"
n=$(grep -c ';' "$combined" || true)
echo "$n statements across $(ls scripts/migrations/*.sql | wc -l | tr -d ' ') migration files"
echo

if npx wrangler d1 execute "$DB" --remote --file "$combined" 2>"$combined.err"; then
  echo
  echo "applied. verifying:"
  ./scripts/check_schema.sh
  exit 0
fi

if grep -q '7403\|Authentication\|authorization' "$combined.err" 2>/dev/null; then
  cat <<'MSG'
The token in this environment cannot execute SQL against D1 (API code 7403).

Either add a token with "D1: Edit" to Doppler and re-run, or paste the SQL
below into the D1 console, which needs no token:

  dash.cloudflare.com -> Workers & Pages -> D1 -> retinaoct-olives -> Console

------------------------------ copy from here ------------------------------
MSG
  sed -e 's/--.*$//' scripts/migrations/*.sql | grep -v '^[[:space:]]*$'
  cat <<'MSG'
------------------------------- to here ------------------------------------

Then run ./scripts/check_schema.sh to confirm, and
  curl -s https://retinaoct.com/api/_schema | python3 scripts/sql/capture_schema.py
to record the new schema in the repo.
MSG
  exit 1
fi

echo "failed for some other reason:"; tail -20 "$combined.err"; exit 1
