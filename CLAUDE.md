See README.md for how the tracker works and docs/deploy.md for the server.

- Secrets live in `.env` (git-ignored) locally and in Dokploy's Environment tab on the server.
- One module per supplier in `app/suppliers/`; keep each one self-contained.
- The owner doesn't read Python: keep code plain and commented, and explain behaviour changes
  in terms of what the alerts or the backoffice will do.
