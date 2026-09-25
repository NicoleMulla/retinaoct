#!/usr/bin/env python3
"""Retinal thickness from a B-scan by classical image processing.

No model and no training: locate the inner limiting membrane (ILM) and the
retinal pigment epithelium (RPE) in each A-scan, and take the distance between
them. The central subfield average is directly comparable to the CST already
recorded for every OLIVES image, which makes this method self-validating.

  python3 thickness_classical.py            # sample 20 images, report only
  python3 thickness_classical.py --write    # also store values in the database
"""
import argparse, sys
import numpy as np
from scipy.ndimage import gaussian_filter, uniform_filter1d
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from _common import connect, register_source, write_values, load_gray, sample_images

SOURCE = dict(key="thickness_classical_v1",
              name="Classical ILM/RPE thickness",
              kind="algorithm", version="1.0",
              notes="Gradient-based ILM and peak-intensity RPE detection per A-scan; "
                    "central-subfield mean over the middle 1/6 of columns. No training.")

def segment(img):
    """Return smoothed (ilm_row, rpe_row) per column, or (None, None).

    RPE is taken as the *deepest* hyperreflective band rather than the
    brightest row — in oedema and fibrosis the global maximum is often a
    hyperreflective focus well above the RPE, which collapses the measurement.
    """
    if img is None or img.ndim != 2: return None, None
    g = gaussian_filter(img, sigma=(2.5, 2.0))
    h, w = g.shape
    ilm = np.full(w, np.nan)
    rpe = np.full(w, np.nan)

    for x in range(w):
        col = g[:, x]
        cmax, cmin = col.max(), np.percentile(col, 20)
        if cmax - cmin < 12:           # near-empty column at the scan edge
            continue
        hi = cmin + 0.55 * (cmax - cmin)
        above = col > hi
        if not above.any():
            continue
        idx = np.flatnonzero(above)

        # RPE: deepest run of bright pixels
        breaks = np.flatnonzero(np.diff(idx) > 3)
        last_run = idx[(breaks[-1] + 1):] if breaks.size else idx
        r = int(last_run[np.argmax(col[last_run])])

        # ILM: first rise that stays bright for >=3 rows, above the RPE
        lo = cmin + 0.30 * (cmax - cmin)
        band = col[:r] > lo
        run = np.convolve(band.astype(int), np.ones(3, int), "same")
        cand = np.flatnonzero(run >= 3)
        if cand.size == 0:
            continue
        i = int(cand[0])
        if r - i < 12 or r - i > 260:  # implausible retinal thickness in pixels
            continue
        ilm[x], rpe[x] = i, r

    ok = ~np.isnan(ilm)
    if ok.sum() < w * 0.4: return None, None
    # interpolate gaps, then smooth: layers are continuous surfaces
    xs = np.arange(w)
    ilm = np.interp(xs, xs[ok], ilm[ok])
    rpe = np.interp(xs, xs[ok], rpe[ok])
    return uniform_filter1d(ilm, 21, mode="nearest"), uniform_filter1d(rpe, 21, mode="nearest")

def measure(img):
    ilm, rpe = segment(img)
    if ilm is None: return None
    th = rpe - ilm
    w = len(th)
    c0, c1 = int(w * 5 / 12), int(w * 7 / 12)      # central sixth ~ 1mm of a 6mm scan
    central = float(np.nanmedian(th[c0:c1]))
    if not np.isfinite(central): return None
    return dict(central_px=central,
                mean_px=float(np.nanmedian(th)),
                max_px=float(np.nanmax(th)))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()

    db = connect()
    rows = sample_images(db, a.n)
    print(f"{'image':>7}  {'central_px':>10}  {'recorded CST':>12}  {'µm/px implied':>13}")
    print("-" * 52)

    obs, out = [], []
    for r in rows:
        m = measure(load_gray(r["path"]))
        if not m:
            print(f"{r['id']:>7}  {'segmentation failed':>10}")
            continue
        implied = r["cst"] / m["central_px"] if m["central_px"] else float("nan")
        print(f"{r['id']:>7}  {m['central_px']:>10.1f}  {r['cst']:>12.0f}  {implied:>13.2f}")
        obs.append((m["central_px"], r["cst"]))
        out.append((r["id"], m))

    if len(obs) >= 3:
        px = np.array([o[0] for o in obs]); cst = np.array([o[1] for o in obs])
        rho = np.corrcoef(px, cst)[0, 1]
        scale = float(np.median(cst / px))   # robust µm per pixel
        pred = px * scale
        mae = float(np.mean(np.abs(pred - cst)))
        print("-" * 52)
        print(f"n={len(obs)}  Pearson r = {rho:.3f}")
        print(f"fitted scale = {scale:.2f} µm/px   MAE vs recorded CST = {mae:.1f} µm")

        if a.write:
            sid = register_source(db, **SOURCE)
            vals = []
            for iid, m in out:
                vals.append((iid, "thickness_central_um", m["central_px"] * scale, None))
                vals.append((iid, "thickness_mean_um",    m["mean_px"] * scale, None))
            write_values(db, sid, vals)
            print(f"\nwrote {len(vals)} values as source '{SOURCE['key']}' (id {sid})")
    db.close()

if __name__ == "__main__":
    main()
