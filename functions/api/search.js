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
export async function onRequestGet(ctx) {
  const { request, env, waitUntil } = ctx;
  // Pages Functions are not edge-cached by default, so cache explicitly.
  // Browsers revalidate every time (max-age=0) while repeats are served from
  // the edge, which is what keeps D1 row reads down.
  const cache = caches.default;
  const hit = await cache.match(request);
  if (hit) return hit;
  const res = await handle(ctx);
  if (res.status === 200) waitUntil(cache.put(request, res.clone()));
  return res;
}

async function handle({ request, env }) {
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
              i.has_biomarkers, i.biomarker_count, i.thumb_key, i.label_source
       ${base} ORDER BY ${order} LIMIT ? OFFSET ?`
    ).bind(...bind, per, (page - 1) * per);

    // ---- fast path: no filters -> precomputed facets, no table scans ----
    if (!filtered) {
      const [rows, g] = await Promise.all([
        rowsQ.all(),
        env.DB.prepare("SELECT payload FROM facets_global WHERE id=1").first(),
      ]);
      const f = JSON.parse(g.payload);
      return json({
        total: f.total,                  // always present: the pager depends on it
        page, per_page: per,
        results: rows.results,
        facets: wantFacets ? shape(f) : null,
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
                  SUM(CASE WHEN i.label_source='expert' THEN 1 ELSE 0 END) AS labelled,
                  SUM(CASE WHEN i.label_source='model'  THEN 1 ELSE 0 END) AS modelled ${bioBase}`
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
        modelled: fBio.modelled || 0,
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
    modelled: f.modelled || 0,
    biomarkers: Object.entries(f.biomarkers)
      .map(([key, count]) => ({ key, label: LABEL[key] || key, count }))
      .filter(x => x.count > 0).sort((a, b) => b.count - a.count),
  };
}
/**
 * Cache at Cloudflare's edge, never in the browser.
 *
 * `max-age=0` makes the browser revalidate every time, so a deployed change to
 * the response shape takes effect immediately instead of being masked by a
 * stale copy. `s-maxage` still lets the edge serve repeats, which is what
 * keeps D1 row reads down.
 */
function json(body, maxAge) {
  return Response.json(body, {
    headers: {
      "cache-control": `public, max-age=0, must-revalidate, s-maxage=${maxAge}, stale-while-revalidate=86400`,
      "vary": "accept-encoding",
    },
  });
}
