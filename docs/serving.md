# Serving the biomarker model

How `retinaoct.com/analyze` reaches the model, what it costs, and the one step
that is not done.

Investigated 2026-10-24.

---

## Shape

```
browser ──POST image bytes──▶ Cloudflare Pages Function ──POST {"inputs": b64}──▶ model endpoint
                              functions/api/analyze.js                            handler.py
```

The browser never sees the token or the endpoint URL. The upload is held in
memory for one request and written nowhere — not B2, not D1, not logs. An
uploaded OCT scan may be patient data, and the only safe amount to retain is
none.

The proxy's wire format is the HF Inference Endpoints contract. `space/app.py`
serves the identical contract, so the host can change without touching the
website.

---

## handler.py has now actually been run

It was written 2026-09-27 and syntax-checked only, because no trained
checkpoint existed yet. First real execution, against the real weights:

| Input | Verdict | Distance | Gate |
|---|---|---:|---|
| Real OLIVES B-scan (`02-004/W20/OD/13.tif`) | `ok` | 26.9 | strict = 58.07 |
| Random noise, 496×504 | `rejected` | 109.5 | loose = 96.56 |
| Wide 3:1 image | `rejected` | 110.7 | centre-crop note fired |

Model load **2.4 s**, inference **0.28–0.35 s** on CPU. The gate, the
thresholds, the centre-crop path and the suppression of the four untrainable
biomarkers all behave as designed.

## Sizing is measured, not guessed

Peak resident memory across load plus three inferences: **2.81 GB**.

| Instance | vCPU | RAM | $/hr | Verdict |
|---|---:|---:|---:|---|
| `intel-spr x1` | 1 | 2 GB | 0.033 | **OOMs** — 140% of RAM |
| **`intel-spr x2`** | 2 | 4 GB | **0.067** | **fits at 70%** — cheapest that works |
| `intel-spr x4` | 4 | 8 GB | 0.134 | comfortable at 35% |

`x2` is the choice. One caveat: 2.81 GB is 70% of 4 GB, so if the endpoint ever
runs two worker processes it will OOM. If the first deploy dies on startup,
that is the reason — go to `x4`.

With scale-to-zero the cost is dominated by idle-before-scale-down, not by
inference. At 15 minutes warm, one upload costs roughly $0.017.

---

## Host: a private ZeroGPU Space

`NicoleMulla/retinaoct-biomarkers` — private, **ZeroGPU**, free on a PRO
account. Inference went from ~19s on free CPU to **0.69s end-to-end through the
website**, roughly 28x.

| | free CPU (`cpu-basic`) | **ZeroGPU** |
|---|---|---|
| Latency (warm, via the site) | 13-19s, variable | **0.69s** |
| Cost | free | free on PRO |
| Daily limit | none | a GPU-time quota, then a hard stop |

### Quota is a hard stop, by design

The account is `billingMode: prepaid` and holds no credits, so exceeding the
daily GPU allowance cannot bill anything — the request simply fails. The Space
returns **429 / `quota_exceeded`**, the Worker passes it through, and the page
shows "The quota for today is exceeded. Please try again tomorrow." with no
retry and no fallback to a slow CPU path.

`@spaces.GPU(duration=20)` rather than the 60s default: quota is checked
against the duration a job *requests*, not what it uses, so a 60s declaration
is refused once under 60s remains even though inference needs under a second.
Asking for little keeps far more of the allowance usable and raises queue
priority.

### Two gradio-SDK traps

ZeroGPU works **only** with the Gradio SDK, which is what forced the move off
Docker. Two consequences, both found by testing rather than by reading:

1. **The launcher owns the port.** Calling `uvicorn.run()` races it and the
   Space dies with `[Errno 98] address already in use`. Instead,
   `demo.launch(prevent_thread_lock=True)` hands back gradio's own FastAPI app
   and the JSON API is attached to that.
2. **GET routes are shadowed by the SPA.** Gradio registers its single-page
   route at launch, so `/api/health` added afterwards returns gradio's HTML.
   Moving the API routes to the front of the router fixes this *locally* —
   verified, it returns JSON — but the deployed Space still serves the SPA for
   that GET, so the shadowing happens in HuggingFace's own layer in front of
   the Space, not in the app. **POST is unaffected**, which is why
   `/api/analyze` works. `/api/health` is therefore only useful when running
   the app locally; treat a successful `POST /api/analyze` as the liveness
   check in production.

