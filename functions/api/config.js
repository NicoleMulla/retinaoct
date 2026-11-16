/**
 * Runtime switches the front end is allowed to know about.
 *
 * Only one so far: whether verification mode exists at all. The grid asks for
 * this when, and only when, someone arrives with ?mode=verification, so an
 * ordinary visit costs nothing.
 *
 * The answer lives in D1 (`app_settings`), not in an environment variable, so
 * it can be flipped without a deploy:
 *
 *   UPDATE app_settings SET value='1' WHERE key='verification_enabled';
 *
 * Edge-cached for a minute. That is the lag between flipping the row and the
 * site following, which is the price of not paying a D1 read per page view.
 */
const TTL = 60;

export async function onRequestGet({ request, env, waitUntil }) {
  const cache = caches.default;
  const hit = await cache.match(request);
  if (hit) return hit;

  let verification = false;
  try {
    const row = await env.DB.prepare(
      "SELECT value FROM app_settings WHERE key = 'verification_enabled'"
    ).first();
    verification = !!row && String(row.value) === "1";
  } catch {
    // A missing table or an exhausted read allowance both mean the same thing
    // to a visitor: no verification mode. Failing closed is the safe default
    // for a switch that turns on database writes.
    verification = false;
  }

  const res = Response.json({ verification }, {
    headers: {
      "cache-control": `public, max-age=0, must-revalidate, s-maxage=${TTL}`,
    },
  });
  waitUntil(cache.put(request, res.clone()));
  return res;
}
