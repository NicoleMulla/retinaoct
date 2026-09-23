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

/** Build a WHERE clause + bindings from query params. */
export function buildFilter(url) {
  const p = url.searchParams;
  const where = [], bind = [];
  const list = (n) => (p.get(n) || "").split(",").map(s => s.trim()).filter(Boolean);

  const trials = list("trial");
  if (trials.length) { where.push(`i.trial IN (${trials.map(() => "?").join(",")})`); bind.push(...trials); }

  const eyes = list("eye").filter(e => e === "OD" || e === "OS");
  if (eyes.length) { where.push(`i.eye IN (${eyes.map(() => "?").join(",")})`); bind.push(...eyes); }

  const visits = list("visit");
  if (visits.length) { where.push(`i.visit IN (${visits.map(() => "?").join(",")})`); bind.push(...visits); }

  for (const k of list("bio")) if (KEYS.has(k)) where.push(`b.${k} = 1`);

  if (p.get("has_bio") === "1") where.push("i.has_biomarkers = 1");

  for (const [param, col, op] of [["bcva_min","bcva",">="],["bcva_max","bcva","<="],
                                  ["cst_min","cst",">="],["cst_max","cst","<="]]) {
    const v = parseFloat(p.get(param));
    if (!Number.isNaN(v)) { where.push(`i.${col} ${op} ?`); bind.push(v); }
  }

  const q = (p.get("q") || "").trim();
  if (q) {
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
