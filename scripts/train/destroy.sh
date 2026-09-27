#!/usr/bin/env bash
# Destroy the provisioned Vast.ai instance. Billing stops only on destroy.
set -euo pipefail
: "${VAST_API_KEY:?}"
ID="${1:-$(cat /tmp/vast_instance_id 2>/dev/null || true)}"
[ -z "$ID" ] && { echo "usage: destroy.sh <instance_id>"; exit 1; }
code=$(curl -sL -o /tmp/destroy.json -w "%{http_code}" -X DELETE \
  -H "Authorization: Bearer $VAST_API_KEY" -H "Content-Type: application/json" \
  "https://console.vast.ai/api/v1/instances/$ID/" -d '{}')
if [ "$code" != "200" ]; then   # fall back to the older path
  code=$(curl -sL -o /tmp/destroy.json -w "%{http_code}" -X DELETE \
    -H "Authorization: Bearer $VAST_API_KEY" -H "Content-Type: application/json" \
    "https://console.vast.ai/api/v0/instances/$ID/" -d '{}')
fi
cat /tmp/destroy.json; echo
[ "$code" = "200" ] && echo " <- destroyed $ID" || { echo " !! destroy FAILED (HTTP $code) — check https://cloud.vast.ai/instances"; exit 1; }
