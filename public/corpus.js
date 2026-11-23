(function(){
/**
 * The whole searchable corpus, in memory.
 *
 * Search, filtering, faceting, sorting and paging all happen here instead of
 * in D1. The corpus is static, so querying it per click was the wrong shape:
 * a filtered search cost ~460,000 D1 row reads against a 5,000,000 daily
 * allowance, and about a dozen of them took the site down. One 580 KB
 * download — cached at the edge and in the browser — replaces all of it, and
 * filtering becomes instant because nothing leaves the page.
 *
 * D1 is still the source of truth, and the detail panel still asks it for
 * what is not here (model confidences, patient demographics). If the corpus
 * fails to load the grid falls back to /api/search, so this is an
 * accelerator, not a hard dependency.
 */
/* Display labels. These live in functions/api/_lib.js for the API; the pair
   must stay in step, and a mismatch shows up immediately as a raw key in the
   sidebar. */
const LABELS = {
  fluid_irf:"Intraretinal fluid (IRF)", fluid_srf:"Subretinal fluid (SRF)",
  ir_hrf:"Intraretinal hyperreflective foci", drt_me:"Diffuse retinal thickening / ME",
  ez_disruption:"Ellipsoid zone disruption", dril:"DRIL",
  ir_hemorrhages:"Intraretinal haemorrhages",
  atrophy_thinning:"Atrophy / thinning of retinal layers",
  rpe_disruption:"RPE disruption", ped_serous:"PED (serous)", shrm:"SHRM",
  preretinal_tissue:"Preretinal tissue / haemorrhage",
  vitreous_partial:"Partially attached vitreous face",
  vitreous_full:"Fully attached vitreous face",
  vitreous_debris:"Vitreous debris", vmt:"Vitreomacular traction",
};

let C = null;                     // the decoded corpus, or null if unavailable

function ready() { return C !== null; }

async function loadCorpus() {
  try {
    const r = await fetch("/data/corpus.json", { cache: "force-cache" });
    if (!r.ok) return false;
    const d = await r.json();
    if (!d || !d.n || !Array.isArray(d.flags)) return false;
    d.bmIndex = Object.fromEntries(d.biomarkers.map((k, i) => [k, i]));
    // Lower-cased once so a keystroke does not re-case 153,045 strings.
    d.pathsLc = d.paths.map(p => p.toLowerCase());
    C = d;
    return true;
  } catch { return false; }
}

/* `pk` packs the enumerated columns: trial:1 eye:1 source:2 visit:6 arm:3
   subject:9. Reading a field is a shift and a mask rather than an object
   lookup, which matters when the inner loop runs 153,045 times per keystroke. */
const TRIAL = i => C.pk[i] & 1;
const EYE   = i => (C.pk[i] >> 1) & 1;
const SRC   = i => (C.pk[i] >> 2) & 3;
const VISIT = i => (C.pk[i] >> 4) & 63;
const ARM   = i => (C.pk[i] >> 10) & 7;
const SUBJ  = i => (C.pk[i] >> 13) & 511;

const idxOf = (list, v) => list.indexOf(v);

/** Which rows match. Returns an array of 0-based positions, id = pos + 1. */
function match(s) {
  const bmOn  = (s.bio || []).map(k => C.bmIndex[k]).filter(i => i != null);
  const bmOff = (s.bio_not || []).map(k => C.bmIndex[k]).filter(i => i != null);
  const trOn  = (s.trial || []).map(v => idxOf(C.trial, v)).filter(i => i >= 0);
  const trOff = (s.trial_not || []).map(v => idxOf(C.trial, v)).filter(i => i >= 0);
  const eyOn  = (s.eye || []).map(v => idxOf(C.eye, v)).filter(i => i >= 0);
  const eyOff = (s.eye_not || []).map(v => idxOf(C.eye, v)).filter(i => i >= 0);
  const viOn  = (s.visit || []).map(v => idxOf(C.visit, v)).filter(i => i >= 0);
  const viOff = (s.visit_not || []).map(v => idxOf(C.visit, v)).filter(i => i >= 0);
  const srcOn = (s.source || []).map(v => C.sources.indexOf(v)).filter(i => i > 0);

  const q = (s.q || "").trim().toLowerCase();
  const useQ = q.length >= 3;
  const bMin = s.bcva_min === "" ? null : +s.bcva_min;
  const bMax = s.bcva_max === "" ? null : +s.bcva_max;
  const cMin = s.cst_min === "" ? null : +s.cst_min;
  const cMax = s.cst_max === "" ? null : +s.cst_max;
  const verified = s.verified ? new Set(s.verifiedIds || []) : null;

  const out = [];
  for (let i = 0; i < C.n; i++) {
    const f = C.flags[i];
    let ok = true;
    for (const b of bmOn)  if (!(f & (1 << b))) { ok = false; break; }
    if (ok) for (const b of bmOff) if (f & (1 << b)) { ok = false; break; }
    if (!ok) continue;

    if (trOn.length  && !trOn.includes(TRIAL(i))) continue;
    if (trOff.length &&  trOff.includes(TRIAL(i))) continue;
    if (eyOn.length  && !eyOn.includes(EYE(i)))   continue;
    if (eyOff.length &&  eyOff.includes(EYE(i)))  continue;
    if (viOn.length  && !viOn.includes(VISIT(i))) continue;
    if (viOff.length &&  viOff.includes(VISIT(i))) continue;
    if (srcOn.length && !srcOn.includes(SRC(i)))  continue;
    if (verified && !verified.has(i + 1)) continue;

    if (bMin !== null && !(C.bcva[i] && C.bcva[i] >= bMin)) continue;
    if (bMax !== null && !(C.bcva[i] && C.bcva[i] <= bMax)) continue;
    if (cMin !== null && !(C.cst[i]  && C.cst[i]  >= cMin)) continue;
    if (cMax !== null && !(C.cst[i]  && C.cst[i]  <= cMax)) continue;

    if (useQ && !C.pathsLc[i].includes(q)) continue;
    out.push(i);
  }
  return out;
}

/** Facet counts over a matched set — exact, and free. */
function facets(hits) {
  const trial = new Map(), eye = new Map(), visit = new Map();
  const bm = new Array(C.biomarkers.length).fill(0);
  let labelled = 0, modelled = 0;
  const bump = (m, k) => m.set(k, (m.get(k) || 0) + 1);
  for (const i of hits) {
    bump(trial, C.trial[TRIAL(i)]);
    bump(eye,   C.eye[EYE(i)]);
    bump(visit, C.visit[VISIT(i)]);
    const s = SRC(i);
    if (s === 1) labelled++; else if (s === 2) modelled++;
    const f = C.flags[i];
    for (let b = 0; b < bm.length; b++) if (f & (1 << b)) bm[b]++;
  }
  const list = (m, limit) => {
    const a = [...m].map(([v, n]) => ({ v, n })).sort((x, y) => y.n - x.n);
    return limit ? a.slice(0, limit) : a;
  };
  return {
    trial: list(trial), eye: list(eye), visit: list(visit, 20),
    labelled, modelled,
    biomarkers: C.biomarkers
      .map((key, b) => ({ key, label: LABELS[key] || key, count: bm[b] }))
      .filter(x => x.count > 0).sort((a, b) => b.count - a.count),
  };
}

const SORTS = {
  relevant:   (a, b) => (C.bc[b] > 0) - (C.bc[a] > 0) || C.bc[b] - C.bc[a] || a - b,
  biomarkers: (a, b) => C.bc[b] - C.bc[a] || a - b,
  bcva_desc:  (a, b) => (C.bcva[b] || -1) - (C.bcva[a] || -1) || a - b,
  bcva_asc:   (a, b) => (C.bcva[a] || 1e9) - (C.bcva[b] || 1e9) || a - b,
  cst_desc:   (a, b) => (C.cst[b] || -1) - (C.cst[a] || -1) || a - b,
  cst_asc:    (a, b) => (C.cst[a] || 1e9) - (C.cst[b] || 1e9) || a - b,
};

function sortHits(hits, sort) {
  return hits.sort(SORTS[sort] || SORTS.relevant);
}

const keyFor = (i, kind) =>
  ("web/olives/" + kind + C.paths[i].replace(/ /g, "_")).replace(/\.[^./]+$/, ".webp");

/** One result row, shaped exactly like a row from /api/search. */
function row(i) {
  const path = C.paths[i];
  return {
    id: i + 1,
    trial: C.trial[TRIAL(i)],
    arm: C.arm[ARM(i)],
    subject: C.subject[SUBJ(i)],
    visit: C.visit[VISIT(i)],
    eye: C.eye[EYE(i)],
    scan_index: (path.match(/(\d+)\.[^./]+$/) || [, null])[1] &&
                +path.match(/(\d+)\.[^./]+$/)[1] % 1000,
    patient_id: null,
    eye_id: C.eye_id[i] || null,
    bcva: C.bcva[i] || null,
    cst: C.cst[i] || null,
    has_biomarkers: C.bc[i] > 0 ? 1 : 0,
    biomarker_count: C.bc[i],
    thumb_key: keyFor(i, "thumb"),
    full_key: keyFor(i, "full"),
    label_source: C.sources[SRC(i)] || null,
    path,
  };
}

/** Everything /api/search returns, computed locally. */
function search(state, page, per, wantFacets) {
  const hits = sortHits(match(state), state.sort);
  const start = (page - 1) * per;
  return {
    total: hits.length,
    page, per_page: per,
    results: hits.slice(start, start + per).map(row),
    facets: wantFacets ? facets(hits) : null,
    _local: true,
  };
}

/** Biomarker list for the detail panel, in the API's shape. */
function biomarkersFor(i) {
  const f = C.flags[i], src = C.sources[SRC(i)];
  return C.biomarkers.map((key, b) => ({
    key, label: LABELS[key] || key,
    present: src === "rejected" ? null : (f & (1 << b)) !== 0,
    source: src === "rejected" ? null : src,
    confidence: null,          // only D1 has these
  }));
}

function corpus() { return C; }

window.Corpus = { ready, loadCorpus, match, facets, sortHits, row, search,
                  biomarkersFor, corpus };
})();
