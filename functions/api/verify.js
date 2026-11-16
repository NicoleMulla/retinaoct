/**
 * Records a reviewer's verdict on one biomarker call.
 *
 *   POST /api/verify
 *   {"image_id": 25795, "biomarker": "drt_me", "verdict": "correct",
 *    "shown_present": true, "source": "expert"}
 *
 * `verdict: null` clears a previously recorded verdict, so a mis-click can be
 * undone rather than left in the record.
 *
 * Refuses everything unless app_settings.verification_enabled is '1'. That
 * switch is the only thing standing between this endpoint and the open
 * internet: there is no per-user authentication here, so while it is on,
 * anyone who knows the URL can write verdicts. Two consequences worth keeping
 * in mind — turn it off when a review session is over, and treat the verdicts
 * as attributable to "someone", not to a named reviewer.
 *
 * Writes are capped per request to one row, and the primary key is
 * (image_id, biomarker), so repeated judging of the same biomarker replaces
 * rather than accumulates. D1's free tier allows 100,000 row writes a day.
 */
import { BIOMARKERS } from "./_lib.js";

const KEYS = new Set(BIOMARKERS.map(([k]) => k));
const VERDICTS = new Set(["correct", "incorrect"]);

const fail = (status, error, extra = {}) =>
  Response.json({ error, ...extra }, { status, headers: { "cache-control": "no-store" } });

async function enabled(env) {
  try {
    const row = await env.DB.prepare(
      "SELECT value FROM app_settings WHERE key = 'verification_enabled'"
    ).first();
    return !!row && String(row.value) === "1";
  } catch {
    return false;
  }
}

export async function onRequestPost({ request, env }) {
  if (!(await enabled(env))) {
    return fail(403, "Verification mode is not enabled.", { code: "disabled" });
  }

  let body;
  try { body = await request.json(); }
  catch { return fail(400, "Expected a JSON body.", { code: "bad_json" }); }

  const id = parseInt(body && body.image_id, 10);
  if (!Number.isInteger(id) || id < 1) {
    return fail(400, "image_id must be a positive integer.", { code: "bad_image_id" });
  }

  const biomarker = String((body && body.biomarker) || "");
  if (!KEYS.has(biomarker)) {
    return fail(400, "Unknown biomarker.", { code: "bad_biomarker" });
  }

  const verdict = body && body.verdict == null ? null : String(body.verdict);
  if (verdict !== null && !VERDICTS.has(verdict)) {
    return fail(400, "verdict must be 'correct', 'incorrect' or null.", { code: "bad_verdict" });
  }

  try {
    if (verdict === null) {
      await env.DB.prepare(
        "DELETE FROM verifications WHERE image_id = ? AND biomarker = ?"
      ).bind(id, biomarker).run();
      return Response.json({ image_id: id, biomarker, verdict: null },
                           { headers: { "cache-control": "no-store" } });
    }

    // What was on screen when the call was judged. Without it, a verdict
    // cannot be interpreted after the underlying prediction changes.
    const shown = body && body.shown_present;
    const source = body && body.source;
    await env.DB.prepare(
      `INSERT INTO verifications (image_id, biomarker, verdict, shown_present, source, updated_at)
       VALUES (?, ?, ?, ?, ?, ?)
       ON CONFLICT(image_id, biomarker) DO UPDATE SET
         verdict = excluded.verdict,
         shown_present = excluded.shown_present,
         source = excluded.source,
         updated_at = excluded.updated_at`
    ).bind(id, biomarker, verdict,
           shown == null ? null : (shown ? 1 : 0),
           source === "expert" || source === "model" ? source : null,
           new Date().toISOString()).run();

    return Response.json({ image_id: id, biomarker, verdict },
                         { headers: { "cache-control": "no-store" } });
  } catch (e) {
    return fail(500, "Could not record that verdict.",
                { code: "write_failed", detail: String(e && e.message || e) });
  }
}

export const onRequestGet = () =>
  fail(405, "POST a verdict to this endpoint.", { code: "method_not_allowed" });
