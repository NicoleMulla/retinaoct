import { BIOMARKERS, MODEL_BIOMARKERS } from "../_lib.js";

/* D1 reports rows_read per query. The default-sort index was lost once and
   nobody noticed until the daily allowance ran out, so every D1 consumer now
   accounts for itself: ?debug=1 returns the per-query counts and anything
   reading more than a handful is logged. `biomarker_conf` is the table to
   watch — its schema was created straight against D1 and exists nowhere in
   this repo, so whether image_id is indexed there is currently unknown. */
const ROW_BUDGET = 200;

function audit(res, label, debug) {
  const n = res && res.meta && typeof res.meta.rows_read === "number" ? res.meta.rows_read : null;
  if (n !== null && n > ROW_BUDGET) {
    console.warn(`[d1] image detail: ${label} read ${n} rows (budget ${ROW_BUDGET}) — missing index?`);
  }
  if (debug) debug[label] = n;
  return res;
}

export async function onRequestGet({ params, env, request }) {
  try {
  const debug = new URL(request.url).searchParams.get("debug") === "1" ? {} : null;
  const id = parseInt(params.id);
  if (!Number.isInteger(id)) return Response.json({ error: "bad id" }, { status: 400 });

  const img = await env.DB.prepare(
    `SELECT i.*, p.age, p.gender, p.ethnicity, p.race, p.diabetes_type,
            p.years_diabetes, p.hba1c_baseline, p.bmi, p.drss
     FROM images i LEFT JOIN patients p ON p.patient_id = i.subject
     WHERE i.id = ?`).bind(id).first();
  if (!img) return Response.json({ error: "not found" }, { status: 404 });

  const isModel = img.label_source === "model";
  const isRejected = img.label_source === "rejected";

  // One row each. `biomarker_conf` exists only for model-inferred images, and is
  // read on the detail panel only — a tall values table would cost 16 rows here
  // and a 1.25M-row scan when faceting.
  // .all() rather than .first() so D1 hands back meta.rows_read to audit
  const [bioRes, confRes] = await Promise.all([
    env.DB.prepare("SELECT * FROM biomarkers WHERE image_id = ?").bind(id).all(),
    isModel ? env.DB.prepare("SELECT * FROM biomarker_conf WHERE image_id = ?").bind(id).all()
            : Promise.resolve(null),
  ]);
  audit(bioRes, "biomarkers", debug);
  if (confRes) audit(confRes, "biomarker_conf", debug);
  const bio = (bioRes.results && bioRes.results[0]) || null;
  const conf = confRes ? ((confRes.results && confRes.results[0]) || null) : null;

  const biomarkers = BIOMARKERS.map(([k, label]) => {
    const present = bio ? (bio[k] === null || bio[k] === undefined ? null : !!bio[k]) : null;
    // The four biomarkers the model cannot predict stay unknown on model-labelled
    // images rather than being reported absent — a fabricated 0 would read as a
    // clinical finding.
    const predictable = MODEL_BIOMARKERS.has(k);
    if (isModel && !predictable) {
      return { key: k, label, present: null, source: null,
               confidence: null, unavailable: "not_predictable" };
    }
    return {
      key: k, label, present,
      source: present === null ? null : (isModel ? "model" : "expert"),
      confidence: isModel && conf ? conf[k] : null,
    };
  });

  const siblings = img.eye_id != null ? audit(await env.DB.prepare(
    `SELECT id, visit, scan_index, thumb_key, biomarker_count, label_source
     FROM images WHERE eye_id = ? AND id != ? ORDER BY visit, scan_index LIMIT 12`
  ).bind(img.eye_id, id).all(), "siblings", debug) : { results: [] };

  return Response.json({
    ...img,
    biomarkers,
    has_labels: !!bio,
    label_source: img.label_source || null,
    // Provenance block. Present only for model-inferred rows, so the UI can show
    // what produced the numbers and how far the image sits from training data.
    provenance: isModel ? {
      kind: "model",
      model: "NicoleMulla/retfound-olives-16bm",
      architecture: "RETFound ViT-L/16 (303.3M)",
      mean_auroc: 0.8916,
      trained_on: "9,408 expert-labelled OLIVES B-scans from 87 patients",
      ood_distance: conf ? conf.ood_distance : null,
      verdict: conf ? conf.verdict : null,
      not_predicted: BIOMARKERS.map(([k]) => k).filter(k => !MODEL_BIOMARKERS.has(k)),
      caveat: "Model inference, not expert annotation. Research use only; not a medical device.",
    } : isRejected ? {
      kind: "rejected",
      reason: "Outside the distribution the model was validated on; no predictions produced.",
      caveat: "Absence of findings here means the model declined to judge, not that the "
              + "retina is normal.",
    } : { kind: "expert", source: "OLIVES dataset expert annotation" },
    same_eye: siblings.results,
    ...(debug ? { _rows_read: debug } : {}),
  }, { headers: { "cache-control": "public, max-age=0, must-revalidate, s-maxage=300" } });
  } catch (err) {
    return Response.json({ error: "lookup failed", detail: String(err && err.message || err) },
                         { status: 500 });
  }
}
