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
   `{"status":"ok","version":"0.1.0","migrations":2}`
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

## M2 — Criteria + scoring + ranked inbox  ← the reveal demo

What exists: boolean keyword engine (`AND`/`OR`/`NOT`, parentheses, quoted
phrases), heuristic 0–100 scorer with "why" chips, ranked inbox at `/`
(rows on desktop, cards on phone), job detail page, interested/hide/open
actions, minimum-score threshold, criteria profiles editor.

The reveal script (with real jobs flowing from M1's sources):

1. Open <http://127.0.0.1:8484/> — the inbox. Jobs are ranked best-first,
   each with a colored score badge and chips explaining *why* it scored
   (`+python +backend +salary`, or `−no keyword match` / `−salary below
   floor` on the losers).
2. Open **Criteria** and build a real profile live: name it, type a query
   like `python AND (backend OR platform) NOT crypto`, add nice-to-haves
   (`fastapi, postgres, aws`), a salary floor, remote-only. Save — every
   job is instantly rescored. Back to the inbox: the ranking has visibly
   reordered around what was just typed. **This is the moment.**
3. Set **Min score** (e.g. 40) — the noise disappears.
4. Click a job → detail page with full description, score reasoning, and
   actions. Click **☆** (interested — it gets an amber edge and joins the
   Interested tab), **✕** (hide — gone from the inbox), or **↗** (opens
   the original posting).
5. Phone: open the same URL on a narrow window/phone — rows become cards.
6. Bad input is safe: typing a broken query like `python AND (` shows a
   clear error and saves nothing.

Tests: `make test` — the boolean engine and scorer have dedicated
suites (precedence, parentheses, word boundaries so `go` ≠ `django`,
exclusions, salary/freshness/recency handling, chip output).

To preview without live sources (e.g. in the sandbox): load the test
fixtures through the real ingest path, then browse normally — see git
history of this file or ask a session to reseed.
