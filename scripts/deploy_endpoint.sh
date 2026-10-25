#!/usr/bin/env bash
# Create (or update) the HF Inference Endpoint that serves the biomarker model,
# wait for it to come up, and smoke-test it with a real B-scan.
#
#   doppler run -p retinaoct -c dev -- ./scripts/deploy_endpoint.sh
#   doppler run -p retinaoct -c dev -- ./scripts/deploy_endpoint.sh --dry-run
#
# Prerequisite: a payment method on the HuggingFace account. Without one the
# create call returns 403 "Payment method required" — see docs/serving.md.
#
# Sizing is measured, not guessed: the model peaks at 2.81 GB resident, so the
# $0.033/hr 2 GB instance OOMs and x2 (4 GB) is the cheapest that fits.
set -euo pipefail

NS="${HF_NAMESPACE:-NicoleMulla}"
NAME="${ENDPOINT_NAME:-retinaoct-biomarkers}"
REPO="${MODEL_REPO:-NicoleMulla/retfound-olives-16bm}"
SIZE="${INSTANCE_SIZE:-x2}"          # x2 = 2 vCPU / 4 GB / $0.067 per hour
REGION="${REGION:-us-east-1}"
IDLE_MIN="${SCALE_TO_ZERO_MIN:-15}"  # minutes warm before scaling back to zero
API="https://api.endpoints.huggingface.cloud/v2/endpoint/$NS"
DRY=0; [ "${1:-}" = "--dry-run" ] && DRY=1

: "${HF_TOKEN:?HF_TOKEN not set — run under 'doppler run --'}"

# curl argv is visible in `ps`; keep the bearer token out of it.
CFG="$(mktemp -t hf_auth)"; chmod 600 "$CFG"
printf 'header = "Authorization: Bearer %s"\nheader = "Content-Type: application/json"\n' "$HF_TOKEN" > "$CFG"
trap 'rm -f "$CFG"' EXIT
auth=(-K "$CFG")

read -r -d '' BODY <<JSON || true
{
  "name": "$NAME",
  "type": "protected",
  "provider": { "vendor": "aws", "region": "$REGION" },
  "compute": {
    "accelerator": "cpu",
    "instanceType": "intel-spr",
    "instanceSize": "$SIZE",
    "scaling": { "minReplica": 0, "maxReplica": 1, "scaleToZeroTimeout": $IDLE_MIN }
  },
  "model": {
    "repository": "$REPO",
    "framework": "pytorch",
    "task": "custom",
    "image": { "huggingface": {} }
  }
}
JSON

if [ "$DRY" = 1 ]; then echo "$BODY"; exit 0; fi

echo "==> creating $NS/$NAME ($SIZE, $REGION, scale-to-zero after ${IDLE_MIN}m)"
code=$(curl -s "${auth[@]}" -X POST -d "$BODY" "$API" -o /tmp/ep_create.json -w "%{http_code}")
if [ "$code" = "409" ]; then
  echo "    already exists — updating instead"
  curl -s "${auth[@]}" -X PUT -d "$BODY" "$API/$NAME" -o /tmp/ep_create.json -w "    HTTP %{http_code}\n"
elif [ "$code" != "200" ] && [ "$code" != "202" ]; then
  echo "    HTTP $code"; cat /tmp/ep_create.json; echo
  [ "$code" = "403" ] && echo "    -> add a payment method at https://huggingface.co/settings/billing"
  exit 1
fi

echo "==> waiting for it to become running (first build pulls a 1.2 GB checkpoint)"
URL=""
for i in $(seq 1 60); do
  sleep 15
  curl -s "${auth[@]}" "$API/$NAME" -o /tmp/ep_state.json || true
  state=$(python3 -c "import json;print(json.load(open('/tmp/ep_state.json')).get('status',{}).get('state','?'))" 2>/dev/null || echo "?")
  URL=$(python3 -c "import json;print(json.load(open('/tmp/ep_state.json')).get('status',{}).get('url') or '')" 2>/dev/null || echo "")
  printf "    [%2d] %s\n" "$i" "$state"
  case "$state" in
    running) break ;;
    failed|*ailed*) echo "    build failed — check https://ui.endpoints.huggingface.co/$NS/endpoints/$NAME"; exit 1 ;;
  esac
done
[ -z "$URL" ] && { echo "    no URL yet; check the dashboard"; exit 1; }

echo "==> smoke test"
# `find | head -1` makes find die on SIGPIPE, which `set -o pipefail` turns into
# a script-wide failure. -print -quit stops find itself instead.
IMG=$(find "$HOME/oct-data/extracted/olives" -name '*.tif' -print -quit 2>/dev/null || true)
if [ -n "$IMG" ]; then
  python3 - "$IMG" "$URL" <<'PY'
import base64, json, os, sys, urllib.request
img, url = sys.argv[1], sys.argv[2]
body = json.dumps({"inputs": base64.b64encode(open(img, "rb").read()).decode()}).encode()
req = urllib.request.Request(url, body, {
    "Authorization": f"Bearer {os.environ['HF_TOKEN']}", "Content-Type": "application/json"})
out = json.load(urllib.request.urlopen(req, timeout=180))
print(f"    verdict={out.get('verdict')} distance={out.get('distance')} "
      f"predictions={len(out.get('predictions') or [])}")
PY
else
  echo "    (no local OLIVES scan found — skipped)"
fi

cat <<EOF

==> endpoint URL
    $URL

Wire it into the website (values never pass through the shell history):
    npx wrangler pages secret put HF_ENDPOINT_URL --project-name retinaoct
    npx wrangler pages secret put HF_TOKEN        --project-name retinaoct
EOF
