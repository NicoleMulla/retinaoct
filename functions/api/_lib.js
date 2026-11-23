export const BIOMARKERS = [
  ["fluid_irf",         "Intraretinal fluid (IRF)"],
  ["fluid_srf",         "Subretinal fluid (SRF)"],
  ["ir_hrf",            "Intraretinal hyperreflective foci"],
  ["drt_me",            "Diffuse retinal thickening / ME"],
  ["ez_disruption",     "Ellipsoid zone disruption"],
  ["dril",              "DRIL"],
  ["ir_hemorrhages",    "Intraretinal haemorrhages"],
  ["atrophy_thinning",  "Atrophy / thinning of retinal layers"],
  ["rpe_disruption",    "RPE disruption"],
  ["ped_serous",        "PED (serous)"],
  ["shrm",              "SHRM"],
  ["preretinal_tissue", "Preretinal tissue / haemorrhage"],
  ["vitreous_partial",  "Partially attached vitreous face"],
  ["vitreous_full",     "Fully attached vitreous face"],
  ["vitreous_debris",   "Vitreous debris"],
  ["vmt",               "Vitreomacular traction"],
];
const KEYS = new Set(BIOMARKERS.map(([k]) => k));

/**
 * Biomarkers the model is allowed to predict. The other four had 1-5 positive
 * patients in the 87-patient training set — too few to learn or validate — so
 * the model emits nothing for them and they stay expert-only. See docs/scaling.md.
 */
export const MODEL_BIOMARKERS = new Set([
  "atrophy_thinning", "drt_me", "ez_disruption", "fluid_irf", "fluid_srf",
  "ir_hemorrhages", "ir_hrf", "preretinal_tissue", "shrm",
  "vitreous_debris", "vitreous_full", "vitreous_partial",
]);
export const EXPERT_ONLY = BIOMARKERS.map(([k]) => k).filter(k => !MODEL_BIOMARKERS.has(k));

/** Build a WHERE clause + bindings from query params. */
export function buildFilter(url) {
  const p = url.searchParams;
  const where = [], bind = [];
  const list = (n) => (p.get(n) || "").split(",").map(s => s.trim()).filter(Boolean);

  /* Every facet can be included or EXCLUDED. `trial=PRIME` keeps PRIME;
     `trial_not=PRIME` keeps everything else. Several negated values exclude
     all of them, so `bio_not=a,b` means "neither a nor b" — negation reads as
     AND where inclusion reads as OR, which is what "exclude these" means to
     someone ticking boxes.

     COALESCE on the column, not a bare NOT IN: SQL's NOT IN evaluates to NULL
     rather than true when the column is NULL, so a row with no trial recorded
     would silently vanish from "not PRIME" instead of being kept. */
  const excl = (col, vals) =>
    `COALESCE(${col},'') NOT IN (${vals.map(() => "?").join(",")})`;

  const trials = list("trial");
  if (trials.length) { where.push(`i.trial IN (${trials.map(() => "?").join(",")})`); bind.push(...trials); }
  const trialsNot = list("trial_not");
  if (trialsNot.length) { where.push(excl("i.trial", trialsNot)); bind.push(...trialsNot); }

  const eyes = list("eye").filter(e => e === "OD" || e === "OS");
  if (eyes.length) { where.push(`i.eye IN (${eyes.map(() => "?").join(",")})`); bind.push(...eyes); }
  const eyesNot = list("eye_not").filter(e => e === "OD" || e === "OS");
  if (eyesNot.length) { where.push(excl("i.eye", eyesNot)); bind.push(...eyesNot); }

  const visits = list("visit");
  if (visits.length) { where.push(`i.visit IN (${visits.map(() => "?").join(",")})`); bind.push(...visits); }
  const visitsNot = list("visit_not");
  if (visitsNot.length) { where.push(excl("i.visit", visitsNot)); bind.push(...visitsNot); }

  for (const k of list("bio")) if (KEYS.has(k)) where.push(`b.${k} = 1`);
  /* A negated biomarker cannot use the partial indexes from migration 003 —
     those index only the rows where the flag is set, which is precisely the
     rows this excludes — so it costs a scan of `biomarkers`. That is the same
     order of cost as filtering on one of the unindexed common flags, and the
     response is edge-cached for a day, so it is affordable rather than free. */
  for (const k of list("bio_not")) if (KEYS.has(k)) where.push(`COALESCE(b.${k},0) = 0`);

  if (p.get("has_bio") === "1") where.push("i.has_biomarkers = 1");

  // Provenance filter: expert annotation vs model inference. Reads a column on
  // `images`, which is already scanned, so it costs no extra rows.
  // Accepts a list so the grid can offer "doctor annotated" and "machine
  // annotated" as independent checkboxes. Ticking both is the same query as
  // ticking neither except that it excludes the handful of scans the model
  // declined, so it stays a real filter rather than a no-op.
  // Images someone has judged in verification mode. The subquery scans the
  // verifications table, which holds a handful of rows, and the outer lookup
  // is by primary key — so this stays cheap however large the corpus grows.
  if (p.get("verified") === "1") {
    where.push("i.id IN (SELECT image_id FROM verifications)");
  }

  const sources = list("source").filter(s => s === "expert" || s === "model");
  if (sources.length) {
    where.push(`i.label_source IN (${sources.map(() => "?").join(",")})`);
    bind.push(...sources);
  }

  for (const [param, col, op] of [["bcva_min","bcva",">="],["bcva_max","bcva","<="],
                                  ["cst_min","cst",">="],["cst_max","cst","<="]]) {
    const v = parseFloat(p.get(param));
    if (!Number.isNaN(v)) { where.push(`i.${col} ${op} ?`); bind.push(v); }
  }

  /* A leading-wildcard LIKE cannot use an index, so every text search is a
     full scan of 153,045 rows — measured at 5,821,125 rows across 13 searches,
     which on its own exceeds the daily allowance. One or two characters match
     almost everything while costing exactly as much as a useful search, so
     they are not worth a scan. Three is the shortest term that narrows. */
  const q = (p.get("q") || "").trim();
  if (q && q.length >= 3) {
    where.push("(i.path LIKE ? OR i.subject LIKE ? OR CAST(i.patient_id AS TEXT) = ?)");
    bind.push(`%${q}%`, `%${q}%`, q);
  }
  return { sql: where.length ? "WHERE " + where.join(" AND ") : "", bind };
}

export const SORTS = {
  relevant: "i.has_biomarkers DESC, i.biomarker_count DESC, i.id",
  biomarkers: "i.biomarker_count DESC, i.id",
  bcva_desc: "i.bcva DESC NULLS LAST, i.id",
  bcva_asc:  "i.bcva ASC NULLS LAST, i.id",
  cst_desc:  "i.cst DESC NULLS LAST, i.id",
  cst_asc:   "i.cst ASC NULLS LAST, i.id",
};
