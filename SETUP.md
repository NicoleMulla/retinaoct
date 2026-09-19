# retinaoct.com — Infrastructure Setup Log

Running record of what's been provisioned, what's decided, and what's still open.
Last updated: 2026-09-19

---

## Current status

| Area | State |
|---|---|
| Domain | ✅ Registered |
| Cloudflare account | ✅ Authenticated (Wrangler OAuth) |
| Backblaze B2 | ✅ Bucket `retinaoct` live, auth verified end-to-end |
| Secrets management | ✅ Doppler project created and bound |
| Local tooling | ✅ Installed |
| Repo | ✅ github.com/NicoleMulla/retinaoct (public) |
| Website | ✅ Placeholder landing page deployed |
| DNS records | ✅ Unblocked — token verified; zone currently empty |

---

## Domain

- **retinaoct.com**, registered 2026-09-19 via **Cloudflare Registrar**
- Zone ID: `15b313cbffa7685f638ec3a4c0ad76bc` — status `active`
- Nameservers: `amit.ns.cloudflare.com`, `noor.ns.cloudflare.com`
- Cloudflare account: `de5e90b1654c563412e579d937eba2c0` (`nclmulla@gmail.com`)
- Apple sign-in resolved to the Gmail address, so the domain and CLI share one
  account — no split-account problem.

---

## Storage decision: Backblaze B2

Chosen over Cloudflare R2 on cost, for ~500 GB of retinal OCT images.

| | Cloudflare R2 | **Backblaze B2** |
|---|---|---|
| Storage | ~$0.015/GB/mo | **~$0.006/GB/mo** |
| 500 GB/mo | ~$7.35 | **~$2.94** |
| Egress | $0 | Free to Cloudflare (Bandwidth Alliance) |

- Bucket: **`retinaoct`** — created 2026-09-19, type `allPrivate`
- Region: **East Coast** (`us-east-005`) — confirmed via `b2_authorize_account`
- S3 endpoint: `s3.us-east-005.backblazeb2.com`
- API: `api005.backblazeb2.com` · downloads: `f005.backblazeb2.com`

Verified working: upload → list → read-back → delete round-trip, 2026-09-19.

### Bucket settings not yet configured

| Setting | Current | Consideration |
|---|---|---|
| Lifecycle rules | none | Old versions are retained **forever**. B2 deletes are soft — they hide a file and keep prior versions, all billed. Set a rule to cap version retention or storage will drift upward silently. |
| Default encryption | none | SSE-B2 is free and one toggle. Worth enabling before any sensitive data lands. |
| Object Lock | disabled | Makes objects immutable once written. Cannot be retrofitted easily — decide before bulk upload. |
- Annual difference vs R2: ~$53

**Important:** free egress is *not* automatic. Traffic must actually route
through Cloudflare (e.g. `images.retinaoct.com` fronting the bucket). Serving
directly from B2 falls back to B2's own egress allowance (3x stored/mo free).

### Note on Cloudflare regions
Cloudflare has **no region picker** for websites — it's an anycast network
serving from 300+ locations, routing each visitor to the nearest edge. The B2
East Coast choice only affects origin fetches on cache miss. There is no
region mismatch to worry about.

---

## Secrets: Doppler

Chosen so credentials never touch disk — injected at runtime via `doppler run --`.

- Workplace: `Nicole` · Project: `retinaoct` · Configs: `dev`, `stg`, `prd`
- Bound: `/Users/nicolemulla/retinaoct` → `dev`
- Scope config lives in `~/.doppler/.doppler.yaml`, not the project dir

Secrets are named as the **literal env vars the tools read**, so no glue code
and no config files:

| Secret | Purpose | Set? |
|---|---|---|
| `RCLONE_CONFIG_B2_TYPE` | `b2` | ✅ |
| `CLOUDFLARE_ACCOUNT_ID` | account id | ✅ |
| `BB_KEY_ID` | B2 keyID (source) | ✅ |
| `BB_APPLICATION_KEY` | B2 applicationKey (source) | ✅ |
| `RCLONE_CONFIG_B2_ACCOUNT` | → `${BB_KEY_ID}` | ✅ |
| `RCLONE_CONFIG_B2_KEY` | → `${BB_APPLICATION_KEY}` | ✅ |
| `B2_BUCKET` | `retinaoct` | ✅ |
| `CLOUDFLARE_API_TOKEN` | scoped token `retinaoct-deploy` | ✅ |

The two `RCLONE_CONFIG_B2_*` entries are Doppler **secret references**
(`${BB_KEY_ID}`), not copies. One source of truth; rotating the underlying
secret updates both automatically.

The `RCLONE_CONFIG_B2_*` naming means **rclone needs no config file at all** —
it materializes the `b2:` remote purely from the environment.

### Credential handling rules
- Enter secrets via the **Doppler web dashboard** or a separate terminal —
  never in an AI session, where the command text enters the transcript.
- Use **bucket-scoped** B2 Application Keys, never the account master key.
- Cloudflare tokens: least privilege + an expiry.
- Treat any key that has appeared in a chat, screenshot, or shell history as burned.

---

## Cloudflare token — verified 2026-09-19

Token `retinaoct-deploy` (id `9c2ca145306ebacf90c6fe8b64fa7b9a`), status `active`.

| Check | Result |
|---|---|
| Token verify endpoint | ✅ active |
| Zone read | ✅ |
| DNS read | ✅ (zone has 0 records) |
| DNS write | ✅ created + deleted a TXT probe |
| Pages access | ✅ (0 projects) |

