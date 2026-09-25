import { BIOMARKERS } from "../_lib.js";

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

  const bio = await env.DB.prepare("SELECT * FROM biomarkers WHERE image_id = ?").bind(id).first();
  const biomarkers = BIOMARKERS.map(([k, label]) => ({
    key: k, label, present: bio ? !!bio[k] : null,
  }));

  // other scans of the same eye — pure ID lookup, no image comparison
  const siblings = img.eye_id != null ? await env.DB.prepare(
    `SELECT id, visit, scan_index, thumb_key, biomarker_count
     FROM images WHERE eye_id = ? AND id != ? ORDER BY visit, scan_index LIMIT 12`
  ).bind(img.eye_id, id).all() : { results: [] };

  return Response.json({
    ...img,
    biomarkers,
    has_labels: !!bio,
    same_eye: siblings.results,
  }, { headers: { "cache-control": "public, max-age=300" } });
  } catch (err) {
    return Response.json({ error: "lookup failed", detail: String(err && err.message || err) },
                         { status: 500 });
  }
}
