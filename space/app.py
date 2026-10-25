"""
Retina OCT biomarker model, served on ZeroGPU.

ZeroGPU is compatible only with the Gradio SDK, so gradio owns the web server.
The JSON API is attached to the FastAPI app gradio creates, after launching it
with prevent_thread_lock=True. Calling uvicorn.run() here instead would race
gradio's own launcher for the port — that failure sank an earlier revision.

Two surfaces on one process:
  GET  /             Gradio UI, for trying the model on the Hub
  POST /api/analyze  JSON, {"inputs": "<base64>"} -> the handler's verdict dict
  GET  /api/health   liveness

`handler.py` is not vendored here. It is pulled from the model repo alongside
the weights, so the gate logic, thresholds and suppression rules cannot drift
from what was validated.
"""
import base64
import json
import os
import sys

import gradio as gr
import spaces
import torch
from fastapi import Request
from fastapi.responses import JSONResponse
from huggingface_hub import snapshot_download

REPO = os.environ.get("MODEL_REPO", "NicoleMulla/retfound-olives-16bm")
TOKEN = os.environ.get("HF_TOKEN")
MAX_BYTES = 8 * 1024 * 1024

# ZeroGPU checks the quota against the duration a job REQUESTS, not the time it
# actually uses: a function declaring the 60s default is refused once fewer than
# 60s of daily quota remain, even though this inference needs well under one
# second. Asking for little keeps far more of the allowance usable and earns
# higher queue priority.
GPU_DURATION = int(os.environ.get("GPU_DURATION", "20"))

local = os.environ.get("MODEL_DIR") or snapshot_download(
    REPO,
    token=TOKEN,
    allow_patterns=["handler.py", "model.pt", "reference.npz", "serving_config.json"],
)
sys.path.insert(0, local)
from handler import EndpointHandler  # noqa: E402  (needs the path above)

HANDLER = EndpointHandler(local)

# Recalibrated at the serving layer, leaving the trained artefact untouched.
# Measured over 117 images: real OCT from three devices (OLIVES, Kermany, OCTDL)
# tops out at 85.2, while a flat grey fill scores 94.8 and a colour gradient
# 90.8 — all waved through by the shipped loose bound of 96.6, each with a full
# set of sixteen predictions. 88 rejects those and rejects nothing real in the
# sample. Set GATE_LOOSE to restore the original behaviour.
GATE_LOOSE = float(os.environ.get("GATE_LOOSE", "88"))
HANDLER.gate["loose"] = GATE_LOOSE

# ZeroGPU wants models placed on cuda at module import, not lazily inside the
# decorated function: a CUDA emulation layer makes this legal outside @spaces.GPU
# and the real transfer is optimised to happen at startup. Off ZeroGPU (local
# testing) there is no CUDA, so stay on the CPU.
ON_ZERO = bool(os.environ.get("SPACES_ZERO_GPU")) or torch.cuda.is_available()
if ON_ZERO:
    try:
        HANDLER.model.to("cuda")
        print("[startup] model placed on cuda")
    except Exception as exc:                      # fall back rather than fail to boot
        ON_ZERO = False
        print(f"[startup] cuda placement failed ({type(exc).__name__}), staying on cpu")
else:
    print("[startup] no ZeroGPU detected — running on cpu")


# An OCT B-scan is a greyscale cross-section. Measured over 90 real scans from
# three devices, per-pixel colour spread never exceeded 0.65/255; a colour
# photograph starts around 52. Anything above this is not an OCT image, and
# saying so beats running the model and printing sixteen confident numbers for
# a photograph of a cat. Greyscale non-OCT input is left to the distance gate.
COLOUR_LIMIT = float(os.environ.get("COLOUR_LIMIT", "12"))


def _colourfulness(im) -> float:
    """Mean per-pixel (max(RGB) - min(RGB)), 0-255. Greyscale gives ~0."""
    import numpy as np
    from PIL import Image
    small = im.convert("RGB")
    small.thumbnail((256, 256), Image.BILINEAR)
    a = np.asarray(small, dtype=np.int16)
    return float((a.max(2) - a.min(2)).mean())


def _is_quota_error(exc) -> bool:
    """ZeroGPU refuses a job when the daily allowance is spent.

    It surfaces as a message like "You have exceeded your Pro ZeroGPU quota
    (60s requested vs. 30s left). Try again in 1:23:45." The exception type is
    not part of any stable contract, so match on the text instead.
    """
    msg = str(exc).lower()
    return "quota" in msg and ("exceed" in msg or "left" in msg or "try again" in msg)


