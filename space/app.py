"""
Retina OCT biomarker model, served from a free-tier HuggingFace Space.

Two surfaces on one process:
  GET  /            Gradio UI — for trying the model directly on the Hub
  POST /api/analyse JSON, {"inputs": "<base64>"} -> the handler's verdict dict

The JSON route deliberately mirrors the HF Inference Endpoints contract, so
retinaoct.com's Cloudflare proxy talks to either without code changes.

`handler.py` is NOT vendored here. It is pulled from the model repo alongside
the weights, so the gate logic, thresholds and suppression rules can never
drift between what was validated and what is served.
"""
import base64
import os
import sys


import gradio as gr
import torch
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from huggingface_hub import snapshot_download

# Torch's own default thread count is left alone deliberately. Forcing it was
# measured as a regression on this Space: 13-15s per forward pass at the
# default against 18-19s when pinned to the host's 16 cores, which the 2-vCPU
# cgroup cannot actually run in parallel.

REPO = os.environ.get("MODEL_REPO", "NicoleMulla/retfound-olives-16bm")
TOKEN = os.environ.get("HF_TOKEN")
MAX_BYTES = 8 * 1024 * 1024

# Weights live in the model repo, not in this Space: one copy, one source of
# truth, and the Space stays small enough to rebuild quickly. MODEL_DIR points
# at an already-staged copy, which is how this is tested locally.
local = os.environ.get("MODEL_DIR") or snapshot_download(
    REPO,
    token=TOKEN,
    allow_patterns=["handler.py", "model.pt", "reference.npz", "serving_config.json"],
)
sys.path.insert(0, local)
from handler import EndpointHandler  # noqa: E402  (needs the path above)

HANDLER = EndpointHandler(local)

app = FastAPI(title="Retina OCT biomarkers")


@app.get("/api/health")
def health():
    return {"ok": True, "model": REPO, "biomarkers": len(HANDLER.bm),
            "host_cpus": os.cpu_count(), "torch_threads": torch.get_num_threads()}


@app.post("/api/analyse")
async def analyse(request: Request):
    """Accepts {"inputs": base64} — or raw image bytes, so curl works too."""
    ctype = (request.headers.get("content-type") or "").lower()
    body = await request.body()
    if len(body) > MAX_BYTES * 2:                 # base64 inflates by ~4/3
        return JSONResponse({"error": "payload too large"}, status_code=413)

    if ctype.startswith("application/json"):
        try:
            payload = __import__("json").loads(body)
        except Exception:
            return JSONResponse({"error": "malformed JSON"}, status_code=400)
        blob = payload.get("inputs")
        if blob is None:
            return JSONResponse({"error": "no 'inputs' field"}, status_code=400)
    else:
        blob = base64.b64encode(body).decode()

    try:
        out = HANDLER({"inputs": blob})
    except Exception as e:                        # never leak a traceback to the web
        return JSONResponse({"error": f"inference failed: {type(e).__name__}"}, status_code=500)

    return JSONResponse(out, status_code=422 if "error" in out else 200)


def ui(image):
    """Gradio path. Returns the same dict the API does, for eyeballing on the Hub."""
    if image is None:
        return {"error": "no image"}
    import io
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return HANDLER({"inputs": base64.b64encode(buf.getvalue()).decode()})


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

app = gr.mount_gradio_app(app, demo, path="/")

if __name__ == "__main__":
    # Deliberately NOT GRADIO_SERVER_PORT: under the gradio SDK that variable
    # points at a port the platform's own launcher has already bound.
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 7860)))
