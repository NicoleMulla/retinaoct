import { BIOMARKERS, buildFilter, SORTS } from "./_lib.js";

/**
 * Faceted search over the OLIVES index.
 *
 * D1 charges per row read, and computing facets across 78,283 rows costs
 * ~400k reads per call — enough to exhaust the free tier in a dozen requests.
 * Two mitigations:
 *   1. Unfiltered requests (the common case) serve precomputed counts from a
 *      single row in `facets_global` — ~25 reads instead of ~400,000.
 *   2. `facets=0` skips facet computation entirely, so paging through results
 *      does not recompute them.
 * Responses are edge-cached, so repeat visitors cost nothing at all.
 */
export async function onRequestGet({ request, env }) {
  try {
    const url = new URL(request.url);
    const { sql: where, bind } = buildFilter(url);
    const filtered = where !== "";
    const needBioJoin = /\bb\./.test(where);
    const join = needBioJoin ? "LEFT JOIN biomarkers b ON b.image_id = i.id" : "";
    const base = `FROM images i ${join} ${where}`;

    const per = Math.min(parseInt(url.searchParams.get("per_page")) || 24, 100);
    const page = Math.max(parseInt(url.searchParams.get("page")) || 1, 1);
    const order = SORTS[url.searchParams.get("sort")] || SORTS.relevant;
    const wantFacets = url.searchParams.get("facets") !== "0";

    const rowsQ = env.DB.prepare(
      `SELECT i.id, i.trial, i.arm, i.subject, i.visit, i.eye, i.scan_index,
              i.patient_id, i.eye_id, i.bcva, i.cst,
              i.has_biomarkers, i.biomarker_count, i.thumb_key
       ${base} ORDER BY ${order} LIMIT ? OFFSET ?`
    ).bind(...bind, per, (page - 1) * per);

    // ---- fast path: no filters -> precomputed facets, no table scans ----
    if (!filtered) {
      const [rows, g] = await Promise.all([
        rowsQ.all(),
        wantFacets ? env.DB.prepare("SELECT payload FROM facets_global WHERE id=1").first() : null,
      ]);
      const f = g ? JSON.parse(g.payload) : null;
      return json({
        total: f ? f.total : null,
        page, per_page: per,
        results: rows.results,
        facets: f ? shape(f) : null,
      }, 3600);
    }

    // ---- filtered: compute against the matching subset ----
    const tasks = [
      env.DB.prepare(`SELECT COUNT(*) AS n ${base}`).bind(...bind).first(),
      rowsQ.all(),
    ];
    if (wantFacets) {
      const bioBase = needBioJoin ? base : `FROM images i LEFT JOIN biomarkers b ON b.image_id = i.id ${where}`;
      tasks.push(
        env.DB.prepare(`SELECT i.trial AS v, COUNT(*) AS n ${base} GROUP BY i.trial ORDER BY n DESC`).bind(...bind).all(),
        env.DB.prepare(`SELECT i.eye AS v, COUNT(*) AS n ${base} GROUP BY i.eye ORDER BY n DESC`).bind(...bind).all(),
        env.DB.prepare(`SELECT i.visit AS v, COUNT(*) AS n ${base} GROUP BY i.visit ORDER BY n DESC LIMIT 20`).bind(...bind).all(),
        env.DB.prepare(
          `SELECT ${BIOMARKERS.map(([k]) => `SUM(COALESCE(b.${k},0)) AS ${k}`).join(", ")},
                  SUM(CASE WHEN i.has_biomarkers=1 THEN 1 ELSE 0 END) AS labelled ${bioBase}`
        ).bind(...bind).first()
      );
    }
    const [countRow, rows, fTrial, fEye, fVisit, fBio] = await Promise.all(tasks);

    return json({
      total: countRow.n,
      page, per_page: per,
      results: rows.results,
      facets: wantFacets ? {
        trial: fTrial.results.filter(r => r.v),
        eye: fEye.results.filter(r => r.v),
        visit: fVisit.results.filter(r => r.v),
        labelled: fBio.labelled || 0,
        biomarkers: BIOMARKERS.map(([k, label]) => ({ key: k, label, count: fBio[k] || 0 }))
                              .filter(x => x.count > 0).sort((a, b) => b.count - a.count),
      } : null,
    }, 600);

  } catch (err) {
    const msg = String(err && err.message || err);
    const quota = msg.includes("row read limit");
    return Response.json(
      { error: quota ? "quota" : "search failed", detail: msg },
      { status: quota ? 503 : 500 });
  }
}

const LABEL = Object.fromEntries(BIOMARKERS);
function shape(f) {
  return {
    trial: f.trial, eye: f.eye, visit: f.visit, labelled: f.labelled,
    biomarkers: Object.entries(f.biomarkers)
      .map(([key, count]) => ({ key, label: LABEL[key] || key, count }))
      .filter(x => x.count > 0).sort((a, b) => b.count - a.count),
  };
}
function json(body, maxAge) {
  return Response.json(body, {
    headers: { "cache-control": `public, max-age=${maxAge}, stale-while-revalidate=86400` },
  });
}
