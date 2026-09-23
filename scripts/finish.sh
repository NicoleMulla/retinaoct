#!/bin/bash
: "${B2_BUCKET:?not set}"
EX=/Users/nicolemulla/oct-data/extracted
T7=/Volumes/T7/ret-dataset
log(){ echo "[$(date -u +%H:%M:%S)] $*"; }
up(){ # local_dir  b2_subpath  label
  log "$3: uploading"
  rclone copy "$1" "b2:$B2_BUCKET/datasets/$2" \
    --transfers 16 --checkers 32 --fast-list --b2-chunk-size 96M \
    --stats 120s --stats-one-line \
  && log "$3: OK" || { log "$3: FAILED"; return 1; }
}

up "$EX/bissig-ohsu-ad"      "bissig-ohsu-ad"  "bissig"
up "$EX/kermany-oct2017-v2"  "kermany-oct2017" "kermany-v2"

# ---- OLIVES ----
log "olives: verifying SHA-256 of 32G zip (takes a few minutes)"
EXPECT=$(awk '{print $1}' "$T7/OLIVES/OLIVES.zip.sha256")
ACTUAL=$(shasum -a 256 "$T7/OLIVES/OLIVES.zip" | awk '{print $1}')
if [ "$EXPECT" = "$ACTUAL" ]; then
  log "olives: checksum OK ($ACTUAL)"
else
  log "olives: CHECKSUM MISMATCH — expected $EXPECT got $ACTUAL — ABORTING olives"
  log "=== finished (olives skipped) ==="; rclone size "b2:$B2_BUCKET/datasets"; exit 1
fi

if [ ! -d "$EX/olives" ] || [ -z "$(ls -A "$EX/olives" 2>/dev/null)" ]; then
  mkdir -p "$EX/olives"
  log "olives: extracting labels"
  unzip -q -o "$T7/OLIVES/OLIVES_Dataset_Labels.zip" -d "$EX/olives" || log "olives: labels extract failed"
  log "olives: extracting OLIVES.zip (32G, slow)"
  unzip -q -o "$T7/OLIVES/OLIVES.zip" -d "$EX/olives" || { log "olives: EXTRACT FAILED"; exit 1; }
  log "olives: $(find "$EX/olives" -type f|wc -l|tr -d ' ') files, $(du -sh "$EX/olives"|cut -f1)"
else
  log "olives: already extracted"
fi

up "$EX/olives" "olives" "olives"

log "=== ALL DONE ==="
rclone size "b2:$B2_BUCKET/datasets"
