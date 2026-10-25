# Serving the biomarker model

How `retinaoct.com/analyse` reaches the model, what it costs, and the one step
that is not done.

Investigated 2026-10-24.

---

## Shape

```
browser ──POST image bytes──▶ Cloudflare Pages Function ──POST {"inputs": b64}──▶ model endpoint
                              functions/api/analyse.js                            handler.py
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

## Host: a private Docker Space

`NicoleMulla/retinaoct-biomarkers` — private, `cpu-basic`, **included in HF PRO
at no per-hour cost**. Docker SDK, not gradio — see below.

| | Space `cpu-basic` | Inference Endpoint `intel-spr x2` |
|---|---|---|
| Cost | included in PRO | $0.067/hr while warm |
| RAM | 16 GB | 4 GB (peak use 2.81 GB — 70%) |
| Reachable from a Worker | yes, token-authenticated | **no — see below** |

### Why not the Inference Endpoint

It was created and did build successfully, but came back as `type: "private"`
despite `"protected"` being requested. On HF, a *private* endpoint is reachable
only over AWS PrivateLink, not the public internet — so a Cloudflare Worker
cannot call it. It was deleted the same session; billing ran for a few minutes.

If that route is ever revisited, the endpoint must come up as `protected`
(token over the internet), and that needs confirming against the live API
rather than assumed from the request body.

### Verified locally before deploying

`space/app.py` was run against the real weights under gradio 5.50.0:

| Route | Result |
|---|---|
| `GET /api/health` | 200, 16 biomarkers loaded |
| `POST /api/analyse` (JSON base64) | 200, `verdict=ok`, 0.14 s |
| `POST /api/analyse` (raw bytes) | 200, identical distance — both paths agree |
| Garbage input | 422, clean error, no traceback leaked |
| `GET /` (Gradio UI) | 200 |

Two compatibility problems were caught this way rather than in a build log:
`allow_flagging` was renamed in Gradio 5 (removed), and `sdk_version` had been
guessed at a release that does not exist — gradio is on 6.x, so the Space pins
the latest 5.x, 5.50.0.

### Two failures the Space build found anyway

**`torch==2.4.0` has no Python 3.13 wheel.** Spaces run 3.13 and only 2.5.0
onwards is published for it. The Space pins **2.14.0** — not a guess, but the
version the handler was verified against locally, producing identical verdicts
and gate distances. `serving/requirements.txt` and the model repo's copy both
still pin 2.4.0, so an Inference Endpoint deploy would hit the same wall.

**The gradio SDK races the app for its port.** With `sdk: gradio`, the platform
launcher and this app's own `uvicorn.run` both try to bind, and the Space dies
with `[Errno 98] address already in use` on 7861. Switching to `sdk: docker`
with an explicit `CMD` and `app_port: 7860` gives the app sole ownership of the
entrypoint. `GRADIO_SERVER_PORT` is deliberately *not* read — under the gradio
SDK it points at a port the launcher has already taken.

### Deploying an update

```bash
doppler run -p retinaoct -c dev -- ./scripts/deploy_space.sh
```

Pushes `space/` and waits for the rebuild. `MODEL_DIR` runs it against an
already-staged local copy of the weights instead of downloading them:

```bash
MODEL_DIR=~/oct-data/serving_test PORT=7870 python space/app.py
```

### Wiring it into the website

```bash
npx wrangler pages secret put HF_ENDPOINT_URL --project-name retinaoct
#   https://nicolemulla-retinaoct-biomarkers.hf.space/api/analyse
npx wrangler pages secret put HF_TOKEN --project-name retinaoct
```

Until both exist, `/analyse` returns a clean
`"Analysis is not configured on this deployment yet."` and the rest of the site
is unaffected. A sleeping Space answers with HTML rather than JSON, which the
proxy already treats as a cold start rather than a broken model.

---

## Licence constraint

Model weights derive from RETFound and inherit **CC BY-NC 4.0**. Serving
predictions publicly is fine for research; a commercial deployment is not, and
no hosting choice changes that.
