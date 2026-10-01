#!/usr/bin/env bash
# Destroy the provisioned Vast.ai instance. Billing stops only on destroy.
set -euo pipefail
: "${VAST_API_KEY:?}"
ID="${1:-$(cat /tmp/vast_instance_id 2>/dev/null || true)}"
[ -z "$ID" ] && { echo "usage: destroy.sh <instance_id>"; exit 1; }
# curl argv is visible in `ps`; keep the bearer token in a 0600 file instead.
VAST_AUTH_CFG="$(mktemp -t vast_auth_cfg)"
chmod 600 "$VAST_AUTH_CFG"
printf 'header = "Authorization: Bearer %s"\nheader = "Content-Type: application/json"\n' "$VAST_API_KEY" > "$VAST_AUTH_CFG"
trap 'rm -f "$VAST_AUTH_CFG"' EXIT
code=$(curl -sL -o /tmp/destroy.json -w "%{http_code}" -X DELETE \
  -K "$VAST_AUTH_CFG" \
  "https://console.vast.ai/api/v1/instances/$ID/" -d '{}')
if [ "$code" != "200" ]; then   # fall back to the older path
  code=$(curl -sL -o /tmp/destroy.json -w "%{http_code}" -X DELETE \
    -K "$VAST_AUTH_CFG" \
    "https://console.vast.ai/api/v0/instances/$ID/" -d '{}')
fi
cat /tmp/destroy.json; echo
[ "$code" = "200" ] && echo " <- destroyed $ID" || { echo " !! destroy FAILED (HTTP $code) — check https://cloud.vast.ai/instances"; exit 1; }
