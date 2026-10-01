#!/usr/bin/env bash
# Runs ON the Vast.ai instance. Installs deps and pulls the 9,408 labelled
# OLIVES images straight from B2, where the full dataset already lives — no
# need to stage a tarball up from a home connection first.
#
# Expects in the environment: RCLONE_CONFIG_B2_ACCOUNT, RCLONE_CONFIG_B2_KEY,
# B2_BUCKET, and optionally HF_TOKEN.
set -euo pipefail
WORK=/workspace
mkdir -p $WORK/{data,runs,models}

echo "==> GPU"
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader

echo "==> python deps"
pip install -q --no-cache-dir timm==1.0.30 huggingface_hub pillow numpy

echo "==> rclone"
command -v rclone >/dev/null || { curl -s https://rclone.org/install.sh | bash >/dev/null 2>&1 || true; }
command -v rclone >/dev/null || { apt-get -qq update && apt-get -qq install -y rclone; }

: "${B2_BUCKET:?}" "${RCLONE_CONFIG_B2_ACCOUNT:?}" "${RCLONE_CONFIG_B2_KEY:?}"
export RCLONE_CONFIG_B2_TYPE=b2

echo "==> pulling 9,408 labelled images from B2"
# filelist.txt paths are relative to datasets/olives/OLIVES/ — the same layout
# the local extract uses, so the manifest resolves identically on both sides.
rclone copy "b2:$B2_BUCKET/datasets/olives/OLIVES" "$WORK/data" \
  --files-from $WORK/filelist.txt \
  --transfers 48 --checkers 48 --b2-chunk-size 16M \
  --stats 15s --stats-one-line
echo "    $(find $WORK/data -name '*.tif' | wc -l) images on disk"

echo "==> caching RETFound encoder"
ENC="${OLIVES_ENCODER:-bitfount/RETFound_MAE_OCT}"
ENC_FILE="${OLIVES_ENCODER_FILE:-pytorch_model.bin}"
python3 - <<EOF
import os
from huggingface_hub import hf_hub_download
p = hf_hub_download("$ENC", "$ENC_FILE", cache_dir="$WORK/models",
                    token=os.environ.get("HF_TOKEN") or None)
print("   ", p)
EOF

cat > $WORK/env.sh <<EOF
export OLIVES_ROOT=$WORK/data
export OLIVES_MANIFEST=$WORK/manifest.csv
export OLIVES_OUT=$WORK/runs
export HF_HOME_MODELS=$WORK/models
export OLIVES_ENCODER=$ENC
export OLIVES_ENCODER_FILE=$ENC_FILE
EOF
echo "==> ready — source $WORK/env.sh, then python3 train_olives.py"
