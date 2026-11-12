# Deploying on Dokploy

One container: the backoffice (uvicorn) running under Litestream. The collectors run in the
same container from Dokploy schedules. The database is `/data/fragrance.db` on the
persistent `../files/data` mount, streamed continuously to R2.

## Create the service

1. Push this repo to GitHub.
2. In Dokploy, create a **Compose** service from the repo, compose path `docker-compose.yml`.
3. **Environment** tab: paste the values from your local `.env` (list in `.env.example`).
4. **Domains** tab: add a domain for service `fragrance`, port `8000`, HTTPS on.
5. Deploy. Open the domain and log in with `BACKOFFICE_USER` / `BACKOFFICE_PASSWORD`.

## Schedule

Two schedules against the `fragrance` service, timezone Europe/Madrid: one collects every
supplier, the other sends one Telegram digest with everything found since the last digest.

| Command | Cron | |
| --- | --- | --- |
| `fragrance run` | `0 0,6-22/2 * * *` | collect every 2 hours from 06:00 to midnight |
| `fragrance notify` | `0 12 * * *` | the digest, once a day at noon |

A supplier that fails shows as a failed collection run (details in that schedule's log), and
the digest names it with ⚠️ if its last attempt still failed.

## Telegram buttons

Set `BACKOFFICE_URL=https://grasse.xdecade.com` in the Environment tab. On start, the
backoffice registers `/telegram` with Telegram so taps on the digest's Follow / Ignore buttons reach
it (the deploy log shows `telegram: webhook registered`).

## Backups and recovery

Litestream writes every change to the R2 bucket within seconds and keeps 30 days of history.
On start, if `/data/fragrance.db` is missing, the entrypoint restores the latest copy from
R2. To move servers: deploy the same service with the same environment and it comes back
with all its data.

Inspect the database from a container terminal: `sqlite3 /data/fragrance.db`.
