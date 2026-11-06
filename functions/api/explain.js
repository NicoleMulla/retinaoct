/**
 * Influence maps: browser -> here -> the model on HuggingFace.
 *
 * Same shape and the same rules as analyze.js — the upload is held for one
 * request and written nowhere, and the token never reaches the browser. This
 * is a separate route rather than a flag on /api/analyze because it costs an
 * extra ~0.9s of GPU and should only run when somebody actually asks.
 *
 * Bindings: HF_ENDPOINT_URL (the Space's /api/analyze), HF_TOKEN.
 */
const MAX_BYTES = 8 * 1024 * 1024;

function sniff(b) {
  const m = (...s) => s.every((v, i) => b[i] === v);
  if (m(0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a)) return "image/png";
  if (m(0xff, 0xd8, 0xff)) return "image/jpeg";
  if (m(0x42, 0x4d)) return "image/bmp";
  if (m(0x49, 0x49, 0x2a, 0x00) || m(0x4d, 0x4d, 0x00, 0x2a)) return "image/tiff";
  if (m(0x52, 0x49, 0x46, 0x46) && b[8] === 0x57 && b[9] === 0x45
      && b[10] === 0x42 && b[11] === 0x50) return "image/webp";
  return null;
}

function toBase64(bytes) {
  let s = "";
  for (let i = 0; i < bytes.length; i += 0x8000) {
    s += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
  }
  return btoa(s);
}

const fail = (status, error, extra = {}) =>
  Response.json({ error, ...extra }, { status, headers: { "cache-control": "no-store" } });

export async function onRequestPost({ request, env }) {
  if (!env.HF_ENDPOINT_URL || !env.HF_TOKEN) {
    return fail(503, "Explanations are not configured on this deployment yet.",
                { code: "not_configured" });
  }
  const buf = new Uint8Array(await request.arrayBuffer());
  if (!buf.length) return fail(400, "Empty upload.", { code: "empty" });
  if (buf.length > MAX_BYTES) {
    return fail(413, `Image is larger than ${MAX_BYTES / 1024 / 1024} MB.`, { code: "too_large" });
  }
  if (!sniff(buf)) {
    return fail(415, "That file is not a PNG, JPEG, TIFF, BMP or WebP image.",
                { code: "unsupported_type" });
  }

  // the Space exposes /api/explain alongside /api/analyze
  const url = env.HF_ENDPOINT_URL.replace(/\/api\/analyze\/?$/, "/api/explain");
  let up;
  try {
    up = await fetch(url, {
      method: "POST",
      headers: { Authorization: `Bearer ${env.HF_TOKEN}`, "content-type": "application/json" },
      body: JSON.stringify({ inputs: toBase64(buf) }),
      signal: AbortSignal.timeout(180000),
    });
  } catch {
    return fail(504, "The model did not respond in time.", { code: "upstream_unreachable" });
  }

  if (up.status === 429) {
    return fail(429, "The quota for today is exceeded. Please try again tomorrow.",
                { code: "quota_exceeded" });
  }
  if (up.status === 503) {
    return fail(503, "Starting the model — this usually takes a few minutes.",
                { code: "cold_start" });
  }
  const ctype = up.headers.get("content-type") || "";
  if (!ctype.includes("json")) {
    return fail(503, "Starting the model — this usually takes a few minutes.",
                { code: "cold_start" });
  }
  if (!up.ok) return fail(502, `The model returned ${up.status}.`, { code: "upstream_error" });

  let out;
  try { out = await up.json(); }
  catch { return fail(502, "Malformed response.", { code: "bad_json" }); }
  return Response.json(out, { headers: { "cache-control": "no-store" } });
}

export const onRequestGet = () =>
  fail(405, "POST an image to this endpoint.", { code: "method_not_allowed" });
