# Wingman demo script

## M0 — Skeleton

1. Install dependencies, initialize the database, and install the user service:
   ```bash
   ./install.sh
   ```
2. If systemd user services are unavailable in the current shell, run the app directly:
   ```bash
   make dev
   ```
3. Open <http://127.0.0.1:8484> and confirm the placeholder dashboard says Wingman is ready for Andy Persons.
4. Confirm the health endpoint returns `{"status":"ok"}`:
   ```bash
   curl http://127.0.0.1:8484/health
   ```