**`wrangler whoami` fails with this token — this is expected, not a fault.**
`whoami` enumerates all accounts, which needs `Account Settings → Read`, a
permission deliberately excluded. Real operations (`wrangler pages ...`) work
because they address the account directly via `CLOUDFLARE_ACCOUNT_ID`. Use
`wrangler pages project list` as the health check instead of `whoami`.

⚠️ **No expiry is set on this token.** It is valid indefinitely until manually
revoked. Consider adding a TTL via the dashboard.

---

## Known gap: Wrangler OAuth lacks DNS write

`wrangler login` grants `zone (read)` only — there is no `dns_records` scope,
regardless of what was approved in the browser.

**Can:** deploy Pages/Workers, KV, D1, queues, secrets
**Cannot:** create or modify DNS records

So the site can deploy to `*.pages.dev`, but attaching `retinaoct.com` and
wiring `images.retinaoct.com` → B2 requires an API token with
`Zone → DNS → Edit`, stored as `CLOUDFLARE_API_TOKEN`.

Gotcha: that env var **overrides** the OAuth session. `doppler run -- wrangler`
uses the scoped token; bare `wrangler` uses OAuth. Check which when debugging
permission errors.

---

## Repository

- **github.com/NicoleMulla/retinaoct** — public, default branch `main`
- Local root: `/Users/nicolemulla/retinaoct`
- Commit identity: `Nicole Mulla <nclmulla@gmail.com>`
- `NicoleMulla/med_classifier` is a separate, currently empty public repo

Because the repo is **public**, never commit: Doppler service tokens, B2
application keys, Cloudflare API tokens, `.env`, `.dev.vars`, or any patient
data. `.gitignore` covers the common paths — verify before each push.

---

## Local tooling

| Tool | Version |
|---|---|
| node | 26.9.0 |
| npm | 11.19.1 |
| wrangler | 4.135.0 |
| rclone | 1.75.1 |
| doppler | 3.76.5 |
| gh | 2.101.0 |
| git | 2.54.0 |

rclone via Homebrew omits `mount` on macOS (needs FUSE) — use `nfsmount`.
`sync`/`copy` are unaffected.

---

## Website

Placeholder landing page — static, no dependencies, no build step.

- Source: `public/` · Live: **https://retinaoct.pages.dev**
- Pages project `retinaoct`, production branch `main`
- Describes the planned features: browse scans, search metadata, export
- Carries a research-use-only disclaimer and states no patient-identifiable
  data is published

Custom domain `retinaoct.com` is **not yet attached** — the zone still has
zero DNS records.

### Deploying

```bash
doppler run -- wrangler pages deploy public --project-name retinaoct \
  --branch main --commit-dirty=true
```

**Gotcha:** `wrangler pages project create` fails on wrangler 4.135 — Pages
commands now delegate to the Workers platform and that subcommand has no
assets directory to target. The project was created through the REST API
instead (`POST /accounts/{id}/pages/projects`). `pages deploy` works normally
once the project exists.

Note also that the scoped token grants `Cloudflare Pages: Edit` but **not**
`Workers Scripts: Edit`, so migrating this to Workers Static Assets would
require adding that permission.

---

## Command reference

```bash
doppler run -- rclone lsd b2:                              # list buckets
doppler run -- rclone sync ./scans b2:$B2_BUCKET/scans -P  # upload images
doppler run -- wrangler whoami                             # verify token
doppler run -- wrangler pages deploy ./dist                # deploy site
```

---

## Open items

1. **Replace the B2 master key with a bucket-scoped key** — see security note below
2. **Create the scoped Cloudflare DNS token** — unblocks all DNS work
3. **Decide what the website is** — landing page / image viewer / gated tool.
   Determines Pages alone vs. Pages + Worker.
4. **Resolve PHI status** — see below

---

## ⚠️ Security: B2 key is over-privileged

The credentials in Doppler are the **account master key**. Confirmed
capabilities include `deleteBuckets`, `deleteKeys`, `writeKeys`, and
`bypassGovernance`, with no bucket restriction.

Master privileges were genuinely required to create the bucket — a
bucket-scoped key lacks `writeBuckets`. But that step is done, so the key
should now be downgraded.

**Fix:** in the B2 console create a new Application Key named
`retinaoct-rclone`, restricted to the `retinaoct` bucket with Read/Write
access. Update `BB_KEY_ID` and `BB_APPLICATION_KEY` in Doppler — the
`RCLONE_CONFIG_B2_*` references follow automatically. Then delete the master
key, or at minimum rotate it.

---

## ⚠️ Unresolved: PHI / compliance

Whether the OCT scans are **identifiable patient data** or **de-identified**
has not been determined, and it can invalidate the storage decision above.

- If **identifiable**: HIPAA requires a signed **BAA**. Backblaze's posture
  here is unverified. AWS, GCP, and Azure sign BAAs routinely — which is why
  regulated medical imaging usually lands there. Discovering this after
  500 GB is uploaded means migrating it all back out.
- If **de-identified** (research/training data): B2 is a sound choice, and
  nothing above needs to change.
- If the files are **DICOM**: a plain object store means hand-building study
  and series indexing, DICOMweb endpoints, and viewer plumbing. AWS
  HealthImaging and Google Cloud Healthcare API speak DICOM natively.

**Settle this before migrating data.**
