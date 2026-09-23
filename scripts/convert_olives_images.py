#!/usr/bin/env python3
"""Convert OLIVES TIFFs to web-servable WebP at two sizes.

TIFF is not renderable in browsers, so every image needs a derivative.
Outputs mirror the B2 key layout recorded in the D1 `images` table:
    web/olives/thumb/<stem>.webp   320px wide, q72  (~11 KB)
    web/olives/full/<stem>.webp    native 504x496, q86 (~44 KB)

Keys are sanitised: spaces -> underscores (TREX paths contain them).
Idempotent: existing outputs are skipped, so it is safe to re-run.
"""
import os, sqlite3, sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from PIL import Image

ROOT = "/Users/nicolemulla/oct-data/extracted/olives"
OUT  = "/Users/nicolemulla/oct-data/web"
DB   = "/Users/nicolemulla/oct-data/olives.db"
THUMB_W, THUMB_Q, FULL_Q = 320, 72, 86

def sanitize(s): return s.replace(" ", "_")

def resolve(path):
    rel = path.lstrip("/")
    for pref in ("TREX_DME", "Prime_FULL"):
        f = f"{ROOT}/OLIVES/{pref}/{rel}"
        if os.path.exists(f): return f
    return None

def convert(args):
    path, thumb_key, full_key = args
    src = resolve(path)
    if not src: return ("missing", path)
    t_out, f_out = f"{OUT}/{thumb_key}", f"{OUT}/{full_key}"
    if os.path.exists(t_out) and os.path.exists(f_out): return ("skip", path)
    try:
        im = Image.open(src).convert("L")
        os.makedirs(os.path.dirname(f_out), exist_ok=True)
        os.makedirs(os.path.dirname(t_out), exist_ok=True)
        im.save(f_out, "WEBP", quality=FULL_Q, method=4)
        h = round(im.size[1] * THUMB_W / im.size[0])
        im.resize((THUMB_W, h), Image.LANCZOS).save(t_out, "WEBP", quality=THUMB_Q, method=4)
        return ("ok", path)
    except Exception as e:
        return ("error", f"{path}: {e}")

def main():
    db = sqlite3.connect(DB)
    rows = db.execute("SELECT path, thumb_key, full_key FROM images").fetchall()
    rows = [(p, sanitize(t), sanitize(f)) for p, t, f in rows]
    db.close()
    print(f"converting {len(rows):,} images -> {OUT}")

    counts = {"ok": 0, "skip": 0, "missing": 0, "error": 0}
    errors = []
    with ProcessPoolExecutor(max_workers=os.cpu_count()) as ex:
        futs = [ex.submit(convert, r) for r in rows]
        for i, fu in enumerate(as_completed(futs), 1):
            status, info = fu.result()
            counts[status] += 1
            if status in ("error", "missing") and len(errors) < 5: errors.append(info)
            if i % 5000 == 0:
                print(f"  {i:,}/{len(rows):,}  ok={counts['ok']:,} skip={counts['skip']:,} "
                      f"missing={counts['missing']} err={counts['error']}", flush=True)
    print(f"\ndone: {counts}")
    if errors: print("samples:", *errors, sep="\n  ")
    tot = sum(os.path.getsize(os.path.join(r, f))
              for r, _, fs in os.walk(OUT) for f in fs)
    print(f"output: {tot/1e9:.2f} GB")

if __name__ == "__main__":
    main()
