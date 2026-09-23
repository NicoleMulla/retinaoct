#!/bin/bash
T7=/Volumes/T7/ret-dataset
EX=/Users/nicolemulla/oct-data/extracted
log(){ echo "[$(date -u +%H:%M:%S)] $*"; }

# Bissig — .rar, needs unar
if [ ! -d "$EX/bissig-ohsu-ad" ] || [ -z "$(ls -A "$EX/bissig-ohsu-ad" 2>/dev/null)" ]; then
  mkdir -p "$EX/bissig-ohsu-ad"
  log "bissig: extracting .rar"
  unar -q -f -o "$EX/bissig-ohsu-ad" "$T7/Bissig-OHSU-Alzheimer-OCT/OCT__FOR_DRYAD_2020-03MAR-08.rar" \
    && log "bissig: $(find "$EX/bissig-ohsu-ad" -type f|wc -l|tr -d ' ') files, $(du -sh "$EX/bissig-ohsu-ad"|cut -f1)" \
    || log "bissig: EXTRACT FAILED"
else log "bissig: already extracted"; fi

# Kermany v2 — OCT-only tar.gz (the canonical release)
if [ ! -d "$EX/kermany-oct2017-v2" ] || [ -z "$(ls -A "$EX/kermany-oct2017-v2" 2>/dev/null)" ]; then
  mkdir -p "$EX/kermany-oct2017-v2"
  log "kermany-v2: extracting tar.gz (5.4G)"
  tar -xzf "$T7/Kermany-OCT2017/OCT2017.tar.gz" -C "$EX/kermany-oct2017-v2" \
    && log "kermany-v2: $(find "$EX/kermany-oct2017-v2" -type f|wc -l|tr -d ' ') files, $(du -sh "$EX/kermany-oct2017-v2"|cut -f1)" \
    || log "kermany-v2: EXTRACT FAILED"
else log "kermany-v2: already extracted"; fi
log "=== extraction done ==="
