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

export async function onRequest({ env, waitUntil, request }) {
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

  // Hold the request open in the background rather than aborting it. A
  // sleeping Space answers slowly -- a direct wake measured 49s before the
  // first byte -- and cancelling at 4s may cancel the boot it just asked for.
  // waitUntil lets the fetch run on after this handler returns, so the caller
  // gets an instant answer and HuggingFace still gets a request that stays
  // connected long enough to matter.
  // Cache-bust and opt out of the edge cache via cf.cacheTtl. Note: the
  // standard `cache: "no-store"` init field is NOT supported in Workers and
  // throws a TypeError synchronously, which silently broke this endpoint.
  // Cache-bust and opt out of the edge cache. A Worker's fetch() is cached by
  // Cloudflare like any other, and a cached holding page never reaches
  // HuggingFace -- so the request that is supposed to start the container
  // never arrives. Measured: warm returned in 0.2s and the Space stayed
  // SLEEPING 80s later, while the same request made from outside Cloudflare
  // woke it in 49s.
  const url = `${origin}/?warm=${Date.now()}`;
  const poke = fetch(url, {
    method: "GET",
    headers: {
      authorization: `Bearer ${env.HF_TOKEN}`,
      // These two are load-bearing. HuggingFace only boots a sleeping Space
      // for requests that look like a page load: measured on a sleeping Space,
      // a header-less request got 503 in 0.18s and started nothing, while the
      // same request with a User-Agent and an HTML Accept got 200 after 33s
      // and woke it. Workers' fetch() sends no User-Agent by default, so this
      // endpoint silently did nothing for days while still answering 200.
      "user-agent": "Mozilla/5.0 (compatible; RetinaOCT-KeepWarm/1.0; +https://retinaoct.com)",
      accept: "text/html,application/xhtml+xml",
      "cache-control": "no-cache",
    },
    cf: { cacheTtl: 0, cacheEverything: false },
    signal: AbortSignal.timeout(90000),
  });
  // ?debug=1 waits for the poke and reports what came back, so a failure to
  // wake can be diagnosed without guessing. It does not leak the endpoint:
  // only the host, status and timing.
  if (new URL(request.url).searchParams.get("debug") === "1") {
    const t0 = Date.now();
    let status = null, ctype = null, cf = null, err = null, bytes = null;
    try {
      const r = await poke;
      if (r) {
        status = r.status;
        ctype = r.headers.get("content-type");
        cf = r.headers.get("cf-cache-status");
        bytes = (await r.text()).length;
      }
    } catch (e) { err = String(e && e.name || e); }
    return Response.json({
      host: new URL(url).host, status, ctype, cf_cache: cf, bytes, err,
      elapsed_ms: Date.now() - t0,
    }, { headers: { "cache-control": "no-store" } });
  }

  if (waitUntil) waitUntil(poke.catch(() => {}));

  return Response.json({ poked: true }, {
    headers: { "cache-control": "no-store" },
  });
}
