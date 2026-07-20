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

1. **UI loads:** open <http://127.0.0.1:8484> — since M2 this is the ranked
   inbox (empty on a fresh install, with a pointer to the Sources page).
2. **Health endpoint:** `curl http://127.0.0.1:8484/health` →
   `{"status":"ok","version":"0.2.0","migrations":4}` (numbers as of M6)
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
3. Watch the **Jobs** column fill in on the Sources page (since M2, the
   fetched jobs also appear ranked in the inbox at `/`).
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

## M3 — Tracker + vault

What exists: profile vault (contact details, resume/document uploads with a
default, cover letter template, canned answers — all entered in the app),
pipeline states with auto follow-up reminders, notes, paste-a-URL capture,
and `wingman backup`.

Demo:

1. **Vault:** open <http://127.0.0.1:8484/profile>. Fill in contact details,
   upload a resume (first upload becomes the default), write the cover
   letter template, add canned answers ("work authorization" → your
   standard answer). Everything is a form — no config files.
2. **Capture:** open Capture, paste any job posting URL (LinkedIn, a
   company site, anywhere). Wingman fetches the page, reads its structured
   JobPosting data (or falls back to the page title/description), scores
   it, and lands you on its detail page.
3. **Lifecycle:** on that job: mark *interested* → move the pipeline
   dropdown to *applied*. A follow-up reminder is automatically scheduled
   for +7 days. Add notes ("referral via Sam"). Add a manual reminder.
4. **Tracker:** open Tracker — the job sits under Applied with its score
   and notes; due reminders surface at the top (and as a banner on the
   inbox). Click Done to clear one.
5. **Backup:** `uv run wingman backup` → prints the path of a tarball
   containing a consistent database snapshot + all uploaded documents.
6. Tests: `make test` — JSON-LD capture parsing runs against recorded
   HTML fixtures; transitions, reminders, vault, and backup all covered.

Verified end-to-end in the build sandbox by serving a fixture job page
over local HTTP and running the full capture → interested → applied →
reminder-fires loop through the real UI routes.

## M4 — AI layer

What exists: provider abstraction (`claude` CLI / `codex` CLI / none — your
subscription logins, never API keys), AI settings + health page, batched AI
scoring with rationale and red flags, cover letter drafting with template
fallback, and tested graceful degradation.

Demo:

1. Open **AI** in the nav. Pick your provider (it shows whether each CLI is
   installed). Click **Run test call** — "Last AI call: OK" proves the
   subscription login works.
2. Click **Score a batch now** (or wait — a batch runs automatically every
   ~30 minutes). Open a high-scoring job: an **AI assessment** panel shows
   the model's 0-100 score, up to three rationale bullets, and red flags
   (ghost-job signals etc.). Results are cached; nothing is scored twice.
3. On any job detail page click **Draft cover letter**. With AI it writes a
   targeted letter in your template's voice; without AI it fills your vault
   template's {company}/{title}/{name} placeholders. Either way you always
   get a letter (cached on the application for M5 to attach).
4. Degradation demo: log out of the CLI (or uninstall it) and repeat —
   every feature keeps working on heuristics/templates, with a single
   ai.error event in the log. `make test` covers missing binary, non-zero
   exit, garbage output, and schema-violating responses.

Note: verified in the build sandbox against a real `claude` CLI (health
check round-trip) plus fake CLI binaries for every failure mode.

## M5 — Apply engine

What exists: ATS detection (Greenhouse, Lever, Ashby, Workable) stamped on
every job; form fillers for **Greenhouse and Lever** driving a real Chromium
via Playwright; canned-answer fuzzy matching (unmatched questions are
outlined, never guessed); assisted review-before-submit as the default;
opt-in auto-submit with per-ATS toggles, a daily cap, per-company cooldown,
CAPTCHA refusal, and a screenshot of every unattended submission; exact
document snapshots (resume + cover letter + fill report) recorded on the
application.

Demo:

1. Open **Apply** in the nav: per-ATS auto-submit toggles, daily cap, and
   cooldown — all editable in the app. Leave auto-submit off for the first
   demo; assisted is the default tier.
