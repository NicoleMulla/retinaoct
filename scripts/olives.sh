#!/bin/bash
: "${B2_BUCKET:?not set}"
O=/Users/nicolemulla/oct-data/extracted/olives/OLIVES
log(){ echo "[$(date -u +%H:%M:%S)] $*"; }

for z in TREX_DME Prime_FULL; do
  if [ -f "$O/$z.zip" ]; then
    log "$z: extracting $(du -h "$O/$z.zip"|cut -f1)"
    mkdir -p "$O/$z"
    if unzip -q -o "$O/$z.zip" -d "$O/$z"; then
      n=$(find "$O/$z" -type f | wc -l | tr -d ' ')
      log "$z: extracted $n files, $(du -sh "$O/$z"|cut -f1)"
      rm -f "$O/$z.zip"; log "$z: removed nested zip to free disk"
    else
      log "$z: EXTRACT FAILED"
    fi
  else
    log "$z: no zip (already handled)"
  fi
done

log "olives: total $(find /Users/nicolemulla/oct-data/extracted/olives -type f | wc -l | tr -d ' ') files, $(du -sh /Users/nicolemulla/oct-data/extracted/olives|cut -f1)"
log "olives: uploading"
rclone copy /Users/nicolemulla/oct-data/extracted/olives "b2:$B2_BUCKET/datasets/olives" \
  --transfers 24 --checkers 48 --fast-list --b2-chunk-size 96M \
  --stats 300s --stats-one-line && log "olives: OK" || log "olives: FAILED"
log "=== OLIVES DONE ==="
