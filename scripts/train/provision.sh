#!/usr/bin/env bash
# Provision a single-GPU Vast.ai instance for the RETFound/OLIVES fine-tune.
#
#   doppler run -- ./scripts/train/provision.sh            # pick cheapest 4090
#   doppler run -- ./scripts/train/provision.sh --dry-run  # show offers only
#
# Requires VAST_API_KEY in the environment (Doppler injects it).
set -euo pipefail

API="https://console.vast.ai/api/v0"
# instances/ moved to v1; bundles, asks and users/current are still v0.
APIV1="https://console.vast.ai/api/v1"
GPU="${GPU:-RTX 4090}"
DISK="${DISK:-80}"
IMAGE="${IMAGE:-pytorch/pytorch:2.4.0-cuda12.1-cudnn9-devel}"
MAX_DPH="${MAX_DPH:-0.60}"
DRY=0; [ "${1:-}" = "--dry-run" ] && DRY=1

: "${VAST_API_KEY:?VAST_API_KEY not set — run under 'doppler run --'}"

auth=(-H "Authorization: Bearer $VAST_API_KEY" -H "Content-Type: application/json")

echo "==> checking account"
curl -s "${auth[@]}" "$API/users/current/" -o /tmp/vast_me.json
python3 - <<'PY'
import json,sys
d=json.load(open('/tmp/vast_me.json'))
c=float(d.get('credit') or 0)
print(f"    {d.get('email')}  credit ${c:.2f}  billing={d.get('has_billing')}")
if c <= 0:
    sys.exit("    ABORT: no credit on the account — add funds at https://cloud.vast.ai/billing")
PY

echo "==> searching offers ($GPU, <= \$$MAX_DPH/hr)"
Q=$(python3 -c "
import json,os
print(json.dumps({'verified':{'eq':True},'rentable':{'eq':True},'num_gpus':{'eq':1},
 'gpu_name':{'eq':os.environ['GPU']},'disk_space':{'gte':int(os.environ['DISK'])+20},
 'dph_total':{'lte':float(os.environ['MAX_DPH'])},'reliability2':{'gte':0.97},
 'inet_down':{'gte':300},'order':[['dph_total','asc']],'type':'on-demand','limit':30}))" )
GPU="$GPU" DISK="$DISK" MAX_DPH="$MAX_DPH" curl -s "${auth[@]}" "$API/bundles/" -d "$Q" -o /tmp/vast_offers.json

python3 - <<'PY'
import json
o=json.load(open('/tmp/vast_offers.json'))['offers']
o.sort(key=lambda r:r['dph_total'])
print(f"    {len(o)} offers; top 5:")
for x in o[:5]:
    print(f"      id={x['id']:<10} ${x['dph_total']:.3f}/hr  {x['cpu_cores_effective']:.0f}cpu "
          f"{x['cpu_ram']/1024:.0f}GB  net {x['inet_down']:.0f}Mbps  rel {x['reliability2']:.3f}  {x.get('geolocation')}")
PY
[ "$DRY" = "1" ] && { echo "(dry run)"; exit 0; }

echo "==> renting (tries cheapest first; offers go stale within seconds)"
IDS=$(python3 -c "import json;o=json.load(open('/tmp/vast_offers.json'))['offers'];o.sort(key=lambda r:r['dph_total']);print(' '.join(str(x['id']) for x in o[:8]))")
NEW=""
for id in $IDS; do
  R=$(curl -s -X PUT "${auth[@]}" "$API/asks/$id/" \
      -d "{\"client_id\":\"me\",\"image\":\"$IMAGE\",\"disk\":$DISK,\"runtype\":\"ssh\",\"label\":\"retfound-olives\"}")
  if echo "$R" | grep -q '"success": *true'; then
    NEW=$(python3 -c "import json,sys;print(json.loads(sys.argv[1]).get('new_contract',''))" "$R")
    echo "    rented ask $id -> instance $NEW"; break
  fi
  echo "    ask $id: $(python3 -c "import json,sys;d=json.loads(sys.argv[1]);print(d.get('msg') or d.get('error'))" "$R")"
done
[ -z "$NEW" ] && { echo "ABORT: no offer could be rented"; exit 1; }

echo "==> waiting for instance to boot"
for i in $(seq 1 60); do
  curl -sL "${auth[@]}" "$APIV1/instances/" -o /tmp/vast_inst.json
  S=$(python3 -c "
import json
d=json.load(open('/tmp/vast_inst.json'))['instances']
m=[x for x in d if str(x['id'])=='$NEW']
print(m[0]['actual_status'] if m and m[0].get('actual_status') else 'pending')")
  echo "    [$i] $S"
  [ "$S" = "running" ] && break
  sleep 10
done

python3 - <<PY
import json
d=json.load(open('/tmp/vast_inst.json'))['instances']
m=[x for x in d if str(x['id'])=='$NEW']
if m:
    x=m[0]
    print(f"""
instance   {x['id']}
gpu        {x.get('gpu_name')}  x{x.get('num_gpus')}
cost       \${x.get('dph_total',0):.3f}/hr
ssh        ssh -p {x.get('ssh_port')} root@{x.get('ssh_host')}
status     {x.get('actual_status')}
""")
PY
echo "$NEW" > /tmp/vast_instance_id
echo "==> instance id saved to /tmp/vast_instance_id"
echo "    destroy with: doppler run -- ./scripts/train/destroy.sh"
