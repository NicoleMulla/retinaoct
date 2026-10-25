#!/usr/bin/env bash
# Push space/ to the HuggingFace Space that serves the biomarker model, wait for
# the rebuild, and smoke-test it with a real OLIVES B-scan.
#
#   doppler run -p retinaoct -c dev -- ./scripts/deploy_space.sh
#
# The Space is private and pulls weights from the private model repo, so it
# needs its own HF_TOKEN secret — set here, never printed.
set -euo pipefail
: "${HF_TOKEN:?HF_TOKEN not set — run under 'doppler run --'}"
SPACE="${SPACE_ID:-NicoleMulla/retinaoct-biomarkers}"

python3 - "$SPACE" <<'PY'
import base64, glob, json, os, sys, time, urllib.error, urllib.request
from huggingface_hub import HfApi

space = sys.argv[1]
tok = os.environ["HF_TOKEN"]
api = HfApi(token=tok)

print(f"==> pushing space/ to {space}")
api.upload_folder(folder_path="space", repo_id=space, repo_type="space",
                  commit_message="Update serving app")
api.add_space_secret(repo_id=space, key="HF_TOKEN", value=tok,
                     description="Read access to the private model repo")
print("    uploaded; HF_TOKEN secret set (value not echoed)")

print("==> waiting for rebuild")
last = None
for i in range(80):                                   # ~20 min ceiling
    stage = api.get_space_runtime(space).stage
    if stage != last:
        print(f"    [{i*15:4d}s] {stage}")
        last = stage
    if stage == "RUNNING":
        break
    if stage in ("BUILD_ERROR", "RUNTIME_ERROR", "CONFIG_ERROR"):
        rt = api.get_space_runtime(space)
        print("    error:", (getattr(rt, "raw", {}) or {}).get("errorMessage", "")[:400])
        print(f"    full logs: https://huggingface.co/spaces/{space}?logs=build")
        sys.exit(1)
    time.sleep(15)
else:
    print("    timed out waiting for RUNNING"); sys.exit(1)

url = f"https://{space.replace('/', '-').lower()}.hf.space"
print(f"==> smoke test against {url}")
imgs = glob.glob(os.path.expanduser("~/oct-data/extracted/olives/**/*.tif"), recursive=True)
if not imgs:
    print("    no local OLIVES scan found — skipped"); sys.exit(0)
body = json.dumps({"inputs": base64.b64encode(open(imgs[0], "rb").read()).decode()}).encode()
req = urllib.request.Request(url + "/api/analyse", body,
    {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"})
for attempt in range(8):                              # first call wakes the Space
    try:
        t = time.time()
        out = json.load(urllib.request.urlopen(req, timeout=240))
        print(f"    ok in {time.time()-t:.1f}s — verdict={out.get('verdict')} "
              f"distance={out.get('distance')} predictions={len(out.get('predictions') or [])}")
        print(f"\nSet as the website's HF_ENDPOINT_URL:\n    {url}/api/analyse")
        break
    except urllib.error.HTTPError as e:
        print(f"    attempt {attempt+1}: HTTP {e.code} — still waking, retrying")
        time.sleep(20)
    except Exception as e:
        print(f"    attempt {attempt+1}: {type(e).__name__} — retrying")
        time.sleep(20)
else:
    print("    smoke test did not succeed"); sys.exit(1)
PY
