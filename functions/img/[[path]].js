/**
 * Serves OLIVES image derivatives from the private B2 bucket.
 *
 * Uses a B2 application key restricted to read-only access on the `web/`
 * prefix of one bucket, stored as an encrypted Pages secret. B2's auth token
 * is cached for an hour; image responses are cached at the edge for a year,
 * so B2 is hit roughly once per object per PoP rather than once per viewer.
 */
const AUTH_CACHE_KEY = "https://internal.retinaoct/__b2auth";

async function getAuth(env, ctx) {
  const cache = caches.default;
  const hit = await cache.match(AUTH_CACHE_KEY);
  if (hit) return hit.json();

  const basic = btoa(`${env.B2_READ_KEY_ID}:${env.B2_READ_KEY}`);
  const r = await fetch("https://api.backblazeb2.com/b2api/v3/b2_authorize_account", {
    headers: { Authorization: `Basic ${basic}` },
  });
  if (!r.ok) throw new Error(`b2 auth ${r.status}`);
  const d = await r.json();
  const auth = {
    token: d.authorizationToken,
    downloadUrl: d.apiInfo.storageApi.downloadUrl,
  };
  ctx.waitUntil(cache.put(AUTH_CACHE_KEY, new Response(JSON.stringify(auth), {
    headers: { "content-type": "application/json", "cache-control": "max-age=3600" },
  })));
  return auth;
}

export async function onRequestGet({ params, env, waitUntil, request }) {
  const key = Array.isArray(params.path) ? params.path.join("/") : String(params.path || "");
  if (!key.startsWith("web/") || key.includes("..")) {
    return new Response("Not found", { status: 404 });
  }

  const cache = caches.default;
  const cached = await cache.match(request);
  if (cached) return cached;

  let auth;
  try {
    auth = await getAuth(env, { waitUntil });
  } catch {
    return new Response("Upstream auth failed", { status: 502 });
  }

  const url = `${auth.downloadUrl}/file/${env.B2_BUCKET_NAME}/${key.split("/").map(encodeURIComponent).join("/")}`;
  const up = await fetch(url, { headers: { Authorization: auth.token } });
  if (!up.ok) return new Response("Not found", { status: up.status === 404 ? 404 : 502 });

  const res = new Response(up.body, {
    headers: {
      "content-type": up.headers.get("content-type") || "image/webp",
      "cache-control": "public, max-age=31536000, immutable",
      "access-control-allow-origin": "*",
    },
  });
  waitUntil(cache.put(request, res.clone()));
  return res;
}
