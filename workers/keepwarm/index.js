/**
 * Pokes retinaoct.com/api/warm on a schedule so the model never goes idle.
 *
 * It calls the site rather than HuggingFace directly, so the HF token stays in
 * the one place that already holds it (the Pages project) and is not copied
 * into a second Worker.
 *
 * Costs no GPU: /api/warm asks for the Space root, never an inference path.
 */
const TARGET = "https://retinaoct.com/api/warm";

async function poke() {
  const started = Date.now();
  try {
    const r = await fetch(`${TARGET}?src=cron`, {
      method: "GET",
      headers: { "user-agent": "retinaoct-keepwarm/1.0" },
      signal: AbortSignal.timeout(60000),
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
