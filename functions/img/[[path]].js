/**
 * Serves OLIVES image derivatives from the private B2 bucket.
 *
 * Uses a B2 application key restricted to read-only access on the `web/`
 * prefix of one bucket, stored as an encrypted Pages secret. B2's auth token
 * is cached for an hour; image responses are cached at the edge for a year,
 * so B2 is hit roughly once per object per PoP rather than once per viewer.
 *
 * `?dl=<filename>` returns the same bytes as an attachment. The edge cache is
 * keyed on the object path alone, so the inline view and the download share a
 * single cached copy and Content-Disposition is attached per response.
 */
const AUTH_CACHE_KEY = "https://internal.retinaoct/__b2auth";

// CC BY 4.0 obliges attribution to travel with redistributed images.
const ATTRIBUTION =
  "OLIVES dataset (Prabhushankar et al., NeurIPS 2022), CC BY 4.0 — https://retinaoct.com/data-sources";

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

/**
 * Build a safe attachment filename. The client's suggestion is advisory only —
 * it reaches a response header, so anything outside [A-Za-z0-9._-] is dropped
 * rather than escaped, and the extension is taken from the object key.
 */
function safeName(suggested, key) {
  const ext = (key.match(/\.[A-Za-z0-9]{1,5}$/) || [".webp"])[0];
  let base = String(suggested || "")
    .replace(/\.[A-Za-z0-9]{1,5}$/, "")
    .replace(/[^A-Za-z0-9._-]/g, "")
    .replace(/^[.-]+/, "")
    .slice(0, 80);
  if (!base) base = "retinaoct-" + (key.split("/").pop() || "scan").replace(/\.[^.]*$/, "");
  return base + ext;
}

export async function onRequestGet({ params, env, waitUntil, request }) {
  const key = Array.isArray(params.path) ? params.path.join("/") : String(params.path || "");
  if (!key.startsWith("web/") || key.includes("..")) {
    return new Response("Not found", { status: 404 });
  }

  const url = new URL(request.url);
  const dl = url.searchParams.get("dl");

  // Cache on the path alone so `?dl=` does not fork the cache entry.
  const cacheKey = new Request(url.origin + url.pathname, { method: "GET" });
  const cache = caches.default;
  let res = await cache.match(cacheKey);

  if (!res) {
    let auth;
    try {
      auth = await getAuth(env, { waitUntil });
    } catch {
      return new Response("Upstream auth failed", { status: 502 });
    }

    const b2 = `${auth.downloadUrl}/file/${env.B2_BUCKET_NAME}/${key.split("/").map(encodeURIComponent).join("/")}`;
    const up = await fetch(b2, { headers: { Authorization: auth.token } });
    if (!up.ok) return new Response("Not found", { status: up.status === 404 ? 404 : 502 });

    res = new Response(up.body, {
      headers: {
        "content-type": up.headers.get("content-type") || "image/webp",
        "cache-control": "public, max-age=31536000, immutable",
        "access-control-allow-origin": "*",
      },
    });
    waitUntil(cache.put(cacheKey, res.clone()));
  }

  if (dl === null) return res;

  const h = new Headers(res.headers);
  h.set("content-disposition", `attachment; filename="${safeName(dl, key)}"`);
  h.set("x-attribution", ATTRIBUTION);
  return new Response(res.body, { status: res.status, headers: h });
}
