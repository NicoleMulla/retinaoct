# retinaoct.com

Infrastructure and web presence for **retinaoct.com** — retinal OCT imaging.

Static site on Cloudflare, bulk image storage on Backblaze B2, secrets in
Doppler. This repo holds the site source, infrastructure configuration, and a
running record of how it was all provisioned.

---

## Status

| Component | State | Notes |
|---|:--:|---|
| Domain + DNS zone | ✅ | `retinaoct.com`, Cloudflare Registrar, zone active |
| Secrets management | ✅ | Doppler project `retinaoct`, bound to `dev` |
| Local tooling | ✅ | node, wrangler, rclone, doppler, gh, git |
| Repository | ✅ | this repo |
| B2 bucket + credentials | ✅ | `retinaoct` private, `us-east-005`, round-trip verified |
| Cloudflare DNS token | ✅ | `retinaoct-deploy`, all permissions verified |
| Website | ✅ | placeholder landing page live at `retinaoct.pages.dev` |
| Image upload pipeline | ✅ | `doppler run -- rclone sync` working |
| B2 key scope | ⚠️ | master key in use — downgrade to bucket-scoped |

---

## Architecture

```
                    ┌─────────────────────────────┐
   visitor  ───────▶│   Cloudflare edge network   │
                    │  anycast, 300+ locations    │
                    └──────────────┬──────────────┘
                                   │
                ┌──────────────────┴──────────────────┐
                ▼                                     ▼
       retinaoct.com                        images.retinaoct.com
       Cloudflare Pages                              │
       retinaoct.pages.dev                           ▼
                                          ┌──────────────────────┐
                                          │    Backblaze B2      │
                                          │  region us-east-005  │
                                          │   ~500 GB of scans   │
                                          └──────────────────────┘
```

**Why this shape.** Cloudflare is anycast — there's no region to choose, and
every visitor is served from their nearest edge automatically. B2 is the single
origin where images live; Cloudflare caches them globally. Routing image
traffic *through* Cloudflare rather than straight from B2 is what makes egress
free under the Bandwidth Alliance — serve directly from B2 and that benefit
disappears.

**Why B2 over Cloudflare R2.** At ~500 GB, B2 costs ~$2.94/mo against R2's
~$7.35/mo — roughly $53/year. Both are S3-compatible, so the decision is
reversible at low cost if requirements change.

---

## Repository layout

```
.
├── public/            site source — deployed to Cloudflare Pages
│   ├── index.html
│   ├── styles.css
│   └── favicon.svg
├── README.md          you are here — overview and status
├── SETUP.md           detailed provisioning log, decisions, and rationale
├── docs/
│   └── runbook.md     day-to-day operational commands
└── .gitignore         secrets and build artifacts
```

---

## Quickstart

Requires [Homebrew](https://brew.sh).

```bash
brew install node rclone gh dopplerhq/cli/doppler
npm install -g wrangler

git clone https://github.com/NicoleMulla/retinaoct.git
cd retinaoct

doppler login
doppler setup --project retinaoct --config dev
```

Verify credentials resolve (neither command prints a secret):

```bash
doppler run -- rclone lsd b2:
doppler run -- wrangler whoami
```

See [`docs/runbook.md`](docs/runbook.md) for the full command set.

---

## Secrets

No credentials live in this repo or on disk. Doppler injects them into the
process environment at runtime via `doppler run --`, and they vanish when the
process exits.

Secrets are named as the **literal environment variables the tools already
read**, so there is no glue code and no tool config files:

| Variable | Consumer |
|---|---|
| `RCLONE_CONFIG_B2_TYPE` | rclone — backend type |
| `RCLONE_CONFIG_B2_ACCOUNT` | rclone — B2 key ID |
| `RCLONE_CONFIG_B2_KEY` | rclone — B2 application key |
| `B2_BUCKET` | bucket name |
| `CLOUDFLARE_API_TOKEN` | wrangler |
| `CLOUDFLARE_ACCOUNT_ID` | wrangler |

The `RCLONE_CONFIG_B2_*` convention means **rclone needs no config file at
all** — it builds the `b2:` remote from the environment alone.

### Rules

- **This repository is public.** Never commit tokens, keys, `.env`,
  `.dev.vars`, or image data.
- Enter secret values through the Doppler dashboard or a dedicated terminal —
  never through an AI coding session, where command text is retained in the
  transcript.
- Use **bucket-scoped** B2 application keys and **least-privilege** Cloudflare
  tokens with expiry set. Never account master keys.
- Treat any credential that has appeared in a chat, screenshot, or shell
  history as compromised, and rotate it.

---

## Data classification — unresolved

Whether the OCT images are identifiable patient data or de-identified has
**not yet been determined**, and the answer governs whether the storage choice
above is appropriate at all.

- **Identifiable** → HIPAA requires a signed BAA. Backblaze's position is
  unverified; AWS, GCP, and Azure provide BAAs as a matter of course. This
  would need settling *before* migrating data, not after.
- **De-identified** → the current architecture is sound as designed.
- **DICOM format** → a plain object store leaves study/series indexing,
  DICOMweb endpoints, and viewer plumbing to be built by hand. AWS
  HealthImaging and Google Cloud Healthcare API handle these natively.

**Until this is resolved: no image data in this repository, and no patient
data in the B2 bucket.**

---

## Related

- [`NicoleMulla/med_classifier`](https://github.com/NicoleMulla/med_classifier) — ML classification work (currently empty)
