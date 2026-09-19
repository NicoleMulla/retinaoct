# Runbook

Operational commands for retinaoct.com. Everything runs through
`doppler run --`, which injects credentials into the process environment and
discards them on exit.

---

## Secrets

```bash
doppler setup --project retinaoct --config dev   # bind this directory
doppler secrets --only-names                     # list names, never values
doppler run -- printenv | grep -c RCLONE         # confirm injection works
```

Setting a secret — **from a separate terminal, not an AI session.** Omitting
the value makes Doppler prompt interactively, keeping it out of shell history:

```bash
doppler secrets set RCLONE_CONFIG_B2_KEY
```

Configs are `dev`, `stg`, `prd`. Target a non-default one with
`--config prd` on any command.

---

## Backblaze B2

rclone builds the `b2:` remote from environment variables alone — there is no
`rclone.conf`.

```bash
doppler run -- rclone lsd b2:                         # list buckets
doppler run -- rclone ls b2:$B2_BUCKET | head         # list objects
doppler run -- rclone size b2:$B2_BUCKET              # total size and count
doppler run -- rclone about b2:                       # account usage
```

### Uploading

Always dry-run first — `sync` deletes destination files absent from the source:

```bash
doppler run -- rclone sync ./scans b2:$B2_BUCKET/scans --dry-run -v
doppler run -- rclone sync ./scans b2:$B2_BUCKET/scans --progress \
  --transfers 16 --checkers 32 --fast-list
```

Use `copy` instead of `sync` when nothing should ever be deleted:

```bash
doppler run -- rclone copy ./scans b2:$B2_BUCKET/scans --progress
```

### Verifying

```bash
doppler run -- rclone check ./scans b2:$B2_BUCKET/scans --one-way
```

### Notes

- Homebrew's rclone omits `mount` on macOS (needs FUSE). Use `nfsmount`.
- B2 keeps old versions by default — deletes hide rather than remove. Check
  bucket lifecycle rules if storage exceeds expectations.
- Tune `--transfers` to your uplink; 16 is a reasonable default for large files.

---

## Cloudflare

```bash
doppler run -- wrangler whoami                   # verify token + account
doppler run -- wrangler pages project list
doppler run -- wrangler pages deploy ./dist --project-name retinaoct
doppler run -- wrangler deploy                   # Workers
doppler run -- wrangler tail                     # live logs
```

### Which credential is in play

`CLOUDFLARE_API_TOKEN` in the environment **overrides** the `wrangler login`
OAuth session:

| Command | Credential |
|---|---|
| `doppler run -- wrangler ...` | scoped API token |
| `wrangler ...` | OAuth session |

Check this first when debugging a permissions error — the OAuth session grants
only `zone (read)` and **cannot create DNS records**. DNS work requires the
scoped token with `Zone → DNS → Edit`.

### Reference

| | |
|---|---|
| Zone | `retinaoct.com` |
| Zone ID | `15b313cbffa7685f638ec3a4c0ad76bc` |
| Account ID | `de5e90b1654c563412e579d937eba2c0` |
| B2 endpoint | `s3.us-east-005.backblazeb2.com` |

---

## Git

```bash
git status -sb
git log --oneline
gh repo view --web
```

Before every push to this **public** repo:

```bash
git diff --cached --name-only     # confirm nothing sensitive is staged
```

---

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `rclone: didn't find section in config file` | Doppler secrets missing — run `doppler secrets --only-names` |
| Cloudflare `Authentication error [10000]` | Token lacks the scope, or OAuth is being used instead of the token |
| DNS record creation fails | Using OAuth (`zone (read)` only) instead of the scoped token |
| B2 `401 unauthorized` | Key scoped to a different bucket, or expired |
| Egress charges appearing | Traffic bypassing Cloudflare and hitting B2 directly |
