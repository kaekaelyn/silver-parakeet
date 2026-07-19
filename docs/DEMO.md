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

## M1 — Ingestion

What exists: adapters for Remotive, RemoteOK, We Work Remotely, the HN
"Who is hiring?" thread, and any generic RSS feed; dedupe across sources
(canonical URL + fuzzy company/title/location match); background polling
with per-source intervals and jitter; a sources admin page; an events log
row for every fetch.

Demo (on a machine with normal internet access):

1. Start the app (`make dev` or the systemd service) and open
   <http://127.0.0.1:8484/sources>. Four boards are pre-configured and
   enabled.
2. Wait ~90 seconds — each source's first poll is staggered shortly after
   startup — or click **Fetch now** on any source.
3. Watch the **Jobs** column fill in, and the dashboard counters climb.
   Real postings are now in the database:
   `sqlite3 ~/.local/share/wingman/wingman.db 'SELECT company, title FROM jobs LIMIT 10;'`
4. **Dedupe:** click Fetch now on a second source that lists some of the
   same jobs — the events log shows `"duplicates": N`:
   `sqlite3 ~/.local/share/wingman/wingman.db "SELECT payload_json FROM events WHERE kind='fetch.ok';"`
5. **Failure isolation:** toggle a source off (button flips to *disabled* —
   its polling stops), or watch a source with a bad URL record its error in
   the **Last error** column while every other source keeps working.
6. **Add an RSS feed:** paste any job-board RSS URL into the form at the
   bottom of the sources page.
7. Tests: `make test` — every adapter is tested against recorded sample
   payloads in `tests/fixtures/`; no test touches the live internet.

Note for sandboxed environments: the build sandbox blocks outbound HTTP to
the job boards, so live fetches there fail with `ProxyError: 403` — which
usefully demos step 5's failure isolation (error recorded, app healthy).
Live ingestion was designed against each API's documented format and the
fixtures mirror those formats; verify live pulls on a normal machine.
