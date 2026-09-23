# Data staging scripts

The scripts that downloaded, extracted, and uploaded the OCT datasets into
Backblaze B2. Kept for provenance — they record how the bucket's contents came
to exist.

Run under `doppler run --` so B2 credentials are injected. They read
`$B2_BUCKET` and the `RCLONE_CONFIG_B2_*` variables from the environment; none
contain secrets.

| Script | Purpose |
|---|---|
| `fetch.sh` | Downloads public datasets from Mendeley, Dryad, JHU. Resumable (`curl -C -`). |
| `process.sh` | Extracts archives and uploads to B2. Flattens redundant top-level dirs. |
| `extract_t7.sh` | Unpacks Bissig (`.rar`, needs `unar`) and Kermany v2 from the T7 drive. |
| `upload_t7.sh` | Uploads Bissig and Kermany v2; purges the superseded v3 first. |
| `olives.sh` | Handles OLIVES' nested archives, then uploads. |
| `finish.sh` | Combined run: Bissig + Kermany v2 + OLIVES with checksum verification. |

## Caveats

- Paths are **absolute** and assume `/Users/nicolemulla/oct-data/` for staging
  and `/Volumes/T7/ret-dataset/` for the external drive. Adjust for other machines.
- All are safe to re-run. Downloads resume; `rclone copy` skips existing objects.
- `fetch.sh` cannot retrieve Bissig — Dryad is behind a proof-of-work challenge
  (see `../docs/datasets.md`). That archive must be downloaded via a browser.
