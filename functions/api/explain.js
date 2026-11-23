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

/**
 * Fetch an atlas scan by id, for explaining an image already in the corpus
 * rather than one someone uploaded.
 *
 * Goes through our own /img/ route instead of reaching into B2 here: that
 * route already holds the read-only bucket key and an edge cache, and
 * duplicating either would mean a second copy to keep correct.
 *
 * Refuses anything not model-labelled. On an expert-annotated scan the
 * biomarkers on screen are a clinician's judgement, not the model's, so an
 * influence map would answer a question nobody asked — and showing one beside
 * a human annotation implies the model produced it.
 */
async function fetchAtlasImage(env, request, id) {
  const row = await env.DB.prepare(
    "SELECT full_key, label_source FROM images WHERE id = ?"
  ).bind(id).first();
  if (!row) return { err: fail(404, "No such image.", { code: "not_found" }) };
  if (row.label_source !== "model") {
    return { err: fail(409,
      "Influence maps explain the model's own predictions, and this scan's "
      + "biomarkers are expert annotations.", { code: "not_model_labelled" }) };
  }
  if (!row.full_key) return { err: fail(404, "That scan has no image file.", { code: "no_file" }) };

  const src = new URL("/img/" + row.full_key, request.url);
  const r = await fetch(src.toString(), { headers: { accept: "image/*" } });
  if (!r.ok) return { err: fail(502, "Could not read that scan.", { code: "image_unavailable" }) };
  return { buf: new Uint8Array(await r.arrayBuffer()) };
}

export async function onRequestPost({ request, env }) {
  if (!env.HF_ENDPOINT_URL || !env.HF_TOKEN) {
    return fail(503, "Explanations are not configured on this deployment yet.",
                { code: "not_configured" });
  }

  /* Two ways in: raw image bytes (an upload from /analyze) or
     {"image_id": N} for a scan already in the atlas. */
  let buf;
  if ((request.headers.get("content-type") || "").includes("json")) {
    let body;
    try { body = await request.json(); }
    catch { return fail(400, "Expected a JSON body.", { code: "bad_json" }); }
    const id = parseInt(body && body.image_id, 10);
    if (!Number.isInteger(id) || id < 1) {
      return fail(400, "image_id must be a positive integer.", { code: "bad_image_id" });
    }
    const got = await fetchAtlasImage(env, request, id);
    if (got.err) return got.err;
    buf = got.buf;
  } else {
    buf = new Uint8Array(await request.arrayBuffer());
  }

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
    return fail(503, "Starting the model.",
                { code: "cold_start" });
  }
  const ctype = up.headers.get("content-type") || "";
  if (!ctype.includes("json")) {
    return fail(503, "Starting the model.",
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
