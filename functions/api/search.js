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
    // INNER, not LEFT. Every biomarker predicate buildFilter emits is
    // `b.<col> = 1`, which discards unmatched rows anyway, so the two are
    // semantically identical here and this states the intent plainly.
    //
    // It is NOT the fix for the row-read problem, though an earlier commit
    // message claimed it was: EXPLAIN QUERY PLAN gives byte-identical plans
    // either way, because SQLite recognises that a strict WHERE on the right
    // table makes a LEFT JOIN inner and rewrites it. Measured cost was
    // unchanged at 1,293,782 rows for a `bio=drt_me` search. What actually
    // reduced it was collapsing the four facet scans into one (below) and,
    // once applied, the partial indexes in migration 003.
    const join = needBioJoin ? "JOIN biomarkers b ON b.image_id = i.id" : "";
    const base = `FROM images i ${join} ${where}`;

    const per = Math.min(parseInt(url.searchParams.get("per_page")) || 24, 100);
    const page = Math.max(parseInt(url.searchParams.get("page")) || 1, 1);
    const order = SORTS[url.searchParams.get("sort")] || SORTS.relevant;
    const wantFacets = url.searchParams.get("facets") !== "0";
    const debug = url.searchParams.get("debug") === "1" ? {} : null;

    const rowsQ = env.DB.prepare(
      `SELECT i.id, i.trial, i.arm, i.subject, i.visit, i.eye, i.scan_index,
              i.patient_id, i.eye_id, i.bcva, i.cst,
              i.has_biomarkers, i.biomarker_count, i.thumb_key, i.full_key, i.label_source
       ${base} ORDER BY ${order} LIMIT ? OFFSET ?`
    ).bind(...bind, per, (page - 1) * per);

    // ---- fast path: no filters -> precomputed facets, no table scans ----
    if (!filtered) {
      const [rows, g] = await Promise.all([
        rowsQ.all(),
        env.DB.prepare("SELECT payload FROM facets_global WHERE id=1").first(),
      ]);
      const f = JSON.parse(g.payload);
      auditRows(rows.meta, "results_default_sort", debug);
      return json({
        total: f.total,                  // always present: the pager depends on it
        page, per_page: per,
        results: rows.results,
        facets: wantFacets ? shape(f) : null,
        ...(debug ? { _rows_read: debug } : {}),
      }, 3600);
    }

    // ---- filtered: compute against the matching subset ----
    // One pass, not four. COUNT(*) and the trial/eye/visit facets were four
    // separate queries over the same subset, each scanning it end to end
    // (measured: 187,706 + 306,092 + 306,092 + 306,138 row reads for a single
    // `bio=drt_me` search). Grouping by all three dimensions at once returns a
    // few dozen rows -- every distinct trial/eye/visit combination in the
    // subset -- from which each facet and the total are derived in JS below.
    const tasks = [
      env.DB.prepare(
        `SELECT i.trial AS trial, i.eye AS eye, i.visit AS visit, COUNT(*) AS n
         ${base} GROUP BY i.trial, i.eye, i.visit`
      ).bind(...bind).all(),
      rowsQ.all(),
    ];
    if (wantFacets) {
      const bioBase = needBioJoin ? base : `FROM images i LEFT JOIN biomarkers b ON b.image_id = i.id ${where}`;
      tasks.push(
        env.DB.prepare(
          `SELECT ${BIOMARKERS.map(([k]) => `SUM(COALESCE(b.${k},0)) AS ${k}`).join(", ")},
                  SUM(CASE WHEN i.label_source='expert' THEN 1 ELSE 0 END) AS labelled,
                  SUM(CASE WHEN i.label_source='model'  THEN 1 ELSE 0 END) AS modelled ${bioBase}`
        ).bind(...bind).all()
      );
    }
    const [dimsQ, rows, fBioQ] = await Promise.all(tasks);
    auditRows(rows.meta, "results_filtered", debug);
    auditRows(dimsQ.meta, "count_and_dim_facets", debug);
    if (wantFacets) auditRows(fBioQ.meta, "facet_biomarkers", debug);

    // Roll the grouped rows up into one list per dimension.
    let total = 0;
    const tally = { trial: new Map(), eye: new Map(), visit: new Map() };
    for (const r of dimsQ.results) {
      total += r.n;
      for (const dim of ["trial", "eye", "visit"]) {
        const v = r[dim];
        if (v == null || v === "") continue;
        tally[dim].set(v, (tally[dim].get(v) || 0) + r.n);
      }
    }
    const facet = (dim, limit) => {
      const out = [...tally[dim]].map(([v, n]) => ({ v, n })).sort((a, b) => b.n - a.n);
      return limit ? out.slice(0, limit) : out;
    };
    const fBio = fBioQ ? fBioQ.results[0] : null;

    return json({
      total,
      ...(debug ? { _rows_read: debug } : {}),
      page, per_page: per,
      results: rows.results,
      facets: wantFacets ? {
        trial: facet("trial"),
        eye: facet("eye"),
        visit: facet("visit", 20),
        labelled: fBio ? fBio.labelled || 0 : 0,
        modelled: fBio ? fBio.modelled || 0 : 0,
        biomarkers: BIOMARKERS.map(([k, label]) => ({ key: k, label, count: fBio ? fBio[k] || 0 : 0 }))
                              .filter(x => x.count > 0).sort((a, b) => b.count - a.count),
      } : null,
    }, 86400);

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
/* The default sort depends on idx_img_sort_default. That index was added
   straight to D1 once and vanished when the table was rebuilt from a dump that
   did not carry it — and nothing failed, queries simply went back to reading
   all 153,045 rows, which burns D1's daily free allowance in ~32 page views.
   D1 reports rows_read per query, so make the regression loud: warn in the
   logs, and expose the counts behind ?debug=1 so one curl can check. */
const EXPECTED_MAX_ROWS = 500;

function auditRows(meta, label, debug) {
  const read = meta && typeof meta.rows_read === "number" ? meta.rows_read : null;
  if (read !== null && read > EXPECTED_MAX_ROWS) {
    console.warn(`[d1] ${label} read ${read} rows, expected <= ${EXPECTED_MAX_ROWS}. ` +
      `idx_img_sort_default may be missing - apply scripts/migrations/001_sort_default_index.sql`);
  }
  if (debug) debug[label] = read;
  return read;
}

function json(body, maxAge) {
  return Response.json(body, {
    headers: {
      "cache-control": `public, max-age=0, must-revalidate, s-maxage=${maxAge}, stale-while-revalidate=86400`,
      "vary": "accept-encoding",
    },
  });
}
