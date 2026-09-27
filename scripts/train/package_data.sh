#!/usr/bin/env bash
# Package the 9,408 labelled OLIVES images + manifest into one tarball and
# (optionally) push it to B2, so the GPU instance pulls a single 2.3 GB object
# instead of making 9,408 round trips.
#
#   ./scripts/train/package_data.sh              # build tarball only
#   doppler run -- ./scripts/train/package_data.sh --upload
set -euo pipefail
ROOT="/Users/nicolemulla/oct-data/extracted/olives/OLIVES"
TRAIN="/Users/nicolemulla/oct-data/train"
TAR="$TRAIN/olives_labelled.tar"
UPLOAD=0; [ "${1:-}" = "--upload" ] && UPLOAD=1

[ -f "$TRAIN/manifest.csv" ] || { echo "no manifest — run build_manifest.py first"; exit 1; }

echo "==> resolving labelled files"
python3 - <<PY
import csv, os
root="$ROOT"; out="$TRAIN/filelist.txt"
n=miss=0
with open(out,"w") as w:
    for r in csv.DictReader(open("$TRAIN/manifest.csv")):
        rel=r["path"].lstrip("/"); f=None
        for pre in ("TREX_DME","Prime_FULL"):
            c=os.path.join(root,pre,rel)
            if os.path.exists(c): f=c; break
        if f: w.write(os.path.relpath(f,root)+"\n"); n+=1
        else: miss+=1
print(f"    {n} files resolved, {miss} missing")
PY

echo "==> building tarball"
tar -C "$ROOT" -cf "$TAR" -T "$TRAIN/filelist.txt"
tar -C "$TRAIN" -rf "$TAR" manifest.csv manifest_meta.json
echo "    $(du -h "$TAR" | cut -f1)  $TAR"

if [ "$UPLOAD" = "1" ]; then
  : "${B2_BUCKET:?run under 'doppler run --'}"
  echo "==> uploading to b2:$B2_BUCKET/train/"
  rclone copy "$TAR" "b2:$B2_BUCKET/train/" --progress
  echo "    done"
fi