def _reject(reason: str, distance=None) -> dict:
    """Shape a refusal exactly like the handler's own rejected verdict."""
    return {"verdict": "rejected", "distance": distance, "reason": reason,
            "predictions": None, "notes": [], "license": HANDLER.license,
            "disclaimer": "Research use only. Not a medical device and not "
                          "for diagnostic use."}


@spaces.GPU(duration=GPU_DURATION)
def _infer(blob: str) -> dict:
    return HANDLER({"inputs": blob})


def analyse(blob: str) -> dict:
    """Colour check first — it is free, and it catches the uploads that would
    otherwise make the model look credulous."""
    import base64 as _b64, io as _io
    from PIL import Image as _Image
    try:
        raw = _b64.b64decode(blob) if isinstance(blob, str) else blob
        im = _Image.open(_io.BytesIO(raw))
        colour = _colourfulness(im)
    except Exception:
        colour = 0.0                       # let the handler report the decode error
    if colour > COLOUR_LIMIT:
        return _reject("This is a colour image. OCT B-scans are greyscale "
                       "cross-sections, so this does not appear to be one.")
    return _infer(blob)


def ui(image):
    """Gradio path — returns the same dict the API does, for eyeballing on the Hub."""
    if image is None:
        return {"error": "no image"}
    import io
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    try:
        return analyse(base64.b64encode(buf.getvalue()).decode())
    except Exception as exc:
        if _is_quota_error(exc):
            return {"error": "Today's GPU quota is exhausted. Try again tomorrow.",
                    "code": "quota_exceeded", "detail": str(exc)}
        raise


demo = gr.Interface(
    fn=ui,
    inputs=gr.Image(type="pil", label="OCT B-scan"),
    outputs=gr.JSON(label="Verdict and biomarkers"),
    title="Retina OCT — OLIVES biomarkers",
    description=(
        "RETFound ViT-L/16 fine-tuned on 9,408 expert-annotated OLIVES B-scans. "
        "Predictions are gated by distance from the training distribution. "
        "**Research use only — not a medical device, not for diagnostic use.**"
    ),
)

# gradio owns the server; attach the JSON API to the app it builds.
demo.launch(server_name="0.0.0.0", server_port=int(os.environ.get("PORT", "7860")),
            prevent_thread_lock=True, show_api=False)
app = demo.app


@app.get("/api/health")
def health():
    return {"ok": True, "model": REPO, "biomarkers": len(HANDLER.bm),
            "device": "cuda" if ON_ZERO else "cpu", "gpu_duration": GPU_DURATION}


@app.post("/api/analyze")
async def analyze(request: Request):
    """Accepts {"inputs": base64} or raw image bytes, so curl works too."""
    ctype = (request.headers.get("content-type") or "").lower()
    body = await request.body()
    if len(body) > MAX_BYTES * 2:                 # base64 inflates by ~4/3
        return JSONResponse({"error": "payload too large"}, status_code=413)

    if ctype.startswith("application/json"):
        try:
            payload = json.loads(body)
        except Exception:
            return JSONResponse({"error": "malformed JSON"}, status_code=400)
        blob = payload.get("inputs")
        if blob is None:
            return JSONResponse({"error": "no 'inputs' field"}, status_code=400)
    else:
        blob = base64.b64encode(body).decode()

    try:
        out = analyse(blob)
    except Exception as exc:
        if _is_quota_error(exc):
            # 429 so the website can tell "come back tomorrow" apart from a fault.
            return JSONResponse(
                {"error": "Today's GPU quota is exhausted.",
                 "code": "quota_exceeded", "detail": str(exc)}, status_code=429)
        return JSONResponse(
            {"error": f"inference failed: {type(exc).__name__}"}, status_code=500)

    return JSONResponse(out, status_code=422 if "error" in out else 200)


# Gradio registers a catch-all GET route for its single-page app when it
# launches, and that happened before the routes above were added — so a later
# GET route is shadowed by it and /api/health returned gradio's HTML. Move ours
# to the front of the router. POST was unaffected (the catch-all is GET-only),
# but reordering both keeps it correct if that ever changes.
_MINE = {"/api/health", "/api/analyze"}
for _route in [r for r in app.router.routes if getattr(r, "path", None) in _MINE][::-1]:
    app.router.routes.remove(_route)
    app.router.routes.insert(0, _route)

demo.block_thread()
