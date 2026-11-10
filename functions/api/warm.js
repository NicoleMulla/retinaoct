/**
 * Nudge the model awake before anyone asks it for anything.
 *
 * The Space sleeps when idle, and waking it takes minutes — long enough that
 * the first visitor after a quiet spell reads it as broken. Nothing can make
 * the boot itself faster from here, but the page can start it earlier: this is
 * called when /analyze loads, so the clock begins while the visitor is still
 * choosing a file rather than after they click Analyze.
 *
 * It costs no GPU. ZeroGPU only allocates a slot inside the handler's
 * @spaces.GPU call, and this never reaches one — it asks for the Space root,
 * whose only job is to make HuggingFace start the container.
 *
 * Fire-and-forget by design: the response says nothing about readiness,
 * because a sleeping Space and a running one both answer the root with HTML.
 * Readiness is settled by /api/analyze itself, which is free to ask while the
 * model is down (it 503s without touching a GPU) and returns the analysis the
 * moment it is up.
 */
const fail = (status, error, extra = {}) =>
  Response.json({ error, ...extra }, { status, headers: { "cache-control": "no-store" } });

export async function onRequest({ env }) {
  if (!env.HF_ENDPOINT_URL || !env.HF_TOKEN) {
    return fail(503, "Analysis is not configured on this deployment yet.",
                { code: "not_configured" });
  }

  let origin;
  try {
    origin = new URL(env.HF_ENDPOINT_URL).origin;
  } catch {
    return fail(500, "Endpoint is misconfigured.", { code: "bad_endpoint" });
  }

  // Short timeout: the point is to make the request, not to wait on it. A
  // sleeping Space holds the connection open while it boots, and there is
  // nothing useful to learn by staying on the line.
  try {
    await fetch(origin, {
      method: "GET",
      headers: { authorization: `Bearer ${env.HF_TOKEN}` },
      signal: AbortSignal.timeout(4000),
    });
  } catch {
    // Timed out or refused. The nudge has been delivered either way.
  }

  return Response.json({ poked: true }, {
    headers: { "cache-control": "no-store" },
  });
}
