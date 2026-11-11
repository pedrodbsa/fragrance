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

## Schedules

Add one schedule per supplier against the `fragrance` service:

| Command | Cron |
| --- | --- |
| `run-supplier nunu` | `0 9,12,21 * * *`, timezone Europe/Madrid (store hours) |

A failed collection sends a ⚠️ message to Telegram; details are in the schedule's log.

## Backups and recovery

Litestream writes every change to the R2 bucket within seconds and keeps 30 days of history.
On start, if `/data/fragrance.db` is missing, the entrypoint restores the latest copy from
R2. To move servers: deploy the same service with the same environment and it comes back
with all its data.

Inspect the database from a container terminal: `sqlite3 /data/fragrance.db`.
