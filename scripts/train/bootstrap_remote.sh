#!/usr/bin/env bash
# Runs ON the Vast.ai instance. Installs deps, pulls the dataset from B2,
# and leaves everything staged for training.
#
#   scp -P <port> bootstrap_remote.sh root@<host>:/root/
#   ssh -p <port> root@<host> 'B2_KEY_ID=... B2_APP_KEY=... B2_BUCKET=... bash bootstrap_remote.sh'
set -euo pipefail
WORK=/workspace
mkdir -p $WORK/{data,train,runs}

echo "==> GPU"
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader

echo "==> python deps"
pip install -q --no-cache-dir timm==1.0.30 huggingface_hub pillow numpy

echo "==> rclone"
command -v rclone >/dev/null || { curl -s https://rclone.org/install.sh | bash >/dev/null 2>&1; }

echo "==> pulling dataset from B2"
: "${B2_BUCKET:?}" "${RCLONE_CONFIG_B2_ACCOUNT:?}" "${RCLONE_CONFIG_B2_KEY:?}"
export RCLONE_CONFIG_B2_TYPE=b2
rclone copy "b2:$B2_BUCKET/train/olives_labelled.tar" $WORK/data/ --progress
tar -C $WORK/data -xf $WORK/data/olives_labelled.tar
rm -f $WORK/data/olives_labelled.tar
echo "    $(find $WORK/data -name '*.tif' | wc -l) images extracted"

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
export OLIVES_MANIFEST=$WORK/data/manifest.csv
export OLIVES_OUT=$WORK/runs
export HF_HOME_MODELS=$WORK/models
export OLIVES_ENCODER=${OLIVES_ENCODER:-bitfount/RETFound_MAE_OCT}
export OLIVES_ENCODER_FILE=${OLIVES_ENCODER_FILE:-pytorch_model.bin}
EOF
echo "==> ready. source $WORK/env.sh then run train_olives.py"
