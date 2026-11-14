# RetinaOCT — What We Built and What It Took

*As of 2026-11-11 · retinaoct.com*

## What RetinaOCT is

RetinaOCT is a searchable atlas of 153,045 retinal OCT B-scans with a biomarker
model attached, running in production at retinaoct.com on free infrastructure.

Two things happen on the site. You can search the OLIVES corpus by sixteen
retinal biomarkers and clinical metadata, download any scan, and see where each
label came from. Or you can upload your own B-scan and get biomarker predictions
in about a second, each with a map showing which part of the scan drove it.

The model is a RETFound ViT-L/16 encoder fine-tuned on 9,408 expert-annotated
B-scans from 87 patients in two diabetic macular oedema trials.

| | |
| --- | --- |
| Scans indexed | 153,045 (9,408 expert-labelled, 143,607 model-inferred) |
| Biomarker predictions stored | 1.72M |
| Model | RETFound ViT-L/16, 303.3M parameters, fine-tuned |
| Performance | mAUROC 0.8916 ± 0.0360 across 12 evaluable biomarkers, 5-fold |
| Analysis latency | 0.75–2.0s warm, end to end through the site |
| Running cost | $0 — Cloudflare Pages, D1 and B2 free tiers, HuggingFace ZeroGPU |

The last row is not a footnote. Almost every hard decision in this project was
shaped by staying inside free tiers, and several of the engineering problems
below exist only because of that constraint.

## The hardest technical problems

The hardest work was not training the model. It was making the model's output
honest — explaining it, bounding it, and not distorting the input on the way in.

### Choosing an attribution method, by disproving two of them

The site has a "Why this prediction?" button on every biomarker. Getting a
trustworthy map behind it took three attempts, and two of them failed in ways
that would have been invisible without testing for them.

**Grad-CAM was structurally broken, not merely weak.** Hooked at the final
transformer block, the gradients were exactly zero. The reason is architectural:
the classification head consumes only the CLS token, so gradients never flow to
the patch tokens Grad-CAM needs.

**Chefer relevance propagation produced beautiful maps that meant nothing.** It
passed visual inspection easily — the maps traced retinal layers crisply. We ran
an Adebayo-style sanity check: randomise the model weights and recompute. A
faithful method should collapse to noise. Chefer's maps correlated **+0.831**
with the original. It was drawing anatomy, not model behaviour. Shipping it
would have given users a confident, authoritative-looking explanation of
nothing.

**Blur-occlusion passed.** Blur one patch of the scan, run it through again,
measure how far each biomarker's probability moves. A 14×14 grid gives 196
patches, batched 98 at a time, in **0.89s** on the GPU. Under the same
randomisation check its maps collapse as they should.

The benchmark for that timing was itself wrong on the first pass — it reported
0.01s for 196 forward passes, which is physically impossible. CUDA launches are
asynchronous, so the timer was measuring queue submission, not compute.

### Preprocessing: distortion is worse than cropping

The original rule resized non-uniformly unless the aspect ratio fell outside
0.8–1.25. Auditing it against a second corpus showed **57% of scans were being
squashed by up to 25%**.

That matters more here than in most vision tasks. Retinal layer geometry — the
thickness and separation of bands — *is* the signal the model reads. Stretching
it vertically changes the thing being measured.

The replacement is one rule with no special cases: scale until the shorter side
reaches 224, then centre-crop the overflow. Resizing before cropping also leaves
real pixels just outside the crop boundary for the resampling kernel, so edges
come out cleaner than cropping first.

### Serving a 303M-parameter model for nothing

On a free CPU host, inference took 13–19 seconds — slow enough that the feature
read as broken. Moving to ZeroGPU took it to **0.69s end to end through the
site**, still free.

That migration had a real constraint: ZeroGPU is Gradio-SDK-only, but the site
needed plain JSON API routes, not a Gradio UI. The resolution was to launch
Gradio with `prevent_thread_lock=True` and attach our own FastAPI routes to
`demo.app` afterwards — keeping ZeroGPU's GPU allocation while serving a clean
API.

### Knowing when not to answer

