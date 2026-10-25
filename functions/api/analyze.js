/**
 * Upload-and-analyze proxy: browser -> here -> our model on HuggingFace.
 *
 * The browser never sees the HF token or the endpoint URL. The upload is held
 * in memory for the length of one request and written nowhere — not to B2, not
 * to D1, not to a log. An uploaded OCT scan may be patient data, and the only
 * safe amount of it to retain is none.
 *
 * Contract matches serving/handler.py: POST {"inputs": "<base64>"} and the
 * handler returns {verdict, distance, predictions[], notes, license, ...}.
 *
 * Bindings (Pages secrets):
 *   HF_ENDPOINT_URL  full URL of the model endpoint — either an HF Inference
 *                    Endpoint or this project's Space route, which serve the
 *                    same contract (see space/app.py)
 *   HF_TOKEN         read token for that endpoint
 */
import { BIOMARKERS } from "./_lib.js";

const MAX_BYTES = 8 * 1024 * 1024;   // generous for a B-scan; bounds worker memory
const LABELS = new Map(BIOMARKERS);

/**
 * Trust the bytes, not the Content-Type header. PIL will decode whatever it is
 * given, so the point of sniffing here is to fail fast and cheaply rather than
 * to pay for a cold GPU start on a PDF.
 */
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

/** btoa() needs a binary string; build it in chunks so 8 MB cannot blow the stack. */
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
    return fail(503, "Analysis is not configured on this deployment yet.",
                { code: "not_configured" });
  }

  const declared = parseInt(request.headers.get("content-length") || "0", 10);
  if (declared > MAX_BYTES) {
    return fail(413, `Image is larger than ${MAX_BYTES / 1024 / 1024} MB.`,
                { code: "too_large" });
  }

  const buf = new Uint8Array(await request.arrayBuffer());
  if (!buf.length) return fail(400, "Empty upload.", { code: "empty" });
  if (buf.length > MAX_BYTES) {
    return fail(413, `Image is larger than ${MAX_BYTES / 1024 / 1024} MB.`,
                { code: "too_large" });
  }

  const kind = sniff(buf);
  if (!kind) {
    return fail(415, "That file is not a PNG, JPEG, TIFF, BMP or WebP image.",
                { code: "unsupported_type" });
  }

  let up;
  try {
    up = await fetch(env.HF_ENDPOINT_URL, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${env.HF_TOKEN}`,
        "content-type": "application/json",
        accept: "application/json",
      },
      body: JSON.stringify({ inputs: toBase64(buf) }),
      signal: AbortSignal.timeout(120000),
    });
  } catch (e) {
    const timedOut = e && (e.name === "TimeoutError" || e.name === "AbortError");
    return fail(504, timedOut
      ? "The model did not respond in time. If it was scaled to zero it may still be starting — try again in a minute."
      : "Could not reach the model endpoint.", { code: "upstream_unreachable" });
  }

  // 503 means the replica is still booting — a normal, retryable state for an
  // endpoint that scales to zero or a Space that has gone to sleep, not a failure.
  if (up.status === 503) {
    return fail(503, "The model is starting up. Try again in about a minute.",
                { code: "cold_start", retry_after: 60 });
  }

  // A sleeping or building Space answers 200 with an HTML holding page rather
  // than JSON. Treat that as a cold start too, not as a broken model.
  const ctype = up.headers.get("content-type") || "";
  if (!ctype.includes("json")) {
    return fail(503, "The model is waking up. Try again in about a minute.",
                { code: "cold_start", retry_after: 60 });
  }

  if (!up.ok && up.status !== 422) {
    return fail(502, `The model endpoint returned ${up.status}.`,
                { code: "upstream_error" });
  }

  let out;
  try { out = await up.json(); }
  catch { return fail(502, "The model returned a malformed response.", { code: "bad_json" }); }

  if (out && out.error) return fail(422, String(out.error), { code: "model_rejected" });

  // Attach display labels here rather than in the browser, so the wire format
  // stays the handler's and the UI has one less mapping to keep in sync.
  if (Array.isArray(out.predictions)) {
    out.predictions = out.predictions.map(p => ({ ...p, label: LABELS.get(p.biomarker) || p.biomarker }));
  }
  if (Array.isArray(out.suppressed)) {
    out.suppressed = out.suppressed.map(k => ({ key: k, label: LABELS.get(k) || k }));
  }
  out.detected_type = kind;

  return Response.json(out, { headers: { "cache-control": "no-store" } });
}

export const onRequestGet = () =>
  fail(405, "POST an image to this endpoint.", { code: "method_not_allowed" });
