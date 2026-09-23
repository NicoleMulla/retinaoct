import { BIOMARKERS, buildFilter, SORTS } from "./_lib.js";

export async function onRequestGet({ request, env }) {
  const url = new URL(request.url);
  const { sql: where, bind } = buildFilter(url);
  const base = `FROM images i LEFT JOIN biomarkers b ON b.image_id = i.id ${where}`;

  const per = Math.min(parseInt(url.searchParams.get("per_page")) || 24, 100);
  const page = Math.max(parseInt(url.searchParams.get("page")) || 1, 1);
  const order = SORTS[url.searchParams.get("sort")] || SORTS.relevant;

  const [countRow, rows, fTrial, fEye, fVisit, fBio] = await Promise.all([
    env.DB.prepare(`SELECT COUNT(*) AS n ${base}`).bind(...bind).first(),
    env.DB.prepare(
      `SELECT i.id, i.trial, i.arm, i.subject, i.visit, i.eye, i.scan_index,
              i.patient_id, i.eye_id, i.bcva, i.cst,
              i.has_biomarkers, i.biomarker_count, i.thumb_key
       ${base} ORDER BY ${order} LIMIT ? OFFSET ?`
    ).bind(...bind, per, (page - 1) * per).all(),
    env.DB.prepare(`SELECT i.trial AS v, COUNT(*) AS n ${base} GROUP BY i.trial ORDER BY n DESC`).bind(...bind).all(),
    env.DB.prepare(`SELECT i.eye AS v, COUNT(*) AS n ${base} GROUP BY i.eye ORDER BY n DESC`).bind(...bind).all(),
    env.DB.prepare(`SELECT i.visit AS v, COUNT(*) AS n ${base} GROUP BY i.visit ORDER BY n DESC LIMIT 20`).bind(...bind).all(),
    env.DB.prepare(
      `SELECT ${BIOMARKERS.map(([k]) => `SUM(COALESCE(b.${k},0)) AS ${k}`).join(", ")},
              SUM(CASE WHEN i.has_biomarkers=1 THEN 1 ELSE 0 END) AS _labelled ${base}`
    ).bind(...bind).first(),
  ]);

  return Response.json({
    total: countRow.n,
    page, per_page: per,
    results: rows.results,
    facets: {
      trial: fTrial.results.filter(r => r.v),
      eye: fEye.results.filter(r => r.v),
      visit: fVisit.results.filter(r => r.v),
      labelled: fBio._labelled || 0,
      biomarkers: BIOMARKERS.map(([k, label]) => ({ key: k, label, count: fBio[k] || 0 }))
                            .filter(x => x.count > 0)
                            .sort((a, b) => b.count - a.count),
    },
  }, { headers: { "cache-control": "public, max-age=60" } });
}
