#!/bin/bash
: "${B2_BUCKET:?not set}"
EX=/Users/nicolemulla/oct-data/extracted
log(){ echo "[$(date -u +%H:%M:%S)] $*"; }

log "bissig: uploading 1,112 files / 5.5G"
rclone copy "$EX/bissig-ohsu-ad" "b2:$B2_BUCKET/datasets/bissig-ohsu-ad" \
  --transfers 16 --checkers 32 --fast-list --b2-chunk-size 96M \
  --stats 60s --stats-one-line && log "bissig: OK" || log "bissig: FAILED"

log "kermany-v2: removing incomplete v3 from B2 first"
rclone purge "b2:$B2_BUCKET/datasets/kermany-oct2017" 2>/dev/null; log "kermany-v3: purged"

log "kermany-v2: uploading 84,484 files / 5.6G"
rclone copy "$EX/kermany-oct2017-v2" "b2:$B2_BUCKET/datasets/kermany-oct2017" \
  --transfers 16 --checkers 32 --fast-list --b2-chunk-size 96M \
  --stats 60s --stats-one-line && log "kermany-v2: OK" || log "kermany-v2: FAILED"

log "=== uploads done ==="
rclone size "b2:$B2_BUCKET/datasets"