### handler.py is device-agnostic now

It called `.numpy()` on tensors that would live on CUDA. It now follows the
model's device and moves results back to CPU before converting. Verified
output-neutral before deploying: old and new loaded side by side over real
B-scans, fundus photos and noise gave **max|Δp| = 0.0** across all three gate
verdicts. GPU inference returns the same gate distance as CPU (24.2 on the
pinned benchmark scan).

That the GPU is genuinely in use is evidenced by latency rather than by the
health endpoint: 0.69s end-to-end versus 13-19s on CPU. A ViT-L forward pass
cannot run that fast on two shared vCPUs.

### Deploying an update

```bash
doppler run -p retinaoct -c dev -- ./scripts/deploy_space.sh
```

Run it locally against already-staged weights, no download, no GPU:

```bash
MODEL_DIR=~/oct-data/serving_test PORT=7880 python space/app.py
```

### Wiring it into the website

The route is `/api/analyze`. Renaming it without updating the Pages secret took
production down with a 502 — and note that **changing a Pages secret does not
affect the running deployment until the next deploy**.

```bash
npx wrangler pages secret put HF_ENDPOINT_URL --project-name retinaoct
#   https://nicolemulla-retinaoct-biomarkers.hf.space/api/analyze
npx wrangler pages secret put HF_TOKEN --project-name retinaoct
npx wrangler pages deploy public --project-name retinaoct --branch main
```

---

## What the gate actually refuses

Surveyed 117 images against the shipped thresholds (strict 58.1, loose 96.6):

| category | n | min | median | max | rejected |
|---|--:|--:|--:|--:|--:|
| OLIVES B-scan (in-domain) | 25 | 24.3 | 38.9 | 75.4 | 0 |
| OLIVES fundus photo | 15 | 68.2 | 73.1 | 78.0 | 0 |
| Kermany OCT (other device) | 25 | 55.6 | 71.6 | 85.2 | 0 |
| OCTDL OCT (other device) | 25 | 43.3 | 74.6 | 84.1 | 0 |
| synthetic colour gradient | 1 | 90.8 | — | — | 0 |
| synthetic flat grey | 1 | 94.8 | — | — | 0 |
| synthetic colour noise | 1 | 82.6 | — | — | 0 |

**Nothing was refused — not one of 117, including a flat grey rectangle.** The
loose bound of 96.6 was never reached in practice, so a photograph returned
sixteen confident probabilities under a caveat.

Distance alone cannot fix it: real OCT reaches 85.2 while junk starts at 82.6,
so any single cut-off that refuses the junk also refuses real scans.

### Two signals instead of one

**Colour.** An OCT B-scan is a greyscale cross-section. Across 90 real scans
from three devices, mean per-pixel `max(RGB) - min(RGB)` never exceeded 0.65;
a colour photograph starts around 52. `COLOUR_LIMIT = 12` sits in an ~80x gap
and runs before the model, so a photograph is refused without inference. It
does not help against greyscale non-OCT input — including OLIVES' own fundus
images, which are greyscale here.

**Distance, recalibrated.** `GATE_LOOSE = 88`, applied at the serving layer so
the trained artefact is untouched. Above every real scan in the survey (85.2),
below the grey synthetics (90.8, 94.8).

Re-run over the same 117 images: all 90 real OCT scans still pass, all three
synthetics are refused, zero real scans lost.

### Presentation follows the verdict

| verdict | shown |
|---|---|
| `ok` | biomarkers, no banner |
| `out_of_domain` | biomarkers, no banner; a plain sentence beside the distance figure |
| `rejected` | a statement and an illustration, **no biomarkers at all** |

The amber banner is gone. Nearly every scan from a non-Spectralis device lands
in `out_of_domain`, so a warning styled as a warning fired almost always and
read as a fault rather than as context. The fact is kept; the alarm is not.

Refusing outright matters more than it sounds: a list of sixteen probabilities
under a caveat still reads as a diagnosis of whatever was uploaded.

---

## Licence constraint

Model weights derive from RETFound and inherit **CC BY-NC 4.0**. Serving
predictions publicly is fine for research; a commercial deployment is not, and
no hosting choice changes that.
