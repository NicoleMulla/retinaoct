/**
 * How many images carry at least one reviewer verdict.
 *
 * Its own endpoint rather than a field on /api/search, and that separation is
 * load-bearing. The count has to be fresh — a reviewer who just marked a
 * biomarker expects the sidebar to move — so it cannot be edge-cached. Riding
 * on /api/search would have meant uncaching search itself, and a filtered
 * search costs on the order of 400,000 D1 row reads against a 5M daily
 * allowance. Asking separately keeps search fully cacheable and puts the
 * uncached cost on a COUNT over a table holding a handful of rows.
 *
 * Open to everyone, in every mode: the "Verified images" filter is visible to
 * ordinary visitors, who can see what has been reviewed but not change it.
 * Writing is gated in /api/verify.
 */
export async function onRequestGet({ env }) {
  let verified = 0;
  try {
    const row = await env.DB.prepare(
      "SELECT COUNT(DISTINCT image_id) AS n FROM verifications"
    ).first();
    verified = (row && row.n) || 0;
  } catch {
    verified = 0;   // table absent, or the read allowance is spent
  }
  return Response.json({ verified }, {
    headers: { "cache-control": "no-store" },
  });
}
