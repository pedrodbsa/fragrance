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

One schedule against the `fragrance` service collects every supplier, then sends one digest:

| Command | Cron |
| --- | --- |
| `fragrance run` | `0 9,12,21 * * *`, timezone Europe/Madrid (store hours) |

A supplier that fails is named in the digest with ⚠️ and the run shows as failed; details
are in the schedule's log.

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
