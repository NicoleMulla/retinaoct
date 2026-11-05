// Schema self-check, reachable with no credentials at all.
//
// This exists because of a failure that has now happened twice: an index or a
// table gets applied straight to D1, nothing records it in this repo, and a
// later rebuild silently drops it. There is no error — queries just start
// reading the whole table, and the only symptom is the daily row-read
// allowance disappearing. The one token this project has (retinaoct-deploy)
// cannot read D1, so scripts/check_schema.sh could not run without a
// human minting a new token. The Worker already holds the DB binding, so the
// check belongs here.
//
// It reads only sqlite_master: table and index definitions for a public
// research dataset, already mirrored in scripts/sql/. No rows, no patient
// data, no secrets.

// Only indexes the query paths actually depend on, so that a failure here
// always means something real. Every one is created by
// scripts/build_olives_index.py, which is what a rebuild runs.
const REQUIRED_INDEXES = {
  images: ["idx_img_trial", "idx_img_eye", "idx_img_patient", "idx_img_eyeid",
           "idx_img_visit", "idx_img_hasbio", "idx_img_bcva", "idx_img_cst",
           "idx_img_sort_default"],
  // Partial indexes on the selective biomarker flags. Without them a filtered
  // search reads all 153,046 biomarker rows. The five flags present in 32-68%
  // of the table are deliberately unindexed -- an index saves little there and
  // costs more write quota than a day allows. See migration 003 for the
  // arithmetic.
  biomarkers: ["idx_bm_ped_serous", "idx_bm_rpe_disruption", "idx_bm_vmt",
               "idx_bm_dril", "idx_bm_atrophy_thinning", "idx_bm_shrm",
               "idx_bm_fluid_srf", "idx_bm_ir_hemorrhages",
               "idx_bm_ez_disruption", "idx_bm_preretinal_tissue",
               "idx_bm_drt_me"],
};

export async function onRequest({ env }) {
  const json = (body, status = 200) =>
    new Response(JSON.stringify(body, null, 2), {
      status,
      headers: {
        "content-type": "application/json; charset=utf-8",
        "cache-control": "no-store",
      },
    });

  let rows, rowsRead = null;
  try {
    const q = await env.DB.prepare(
      "SELECT type, name, tbl_name, sql FROM sqlite_master " +
      "WHERE name NOT LIKE 'sqlite_%' ORDER BY tbl_name, type DESC, name"
    ).all();
    rows = q.results || [];
    rowsRead = q.meta && typeof q.meta.rows_read === "number" ? q.meta.rows_read : null;
  } catch (e) {
    return json({ ok: false, error: String(e && e.message || e) }, 503);
  }

  const indexesByTable = {};
  for (const r of rows) {
    if (r.type !== "index") continue;
    (indexesByTable[r.tbl_name] ||= []).push(r.name);
  }

  const missing = [];
  for (const [table, required] of Object.entries(REQUIRED_INDEXES)) {
    const have = new Set(indexesByTable[table] || []);
    for (const idx of required) if (!have.has(idx)) missing.push(`${table}.${idx}`);
  }

  // Any table a query filters by image_id needs an index on it, or every
  // lookup scans. Report which ones have no index mentioning the column so a
  // new table cannot quietly arrive without one.
  const unindexedByImageId = [];
  for (const r of rows) {
    if (r.type !== "table" || !r.sql || !/\bimage_id\b/i.test(r.sql)) continue;
    const ddl = (indexesByTable[r.name] || [])
      .map((n) => rows.find((x) => x.type === "index" && x.name === n))
      .map((x) => (x && x.sql) || "")
      .join(" ");
    const pkIsImageId = /image_id[^,]*\bprimary key\b/i.test(r.sql);
    if (!pkIsImageId && !/\bimage_id\b/i.test(ddl)) unindexedByImageId.push(r.name);
  }

  return json({
    ok: missing.length === 0 && unindexedByImageId.length === 0,
    missing_indexes: missing,
    tables_filtering_image_id_without_an_index: unindexedByImageId,
    rows_read: rowsRead,
    schema: rows.map((r) => ({ type: r.type, name: r.name, table: r.tbl_name, sql: r.sql })),
  }, missing.length || unindexedByImageId.length ? 500 : 200);
}
