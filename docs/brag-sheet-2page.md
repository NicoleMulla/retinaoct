# RetinaOCT

**A searchable atlas of 153,045 retinal OCT B-scans with a biomarker model attached, in production at retinaoct.com — built and run at zero cost.** Search the corpus by sixteen biomarkers and clinical metadata, or upload a B-scan and get predictions in about a second, each with a map showing which region drove it.

| | |
| --- | --- |
| Scans indexed | 153,045 — 9,408 expert-labelled, 143,607 model-inferred |
| Biomarker predictions stored | 1.72M |
| Model | RETFound ViT-L/16, 303.3M parameters, fine-tuned on OLIVES |
| Performance | mAUROC 0.8916 ± 0.0360 across 12 evaluable biomarkers, 5-fold |
| Analysis latency | 0.75–2.0s end to end through the site |
| Running cost | $0 — Cloudflare Pages, D1, B2 free tiers; HuggingFace ZeroGPU |

## Technical highlights

**Shipped explainability by first disproving two standard methods.** Grad-CAM
proved structurally broken on this architecture — the head consumes only the CLS
token, so gradients to the patch tokens it needs are exactly zero. Chefer
relevance propagation produced maps that traced retinal layers crisply and
passed visual inspection easily; an Adebayo-style sanity check (randomise the
weights, recompute, expect noise) showed them correlating **+0.831** with the
original. It was drawing anatomy, not model behaviour. Blur-occlusion passed the
same check and ships: 196 patches in **0.89s** on GPU.

**Served a 303M-parameter model free at interactive speed.** Inference went from
13–19s on free CPU to **0.69s** on ZeroGPU. The migration meant solving a
platform constraint — ZeroGPU is Gradio-SDK-only, but the site needed plain JSON
endpoints — by launching Gradio non-blocking and attaching custom FastAPI routes
to its app, keeping GPU allocation while serving a clean API.

**Caught a silent preprocessing bug affecting most inputs.** The original resize
rule distorted **57% of scans in a second corpus by up to 25%**. Retinal layer
geometry *is* the signal the model reads, so stretching it changes the thing
being measured. Replaced with one rule, no special cases: scale until the
shorter side reaches 224, then centre-crop. A Mahalanobis gate against the
training distribution also refuses scans outside it rather than guessing.

## Engineering under hard constraints

The site repeatedly exhausted its 5,000,000 daily database row reads on almost
no traffic. The intuition that this was a code defect rather than usage proved
correct: five queries had consumed **3,164,996 row reads across sixteen runs**,
and one filtered search cost **1,293,782 rows** — a ceiling of four searches per
day. Three distinct bugs shared one shape: an index satisfying the `WHERE`
clause but not the `ORDER BY`, so the database read a whole subset and discarded
nearly all of it.

| Fix | Before | After |
| --- | --- | --- |
| Four facet scans collapsed into one `GROUP BY` | 1,293,782 rows | 410,151 |
| Sibling lookup `ORDER BY` removed | 980–2,156 rows to return 8 | 8–9 |
| Edge caching enabled on detail pages | every view hit the database | 24h cache |

The middle fix matters most. The textbook remedy was a composite index — but the
free tier allows 100,000 row *writes* daily and that index needed 153,045
entries, over a full day's budget. Dropping the `ORDER BY` gave a **240×
reduction at no cost**, because rows already arrive in the order displayed.

The root cause was a schema that existed nowhere in version control, applied
directly to the live database, with no credential available to audit it. That is
now closed: a schema endpoint reports drift through the application's own
database binding and therefore **needs no credentials** — the precise reason the
problem went unnoticed.

## Impact and the path to clinical validation

Every performance figure is measured against OLIVES' expert annotations. That
establishes the model reproduces those annotators — not that their annotations
match what a practising clinician would mark. **Only a licensed optometrist can
answer that, and nothing in the architecture has to change for them to do it.**

1. **Agreement on real scans** — a blinded read compared against model output,
   giving a clinician-versus-model figure independent of OLIVES.
2. **Whether the influence maps point somewhere sensible** — the claim most
   exposed to being confidently wrong, and the one no layperson can check.
3. **Whether thresholds and refusal behaviour are clinically right** — both were
   tuned statistically, with no clinical input on the cost of a miss against a
   false alarm.

"Reproduces OLIVES annotations at mAUROC 0.89" is a machine-learning result.
"Agrees with licensed optometrists at rate X on an independent set" is a
clinical one — the sentence a reviewer, collaborator or grant panel responds to,
and what would make 153,045 labelled scans defensible as a teaching resource.
The infrastructure is already in place: stored predictions for all 143,607
inferred scans, per-image download, and uploads that are never stored. The
missing piece is a structured read-and-record flow, not a change to the model.