A model asked to classify a photograph of a cat will classify it. The site
computes a Mahalanobis distance between the uploaded scan's feature vector and
the training distribution. Scans far enough outside the validated distribution
are refused rather than guessed at — and the page says explicitly that a refusal
is not the same as finding the retina normal.

## Biggest challenges overcome

### A database that exhausted its daily quota on almost no traffic

The site went down repeatedly: 5,000,000 daily row reads exhausted, on a site
barely being used. The first diagnosis blamed ordinary search usage. That was
rejected — correctly — on the grounds that the traffic simply was not there, and
that something in the code had to be responsible.

Measurement proved it. The five costliest queries had consumed **3,164,996 row
reads across sixteen runs**. A single filtered search cost **1,293,782 rows**.
Four searches exhausted an entire day, so no amount of light usage was ever
going to be safe.

Three separate bugs, all the same shape — an index that satisfies the `WHERE`
clause but not the `ORDER BY`, so the database reads an entire subset and
discards nearly all of it:

| Bug | Before | After | How |
| --- | --- | --- | --- |
| Faceted search ran four full scans | 1,293,782 rows | 410,151 | Collapsed `COUNT(*)` + three dimension facets into one `GROUP BY` |
| Detail view sibling lookup | 980–2,156 rows to return 8 | 8–9 | Dropped an `ORDER BY` the index could not satisfy |
| Detail endpoint never edge-cached | every view hit the database | 24h cache | Caching was off on all 153,045 pages |

The sibling fix is the one worth dwelling on. The obvious remedy was a composite
index — but the free tier allows only 100,000 row *writes* per day, and an index
on the images table is 153,045 entries. One index would have exceeded a full
day's write budget. Removing the `ORDER BY` achieved a **240× reduction for
free**, because the rows already come back in the order that part of the page
displays.

### Making the failure impossible to repeat

The deeper problem was that **the database schema existed nowhere in the
repository**. Tables and indexes had been applied directly to the live database
during the import work. Nothing recorded them, so nothing could detect one going
missing — and the only API token available could not read the database to check.

Four changes closed that gap permanently:

1. A schema endpoint reports the live schema and names any missing index,
   through the application's own database binding — so it needs **no credentials
   at all**, which was the exact reason the drift went unnoticed.
2. A committed schema snapshot, regenerated by script.
3. The schema check now asks that endpoint instead of requiring a token nobody
   had.
4. Every database consumer reports its own per-query row reads on demand and
   logs anything over budget.

Eleven partial indexes were then applied — 81,310 index entries against the
100,000 daily write cap, sized deliberately to fit inside one day.

### Cold starts that told users to do the impossible

The model sleeps when idle. The page said "try again in about a minute."
Measured reality: **44 seconds for a re-wake, over seven minutes from properly
cold**. Users followed the instruction, it failed, and they concluded the site
was broken. The message was specific, confident and wrong — worse than vague.

It was also styled as a red error identical to a corrupt upload, so people
blamed their own file.

The fix rests on one observation: requesting analysis while the model is down
costs nothing — it fails fast without ever reaching a GPU — and the first
request that *succeeds* **is** the analysis. So the page now keeps asking every
10 seconds, shows the elapsed wait, and renders results the moment they arrive,
with nothing to re-upload. A warm-up call starts the boot on page load rather
than on the Analyze click, and a scheduled job pings every 15 minutes so the
model never goes idle — verified awake across 23.5 hours of monitoring.

### Working without the credentials to do the job

The available deploy token could read database analytics but could not execute
SQL, returning API error 7403. Rather than request broader credentials or paste
secrets into a working session, the migration tooling detects the limitation and
prints the exact SQL to run in the browser console instead. The scheduled
warm-up job was likewise designed so no credential is duplicated into CI.

## Accomplishments and progress

The arc runs from a model that worked to a product that could be trusted, and
most of the effort went into the second half.

