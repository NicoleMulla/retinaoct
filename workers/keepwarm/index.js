/**
 * Pokes retinaoct.com/api/warm on a schedule so the model never goes idle.
 *
 * It calls the site rather than HuggingFace directly, so the HF token stays in
 * the one place that already holds it (the Pages project) and is not copied
 * into a second Worker.
 *
 * Costs no GPU: /api/warm asks for the Space root, never an inference path.
 */
// wait=1 so the request is held for the whole boot. Without it the call
// returns in ~0.2s and the wake is left to waitUntil, which is cut short
// before HuggingFace finishes -- enough to keep a running Space awake, never
// enough to bring a sleeping one back.
const TARGET = "https://retinaoct.com/api/warm?wait=1";

async function poke() {
  const started = Date.now();
  try {
    const r = await fetch(`${TARGET}&src=cron`, {
      method: "GET",
      headers: { "user-agent": "retinaoct-keepwarm/1.0" },
      signal: AbortSignal.timeout(120000),
    });
    console.log(`warm ${r.status} in ${Date.now() - started}ms`);
    return r.ok;
  } catch (e) {
    console.log(`warm failed after ${Date.now() - started}ms: ${e && e.name}`);
    return false;
  }
}

export default {
  async scheduled(event, env, ctx) {
    ctx.waitUntil(poke());
  },
  // Lets the schedule be exercised by hand without waiting for the next tick.
  async fetch() {
    const ok = await poke();
    return new Response(ok ? "poked\n" : "poke failed\n", { status: ok ? 200 : 502 });
  },
};
