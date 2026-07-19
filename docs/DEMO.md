# Demo script

Per-milestone commands/clicks to show Wingman working. Doubles as manual QA.

## M0 — Skeleton

What exists: uv-managed project, FastAPI app with a placeholder dashboard,
SQLite schema + migration runner, config loading from `~/.config/wingman/env`,
installer with systemd user service, Makefile, tests + lint, CI.

```sh
git clone <repo-url> wingman && cd wingman
./install.sh
```

The installer syncs dependencies, creates `~/.config/wingman/env` (mode 600),
initializes the database at `~/.local/share/wingman/wingman.db` (WAL mode,
full schema from PLAN.md §8), and enables the `wingman` systemd user service.
On machines without a systemd user session (e.g. containers), it says so —
run the app manually with `make dev` instead.

Then show:

1. **UI loads:** open <http://127.0.0.1:8484> — "Wingman is running" dashboard
   with zeroed counters for jobs / sources / applications / reminders.
2. **Health endpoint:** `curl http://127.0.0.1:8484/health` →
   `{"status":"ok","version":"0.1.0","migrations":1}`
3. **Service is real:** `systemctl --user status wingman` → active (running).
4. **Audit trail from day one:**
   `sqlite3 ~/.local/share/wingman/wingman.db 'SELECT * FROM events;'` →
   an `app.started` row.
5. **Tests green:** `make test` (14 passing), `make lint` (clean).

Config demo (optional): put `WINGMAN_PORT=9000` in `~/.config/wingman/env`,
restart (`systemctl --user restart wingman`), UI moves to port 9000.

Notes: Playwright browser install is wired into `install.sh` but skipped
until the apply engine (M5) adds the dependency.