2. Open a Greenhouse or Lever job → the **Apply** card names the detected
   ATS. Click **Apply with Wingman**: a visible Chromium window opens with
   name, email, links, resume, cover letter, and canned answers filled; a
   banner reports the count and anything unanswered is outlined in red
   (required) or amber (optional). Review, fix the outlined bits, click
   Submit yourself — Wingman detects the confirmation page, records the
   application with the exact documents sent, and schedules the +7d
   follow-up reminder. Closing the window without submitting records
   nothing.
3. Auto-submit: enable the ATS toggle under Apply, then click
   **Auto-submit** on a job. If — and only if — every required field
   matched and there's no CAPTCHA, Wingman submits headlessly, saves a
   full-page screenshot, and records the application as `wingman-auto`.
   Anything ambiguous falls back to "needs review" instead. The cap,
   cooldown, and already-applied checks run before a browser even opens.
4. Guardrail demo (the important one): remove a canned answer so a required
   question has no match, click Auto-submit — Wingman refuses and tells you
   why. Same for a form with a CAPTCHA, an exhausted daily cap, or a
   company applied-to within the cooldown.
5. Tests: `make test` — fillers run against saved Greenhouse/Lever HTML
   fixtures in a real headless Chromium (no live HTTP); every guardrail
   above is covered, including end-to-end auto-submit on a fixture form
   with screenshot and document-snapshot assertions.

Note: the build sandbox has no outbound network and no display, so this
milestone was verified on fixture forms (headless). The acceptance bar in
PLAN.md — prefill accuracy on live Greenhouse/Lever postings — still needs
a pass on Andy's machine with real postings; the fillers' selectors follow
the boards' published form structures, and anything they miss lands in the
outlined-for-review path rather than being guessed.

## M6 — Polish + Android

What exists: PWA (installable on Android, share-target into capture), ntfy
push (morning digest + due reminders) with a Notify settings page, metrics
page, company watchlist sources (Greenhouse/Lever/Ashby public boards) with
a scoring boost, and Adzuna + USAJOBS adapters whose keys are entered in the
UI (sources hidden until keys exist). Plain-language run guides live in
docs/RUNNING.md (Windows/Mac included) and docs/PHONE.md (home-screen
install, Tailscale, ntfy).

Demo:

1. **Watchlist:** Sources → "Watch a company" → e.g. company *Stripe*, ATS
   *Greenhouse*, board name *stripe* → Watch company. A new "Watchlist:
   Stripe" source appears; Fetch now pulls its live board, and its postings
   show a `+watchlist` chip and a +10 boost in the inbox.
2. **Keyed boards:** Sources → "Keyed job boards" — Adzuna and USAJOBS are
   invisible in the source table until you paste free API keys into the
   form (links to the sign-up pages are right there). Enter keys → the
   source appears enabled with your search terms; "Remove keys" hides it
   again.
3. **Phone (the reveal):** follow docs/PHONE.md — on the phone open the
   app, ⋮ → Add to Home screen. Open any job in a browser or app and
   Share → Wingman: the capture page opens with the link pre-filled, one
   tap creates the tracked job. Say it plainly: there is no APK; this IS
   the app.
4. **Push:** install ntfy on the phone, subscribe to a made-up topic, put
   the same topic on Wingman's Notify page → "Send a test push" buzzes the
   phone. The page previews exactly what tomorrow's digest will say; the
   real one arrives each morning at the configured hour, and due reminders
   push as they come due (each exactly once).
5. **Metrics:** apply/advance a few jobs on the tracker, then open
   Metrics — applications per week, response rate by source, and response
   rate by score band ("response" = interviewing/offer/rejected, and that
   definition is printed on the page).
6. Tests: `make test` — board adapters, keyed boards (auth headers, key
   injection, never-in-raw_json), digest once-per-day, reminder
   exactly-once, share-target URL extraction, metrics math, all on
   fixtures with zero live HTTP.

