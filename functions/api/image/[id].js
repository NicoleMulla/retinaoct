import { BIOMARKERS, MODEL_BIOMARKERS } from "../_lib.js";

export async function onRequestGet({ params, env }) {
  try {
  const id = parseInt(params.id);
  if (!Number.isInteger(id)) return Response.json({ error: "bad id" }, { status: 400 });

  const img = await env.DB.prepare(
    `SELECT i.*, p.age, p.gender, p.ethnicity, p.race, p.diabetes_type,
            p.years_diabetes, p.hba1c_baseline, p.bmi, p.drss
     FROM images i LEFT JOIN patients p ON p.patient_id = i.subject
     WHERE i.id = ?`).bind(id).first();
  if (!img) return Response.json({ error: "not found" }, { status: 404 });

  const isModel = img.label_source === "model";

  // One row each. `biomarker_conf` exists only for model-inferred images, and is
  // read on the detail panel only — a tall values table would cost 16 rows here
  // and a 1.25M-row scan when faceting.
  const [bio, conf] = await Promise.all([
    env.DB.prepare("SELECT * FROM biomarkers WHERE image_id = ?").bind(id).first(),
    isModel ? env.DB.prepare("SELECT * FROM biomarker_conf WHERE image_id = ?").bind(id).first()
            : Promise.resolve(null),
  ]);

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

  const siblings = img.eye_id != null ? await env.DB.prepare(
    `SELECT id, visit, scan_index, thumb_key, biomarker_count, label_source
     FROM images WHERE eye_id = ? AND id != ? ORDER BY visit, scan_index LIMIT 12`
  ).bind(img.eye_id, id).all() : { results: [] };

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
    } : { kind: "expert", source: "OLIVES dataset expert annotation" },
    same_eye: siblings.results,
  }, { headers: { "cache-control": "public, max-age=0, must-revalidate, s-maxage=300" } });
  } catch (err) {
    return Response.json({ error: "lookup failed", detail: String(err && err.message || err) },
                         { status: 500 });
  }
}
