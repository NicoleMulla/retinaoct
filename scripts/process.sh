#!/bin/bash
# Extract each archive, then sync it to Backblaze B2 under datasets/<name>/.
# Run under: doppler run -- ./process.sh
set -uo pipefail
ROOT=/Users/nicolemulla/oct-data
AR="$ROOT/archives"; EX="$ROOT/extracted"
log() { echo "[$(date -u +%H:%M:%S)] $*"; }

: "${B2_BUCKET:?B2_BUCKET not set — run under 'doppler run --'}"

declare -a JOBS=(
  "octdl:OCTDL.zip"
  "bissig-ohsu-ad:bissig-ohsu-ad.zip"
  "hcms:hcms.zip"
  "kermany-oct2017:kermany-oct2017.zip"
)

for job in "${JOBS[@]}"; do
  name="${job%%:*}"; file="${job#*:}"
  src="$AR/$file"; dest="$EX/$name"

  [ -s "$src" ] || { log "$name: archive missing, skipping"; continue; }

  if [ -d "$dest" ] && [ -n "$(ls -A "$dest" 2>/dev/null)" ]; then
    log "$name: already extracted"
  else
    log "$name: extracting $file"
    mkdir -p "$dest"
    case "$file" in
      *.zip) unzip -q -o "$src" -d "$dest" || { log "$name: EXTRACT FAILED"; continue; } ;;
      *.tar.gz|*.tgz) tar -xzf "$src" -C "$dest" || { log "$name: EXTRACT FAILED"; continue; } ;;
      *) log "$name: unknown archive type"; continue ;;
    esac
    # collapse a single redundant top-level directory
    shopt -s nullglob dotglob
    entries=("$dest"/*)
    if [ ${#entries[@]} -eq 1 ] && [ -d "${entries[0]}" ]; then
      inner="${entries[0]}"
      log "$name: flattening $(basename "$inner")/"
      mv "$inner"/* "$dest"/ 2>/dev/null && rmdir "$inner" 2>/dev/null
    fi
    shopt -u nullglob dotglob
    log "$name: extracted — $(find "$dest" -type f | wc -l | tr -d ' ') files, $(du -sh "$dest"|cut -f1)"
  fi

  log "$name: uploading to b2:$B2_BUCKET/datasets/$name/"
  rclone copy "$dest" "b2:$B2_BUCKET/datasets/$name" \
    --transfers 16 --checkers 32 --fast-list \
    --b2-chunk-size 96M --stats 30s --stats-one-line \
  && log "$name: upload OK" || log "$name: UPLOAD FAILED"
done

# labels csv rides alongside octdl
if [ -s "$AR/OCTDL_labels.csv" ]; then
  rclone copy "$AR/OCTDL_labels.csv" "b2:$B2_BUCKET/datasets/octdl/" && log "octdl labels uploaded"
fi

log "=== done ==="
rclone size "b2:$B2_BUCKET/datasets"