Note: the build sandbox has no outbound network, so live board fetches
(Stripe's real Greenhouse board, a real ntfy push, real Adzuna calls) were
verified against recorded fixture payloads; the request URLs, params, and
auth headers are asserted in tests. First run on a real network should
click "Fetch now" on one watchlist source and "Send a test push" to see
both ends live.

## M7a — PIN gate

What to show: opening Wingman to the LAN no longer exposes the vault —
non-local devices see a login screen until they enter the PIN once.

1. Add `WINGMAN_PIN=4271` (pick your own) to `~/.config/wingman/env` and
   restart Wingman. On the computer itself nothing changes — loopback is
   never gated, so `http://127.0.0.1:8484` works as always.
2. From a phone (or `curl -i http://<lan-ip>:8484/`), open any page: you
   get the PIN form instead. Type a wrong PIN — it pauses a second,
   re-prompts, and a `auth.failed` event with the client IP lands in the
   events table (`sqlite3 ~/.local/share/wingman/wingman.db "SELECT * FROM
   events WHERE kind='auth.failed'"`). The PIN itself is never logged.
3. Enter the right PIN: you land back on the page you asked for, and the
   phone stays signed in for a year (httponly cookie keyed to a per-install
   secret in `~/.local/share/wingman/secret`, mode 600 — deleting that file
   signs every device out).
4. The Android install path still works pre-login: `/static/*` (manifest,
   icons, CSS) and `/sw.js` are exempt from the gate; they hold no PII.
5. Remove `WINGMAN_PIN` and restart: behavior is exactly as before — no
   login route, nothing gated.
6. Tests: `make test` — gate off leaves everything open, gate on redirects
   non-local clients, wrong PIN brakes + records the event, right PIN
   unlocks every page, forged cookies bounce, static stays reachable.

## M7b — Ashby and Workable fillers

What to show: the apply engine now fills all four hosted boards —
Greenhouse, Lever, Ashby, Workable — with the same guardrails.

1. Open **Apply** in the nav: Ashby and Workable now have their own
   auto-submit toggles next to Greenhouse and Lever (the old "detection
   only for now" labels are gone). Everything stays off by default.
2. Open a job hosted on `jobs.ashbyhq.com` or `apply.workable.com` (paste
   one via capture if the inbox has none) — the Apply card offers **Apply
   with Wingman** instead of the manual-apply fallback. Assisted flow is
   identical: Chromium opens on the application form (Wingman navigates to
   the `/application` or `/apply` form page itself), fills contact fields,
   resume, cover letter, and canned answers, outlines the rest.
3. Auto-submit works the same too: enable the ATS toggle, click
   Auto-submit; refusal on CAPTCHA or any unmatched required field, daily
   cap, cooldown, screenshot — all shared machinery, nothing new to learn.
4. First-live-run reminders (the caveat below, surfaced in the app): the
   Apply page shows a "Before trusting Wingman on a new job board" card
   listing every board whose filler hasn't been proven on a real posting
   from this install, with the exact instruction — one review-&-submit
   application, read every field, keep auto-submit off until it works.
   Each board's toggle carries a "(not tried for real yet)" tag, and job
   pages show a one-line nudge. After the first recorded Wingman
   application on a board, a "Yes, it worked — hide this reminder" button
   appears for it; before that, the reminder cannot be dismissed. To demo:
   apply to a job through Wingman, revisit Apply, click the button — that
   board's reminder, tag, and job-page nudge all disappear (and an
   `apply.live_verified` event lands in the log).
5. Tests: `make test` — both new fillers run the full existing matrix
   against saved Ashby/Workable HTML fixtures in headless Chromium:
   fill+report accuracy, unmatched-required refusal, CAPTCHA refusal, and
   end-to-end auto-submit with screenshot; plus regression tests proving
   the settings page and guardrails pick up new ATS kinds automatically
   from `ats.SUPPORTED`, and that reminders only unlock for dismissal
   after a recorded Wingman application on that board.

Note: same sandbox caveat as M5 — fixtures model the boards' published
form structures (Ashby `_systemfield_*` ids, Workable `data-ui`
attributes); first live pass on Andy's machine should assisted-apply to
one real posting per board before trusting auto-submit. The in-app
reminders above walk Andy through exactly that.
