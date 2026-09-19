# retinaoct.com — Infrastructure Setup Log

Running record of what's been provisioned, what's decided, and what's still open.
Last updated: 2026-09-19

---

## Current status

| Area | State |
|---|---|
| Domain | ✅ Registered |
| Cloudflare account | ✅ Authenticated (Wrangler OAuth) |
| Backblaze B2 | ⚠️ Account + bucket created; credentials not yet in Doppler |
| Secrets management | ✅ Doppler project created and bound |
| Local tooling | ✅ Installed |
| Website | ❌ Not started — scope undecided |
| DNS records | ❌ Blocked on scoped API token |

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

- Region: **East Coast** (`us-east-005`)
- S3 endpoint: `s3.us-east-005.backblazeb2.com`
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
| `RCLONE_CONFIG_B2_ACCOUNT` | B2 keyID | ❌ |
| `RCLONE_CONFIG_B2_KEY` | B2 applicationKey | ❌ |
| `B2_BUCKET` | bucket name | ❌ |
| `CLOUDFLARE_API_TOKEN` | scoped DNS token | ❌ |

The `RCLONE_CONFIG_B2_*` naming means **rclone needs no config file at all** —
it materializes the `b2:` remote purely from the environment.

### Credential handling rules
- Enter secrets via the **Doppler web dashboard** or a separate terminal —
  never in an AI session, where the command text enters the transcript.
- Use **bucket-scoped** B2 Application Keys, never the account master key.
- Cloudflare tokens: least privilege + an expiry.
- Treat any key that has appeared in a chat, screenshot, or shell history as burned.

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

## Command reference

```bash
doppler run -- rclone lsd b2:                              # list buckets
doppler run -- rclone sync ./scans b2:$B2_BUCKET/scans -P  # upload images
doppler run -- wrangler whoami                             # verify token
doppler run -- wrangler pages deploy ./dist                # deploy site
```

---

## Open items

1. **Add the four remaining secrets to Doppler** (see table above)
2. **Create the scoped Cloudflare DNS token** — unblocks all DNS work
3. **Decide what the website is** — landing page / image viewer / gated tool.
   Determines Pages alone vs. Pages + Worker.
4. **Set git identity** — `user.name` and `user.email` are unset globally
5. **Resolve PHI status** — see below

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
