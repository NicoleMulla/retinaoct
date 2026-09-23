#!/bin/bash
# Download public OCT datasets. Resumable (-C -). Logs to fetch.log.
cd /Users/nicolemulla/oct-data/archives || exit 1
log() { echo "[$(date -u +%H:%M:%S)] $*"; }

dl() { # name url filename
  local n="$1" u="$2" f="$3"
  if [ -s "$f" ]; then log "$n: already present ($(du -h "$f"|cut -f1))"; return 0; fi
  log "$n: downloading -> $f"
  if curl -fL -C - --retry 4 --retry-delay 5 --max-time 7200 \
       -A "Mozilla/5.0 (research dataset fetch)" -o "$f" "$u"; then
    log "$n: OK ($(du -h "$f"|cut -f1))"
  else
    log "$n: FAILED (exit $?)"; return 1
  fi
}

dl "OCTDL"     "https://data.mendeley.com/public-files/datasets/sncdhf53xc/files/2721fe0f-7793-4ef5-b2d0-d31a2ebfdeef/file_downloaded" "OCTDL.zip"
dl "OCTDL-lbl" "https://data.mendeley.com/public-files/datasets/sncdhf53xc/files/82880b41-939c-42b5-9f6b-3304b2c8dca1/file_downloaded" "OCTDL_labels.csv"
dl "Bissig"    "https://datadryad.org/api/v2/versions/56701/download" "bissig-ohsu-ad.zip"
dl "HCMS"      "https://iacl.ece.jhu.edu/~aaron/data/OCT_Manual_Delineations-2018_June_29_b.zip" "hcms.zip"
dl "Kermany"   "https://data.mendeley.com/public-files/datasets/rscbjbr9sj/files/810b2ce2-11c3-4424-996e-3bef36600907/file_downloaded" "kermany-oct2017.zip"

log "=== all downloads finished ==="
ls -lh /Users/nicolemulla/oct-data/archives
