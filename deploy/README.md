# Deploy (single Ubuntu droplet)

Runs the FastAPI backend (`:8000`) and the Next.js dashboard (`:3000`) behind
nginx on `:80`. Frontend calls `/api`, nginx proxies it to the backend.

## One command

SSH to the droplet as root and run:

```bash
curl -fsSL https://raw.githubusercontent.com/Callince/levista-marketing-performance/main/deploy/setup.sh | bash
```

This installs Python/Node/nginx, adds swap (the 1 GB droplet can't `next build`
without it), clones the repo, builds, and starts `levista-api` + `levista-web`
via systemd. Re-run any time to update to the latest `main`.

## Data (not in the repo)

The business data is gitignored, so ship it separately from your machine:

```bash
# option A — copy a prebuilt SQLite DB (fastest)
scp platform/levista.db root@68.183.80.200:/opt/levista/platform/levista.db
scp platform/overrides.json root@68.183.80.200:/opt/levista/platform/overrides.json
ssh root@68.183.80.200 'chown www-data:www-data /opt/levista/platform/levista.db /opt/levista/platform/overrides.json && systemctl restart levista-api'

# option B — copy raw exports and build on the droplet
scp -r "Levista performance report input files..." root@68.183.80.200:/opt/levista/data/input/
ssh root@68.183.80.200 'cd /opt/levista/platform && sudo -u www-data /opt/levista/.venv/bin/python run_all.py'
```

## Operating it

```bash
systemctl status levista-api levista-web      # health
journalctl -u levista-api -f                  # backend logs
systemctl restart levista-api                 # after a DB swap
```

`platform/.env` on the droplet sets `DATABASE_URL` (SQLite by default), `INPUT_DIR`
and `OUTPUT_DIR`. Point `DATABASE_URL` at Postgres/Turso instead if you outgrow SQLite.