| Milestone | What it took |
| --- | --- |
| Model evaluation figures published | Per-biomarker confusion matrices and ROC curves recomputed from held-out predictions, every value cross-checked against the recorded summaries |
| Cold starts handled gracefully | Auto-retry, warm-on-load, and a 15-minute keep-warm schedule |
| Database made durable | Three row-read leaks fixed, schema captured into version control, credential-free drift detection added |
| Explainability shipped | Blur-occlusion maps behind a "Why this prediction?" button, after two candidate methods were disproved |
| Preprocessing corrected | Uniform resize-then-centre-crop, ending distortion of 57% of one evaluation corpus |
| Serving moved to ZeroGPU | 13–19s on free CPU to 0.69s, at no cost |
| Upload-and-analyze built | Magic-byte validation, 8MB cap, in-memory only — uploads are never stored or logged |
| Atlas site launched | Faceted search over 153,045 scans, per-image downloads, provenance on every label |
| Corpus labelled end to end | 9,408 expert annotations plus 143,607 model-inferred, 1.72M prediction rows |
| Model fine-tuned | RETFound ViT-L/16 on OLIVES, mAUROC 0.8916 ± 0.0360 over 12 evaluable biomarkers |

The through-line is a working practice rather than any single result: measure
the thing that has been assumed, recompute it independently, and test
specifically for the failure that would be invisible if it occurred. Two of the
entries above exist because that practice caught something already believed
finished.

## Impact and the clinical validation path

The project is built so that a licensed optometrist can check its claims rather
than take them on trust, and that is the single thing most likely to turn it
from a demonstration into something used.

### Why external review is the natural next step

Every performance figure here is measured against OLIVES' own expert
annotations. That establishes the model reproduces those annotators. It does not
establish that those annotations match what a practising clinician would mark on
the same scan, nor that the model's confident cases are the clinically
meaningful ones.

Only someone licensed to read OCT can answer that, and nothing in the
architecture has to change for them to do it. The site already shows
per-biomarker probabilities with their decision thresholds, the provenance of
every label, and an influence map for every prediction.

### What an optometrist could validate, concretely

1. **Agreement on real scans.** Read a blinded set, mark the sixteen biomarkers,
   compare against model output — yielding a clinician-versus-model agreement
   figure independent of OLIVES.
2. **Whether the influence maps point somewhere sensible.** For each positive
   prediction, does the highlighted region correspond to the structure a
   clinician would have cited? This is the claim most exposed to being
   confidently wrong, and the one a layperson cannot check.
3. **Whether the decision thresholds sit in clinically sensible places.** They
   were tuned statistically, with no clinical input on the cost of a miss
   against a false alarm.
4. **Whether the refusal behaviour is right.** Does the model decline scans a
   clinician would consider readable, and accept any it would not?
5. **Whether the interface communicates uncertainty honestly.** The research-use
   warnings and the influence-map explanation were written without clinical
   review.

### What validation would unlock

**A defensible claim.** "Reproduces OLIVES annotations at mAUROC 0.89" is a
machine-learning result. "Agrees with licensed optometrists at rate X on an
independent set" is a clinical one, and it is the sentence a journal reviewer, a
collaborator or a grant panel responds to.

**A credible teaching tool.** 153,045 labelled scans with searchable biomarkers
and visible model reasoning is already a strong teaching resource. Clinician
sign-off is what would let it be put in front of students, because it
establishes the labels are worth learning from.

**An honest map of where the model is strong.** Performance varies sharply by
biomarker — subretinal fluid reaches 0.996 while the weakest sits at 0.730.
Knowing which predictions a clinician can rely on is more useful than a single
headline number, and the site already surfaces every biomarker at equal
prominence rather than showcasing the best.

**A path through the remaining open problems.** Two are partly clinical
judgements rather than engineering ones: how aggressively the model should
refuse scans outside its validated distribution, and what field of view a
widefield scan should be analysed over. Both currently rest on our own
assumptions, and a clinician could say whether those assumptions hold.

### What would make a review easy to run

The infrastructure is largely in place. A reviewer needs a blinded set of scans,
a way to record their reads, and a comparison against stored predictions. The
database already holds model predictions with confidences for all 143,607
inferred scans, per-image download already exists, and uploads are never stored
— so a reviewer's own scans stay private by construction.

The missing piece is a structured read-and-record flow, not any change to the
model.
