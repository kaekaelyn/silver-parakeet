# Execution guide — building Wingman with AI coding sessions

The plan (PLAN.md) was produced with a frontier model (Fable). Implementation
is designed to run as a series of **scoped sessions with less expensive
models** (Sonnet is the right default; Haiku only for mechanical chores).
This file is the playbook for those sessions.

## Why this split works

Planning is where deep judgment matters (architecture, ToS constraints,
failure modes). Execution succeeds or fails on **scope and specification** —
a mid-tier model with a tight brief, fixtures, and acceptance criteria will
beat a frontier model with a vague one. So: every milestone below is sized
to fit in one session, states its acceptance criteria, and names its files.

## Rules for every build session

1. **One milestone per session.** Don't let a session "get ahead" into the
   next milestone; stop at green acceptance criteria.
2. **Start every session the same way:** the model must read `CLAUDE.md`,
   `PLAN.md`, and this file's section for the current milestone before
   writing code.
3. **Tests are the contract.** Each milestone lands with pytest coverage of
   its logic (adapters and fillers get fixture-based tests with recorded
   sample payloads — never tests that hit live services).
4. **Demo script per milestone.** Each session ends by updating
   `docs/DEMO.md` with the exact commands/clicks to show the milestone
   working. This doubles as manual QA and as the script for showing Andy.
5. **Review between sessions.** After each milestone, run a review pass
   (`/code-review` in Claude Code, or a fresh session prompted only to
   review the diff against the milestone's acceptance criteria) before
   starting the next.
6. **Commit style:** small commits, imperative subject, milestone tag in
   subject, e.g. `M1: add Remotive source adapter`.
7. **When stuck or when reality contradicts the plan** (an API is dead, an
   assumption is wrong): update PLAN.md in the same commit as the change.
   The plan is a living document; drift between plan and code is a bug.
8. **Escalate model, not scope.** If a Sonnet session fails a milestone
   twice, don't expand the prompt with hacks — rerun the milestone with a
   stronger model. M5 (apply engine) is the one milestone where starting
   with a stronger model is worth the cost.

## Session prompts

Paste these verbatim to start each session (adjust only the milestone tag).
They assume the session runs inside this repo with the branch checked out.

### M0 — Skeleton

> Read CLAUDE.md, PLAN.md, and docs/EXECUTION.md §M0. Implement milestone
> M0 exactly as specified in PLAN.md §11: uv-managed Python 3.11+ project
> named `wingman`, FastAPI app serving a placeholder dashboard at
> `http://127.0.0.1:8484`, SQLite schema from PLAN.md §8 created by a
> minimal SQL-file migration runner, config loading from
> `~/.config/wingman/env`, `install.sh` (uv sync, db init, playwright
> chromium install — auto-skipped until the M5 playwright dependency lands,
> systemd user unit install+enable), Makefile with
> `dev`/`test`/`lint`, pytest + ruff configured, GitHub Actions workflow
> running lint+test. Acceptance: fresh clone → `./install.sh` → service
> running → UI loads; `make test` green. Update docs/DEMO.md. Do not start
> M1.

### M1 — Ingestion

> Read CLAUDE.md, PLAN.md, and docs/EXECUTION.md §M1. Implement milestone
> M1: `Source` adapter protocol (`fetch() -> list[RawPosting]`), adapters
> for Remotive (JSON API), RemoteOK (JSON API), We Work Remotely (RSS),
> Hacker News Who-is-hiring (Algolia API, parse top-level comments), and
> generic RSS. Normalization into `jobs`, dedupe via
> normalized-(company,title,location) fuzzy hash + canonical URL, APScheduler
> polling with per-source intervals and jitter, `events` log rows for every
> fetch, `/sources` admin page (enable/disable, last fetch, last error).
> Every adapter gets fixture tests from recorded sample payloads in
> `tests/fixtures/` (no live HTTP in tests). A raising adapter must not
> affect other sources (test this). Acceptance per PLAN.md §11 M1. Update
> docs/DEMO.md. Do not start M2.

### M2 — Criteria + scoring + feed

> Read CLAUDE.md, PLAN.md, and docs/EXECUTION.md §M2. Implement milestone
> M2: criteria editor UI backed by `criteria` table; boolean keyword engine
> supporting `AND`/`OR`/`NOT` and parentheses over posting title+description;
> heuristic scorer per PLAN.md §4 producing 0–100 plus "why" chips stored in
> `scores`; ranked inbox at `/` (responsive: cards on narrow screens, rows on
> wide) showing score, chips, age, source; job detail page; actions:
> interested / hide / open original. Threshold setting hides low scores from
> inbox. Unit-test the boolean engine and scorer thoroughly (these are the
> product's brain). Acceptance per PLAN.md §11 M2 — this milestone is the
> live demo, so polish the inbox rendering. Update docs/DEMO.md. Do not
> start M3.

### M3 — Tracker + vault

> Read CLAUDE.md, PLAN.md, and docs/EXECUTION.md §M3. Implement milestone
> M3: profile vault forms writing to `profile`/`documents`/`answers`
> (resume upload to a documents dir, multiple variants, one default);
> pipeline states on `applications` with transitions from job detail and
> inbox; notes; reminders (auto +7d on applied, manual add) surfaced on the
> dashboard; paste-a-URL capture endpoint that fetches the page, parses
> JSON-LD JobPosting (fallback: title/meta heuristics), and creates a job;
> `wingman backup` CLI producing a tarball of DB + documents. Fixture tests
> for JSON-LD parsing. Acceptance per PLAN.md §11 M3. Update docs/DEMO.md.
> Do not start M4.

### M4 — AI layer

> Read CLAUDE.md, PLAN.md, and docs/EXECUTION.md §M4. Implement milestone
> M4: `AIProvider` interface (`complete(system, prompt, json_schema) ->
> dict | None`); `ClaudeCLIProvider` shelling to `claude -p --output-format
> json` with timeout; `CodexCLIProvider` shelling to `codex exec`; `NullProvider`.
> Provider chosen in settings with live health check page (CLI present?
> logged in? last call ok?). Batch scoring queue: unscored jobs above
> heuristic threshold get AI score+rationale+red-flags (schema-validated),
> cached in `scores` with scorer='ai'. Cover letter generation on job detail
> (AI when available, else template substitution from vault). Degradation
> tests: provider binary missing / non-zero exit / garbage output ⇒ feature
> silently falls back, one event logged, app healthy. Never store API keys;
> subscriptions auth via the CLIs' own login. Acceptance per PLAN.md §11 M4.
> Update docs/DEMO.md. Do not start M5.

### M5 — Apply engine (use a strong model for this one)

> Read CLAUDE.md, PLAN.md, and docs/EXECUTION.md §M5. Implement milestone
> M5 per PLAN.md §5: Playwright with a persistent Chromium profile dir;
> ATS detection from job URL/page (`ats_kind`); form fillers for Greenhouse
> and Lever first (Ashby, Workable after): fill contact fields, upload
> default resume, insert cover letter, answer questions by fuzzy-matching
> question text against `answers` (unmatched required fields highlighted,
> never guessed); headed review-before-submit flow is the default; on
> submit-confirmation, record the application with exact document snapshots
> and schedule the follow-up reminder. Then opt-in auto-submit: per-ATS
> toggle, daily cap (default 5), per-company cooldown, abort to headed mode
> on CAPTCHA or any unmatched required field, screenshot every
> auto-submission. Fillers are per-ATS modules tested against saved HTML
> fixtures of real forms. Acceptance per PLAN.md §11 M5. Update
> docs/DEMO.md. Do not start M6.

### M6 — Polish + Android

> Read CLAUDE.md, PLAN.md, and docs/EXECUTION.md §M6. Implement milestone
> M6: PWA manifest + minimal service worker + Android share-target routed to
> the capture endpoint; ntfy notifier (topic from config) for daily digest
> (counts + top matches) and due reminders, scheduled morning digest; metrics
> page (applications/week, response rate by source and score band); company
> watchlist adapters polling Greenhouse/Lever/Ashby public JSON boards from a
> user-entered company list; Adzuna and USAJOBS adapters (keys from config,
> hidden in UI when absent); README/docs refresh with Tailscale setup guide.
> Acceptance per PLAN.md §11 M6. Update docs/DEMO.md.

### M7 — Gloss (post-plan hardening; sessions written by Fable, sized for Sonnet)

All of PLAN.md §11 is built. These are the remaining improvements, in
priority order, each scoped to one session. Rules 1–8 above still apply —
especially rule 3 (fixtures, no live HTTP) and rule 5 (review pass between
sessions). If a session stalls twice, escalate the model, not the scope.

#### M7a — PIN gate for non-local access (do this first)

> Read CLAUDE.md, PLAN.md §10, and docs/EXECUTION.md §M7a. Wingman has no
> auth; docs/PHONE.md tells users to set WINGMAN_HOST=0.0.0.0 for phone
> access, which exposes the PII vault to the whole LAN. Add an optional PIN
> gate, no new dependencies: (1) `WINGMAN_PIN` in the env file / process
> env (Settings.pin, default None — when unset, behavior is exactly as
> today and all existing tests must pass unchanged). (2) A Starlette
> middleware in create_app: when a PIN is set and the request's client host
> is not loopback (127.0.0.1/::1), require a `wingman_auth` cookie whose
> value is hmac-sha256 of the fixed string "ok" keyed with a per-install
> secret (random 32 bytes created at first use in data_dir/secret, mode
> 600); otherwise redirect to GET /login. (3) /login: minimal inline-styled
> form (no /static dependency), POST compares the PIN with hmac.compare_digest,
> sleeps 1s on failure (crude brute-force brake), sets the cookie for 365
> days (httponly, samesite=lax), redirects to the original path. Exempt
> from the gate: /login and /static/* (assets hold no PII; the manifest,
> icons, and sw.js must load pre-auth or Android install breaks). Never
> log the PIN or the cookie value; the `events` row for a failed attempt
> records only a count-worthy `auth.failed` with the client IP. Tests:
> gate off ⇒ everything open (client host "testclient" is non-local, which
> conveniently exercises the gate in tests when a PIN IS set); gate on ⇒
> non-local requests 303 to /login, wrong PIN re-prompts (and records
> auth.failed), right PIN sets the cookie and every page works, static
> stays reachable pre-auth, forged cookie values are rejected. Update
> docs/PHONE.md (replace the "no login screen yet" warning with PIN setup
> steps) and docs/DEMO.md. Do not start other M7 items.

#### M7b — Ashby and Workable fillers

> Read CLAUDE.md, PLAN.md §5, docs/EXECUTION.md §M7b, and — before writing
> anything — wingman/apply/fillers/greenhouse.py, lever.py, and common.py:
> the new fillers must follow that exact pattern (module constants ATS,
> SUBMIT_SELECTOR, CONFIRMATION_MARKERS; standard-field pass; then
> common.attach_resume, cover letter, common.walk_questions with
> skip-lists; common.detect_captcha last). Build saved-HTML fixture forms
> the way tests/fixtures/greenhouse_form.html works (a static form the
> headless-chromium tests drive), modeled on real jobs.ashbyhq.com and
> apply.workable.com application forms. Add both kinds to ats.SUPPORTED,
> remove the "(detection only for now)" labels in routes/apply.py, and
> confirm the /apply settings page and auto_check guardrails pick the new
> kinds up automatically (they key off ats.SUPPORTED — test it). Mirror
> the full existing filler test matrix for each ATS: fill+report accuracy,
> unmatched-required refusal, CAPTCHA refusal, end-to-end auto-submit on
> the fixture. Do not touch the Greenhouse/Lever fillers.

#### M7c — Events page (the audit trail, surfaced)

> Read CLAUDE.md, PLAN.md §7 ("the app can always answer what did you do
> on my behalf and when"), docs/EXECUTION.md §M7c. Add GET /events: newest
> first, filter by kind prefix via ?kind= (fetch., apply., ai., notify.,
> capture., plus "all"), 100 rows per page with a simple offset pager,
> payload shown compactly (pretty-print the JSON in a <details>). Link it
> from the nav as "Log". Payloads are already PII-clean by convention —
> do NOT start logging new data for this page. Tests: page renders, filter
> filters, pagination pages, unknown kind prefix falls back to all.

#### M7d — Tier 3 prep pack on unsupported-ATS jobs

> Read CLAUDE.md, PLAN.md §5 Tier 3 + §6 (AI feature 3), docs/EXECUTION.md
> §M7d. On the job-detail page of any job whose ats_kind is NOT in
> ats.SUPPORTED, render a "prep pack" card: contact fields, every canned
> answer, and the cover letter, each with a copy button
> (navigator.clipboard.writeText inline — no JS build step), so a manual
> application takes minutes. When an AI provider is configured, add
> "resume tailoring suggestions": one schema-validated call (list of at
> most 5 short bullets — which existing vault/resume facts to emphasize
> for THIS posting; never invent experience), cached in the application
> row's docs_json under "tailoring" so it is generated at most once per
> job; a provider failure shows the pack without suggestions and records
> one ai.error event (mirror letters.py's degradation pattern exactly).
> Tests: pack renders for unsupported kinds only; AI path on a fake
> provider; degradation path.

#### M7e — Ghost-job signals

> Read CLAUDE.md, PLAN.md §11 "Later / stretch", docs/EXECUTION.md §M7e.
> Add ghost-posting heuristics to the scorer as negative chips with small
> penalties — never hard exclusions (a real job must survive a false
> positive): "−stale-repost" (posted_at more than 45 days ago but still
> listed) −10; "−agency" (description matches a small curated regex list:
> "our client", "recruiting on behalf", "staffing agency", etc.) −10.
> Constants next to the other W_* weights; chips explain themselves in
> the inbox. Extend scoring tests; rescore_all picks the changes up on
> the next criteria save (verify, don't add a migration).

#### M7f — Restore command and update guide

> Read CLAUDE.md, docs/EXECUTION.md §M7f, wingman/backup.py, and
> wingman/main.py. Add `wingman restore <tarball>`: validates the tarball
> contains wingman.db (reject anything with absolute paths or ".." members
> before extracting), refuses to run while the DB exists unless --force,
> and with --force first writes a safety backup via create_backup, then
> swaps in the restored DB + documents dir. Print exactly what happened.
> Tests: round-trip backup→wipe→restore; refusal without --force;
> hostile-tarball rejection. Then add an "Updating Wingman" section to
> docs/RUNNING.md: git pull (or re-download ZIP), re-run ./install.sh
> (it is idempotent) or restart the serve window; migrations apply
> automatically on start; `wingman backup` before updating is one command
> of insurance.

#### Deferred, deliberately (decide with Andy, don't build speculatively)

- **Criteria v2** (locations/timezones, seniority ranges, per-source
  profile flags) — PLAN §4's phasing note still stands: wait for real
  usage; boolean queries cover most of it today.
- **Resume-term extraction into the scorer** (PLAN §4) — needs a PDF-text
  dependency (pypdf) and real resumes to tune against; only worth it if
  Andy's criteria profiles prove too coarse. Update PLAN §4 in the same
  commit if built.
- **Watchlist Workable boards** — boards.py covers Greenhouse/Lever/Ashby;
  add Workable's public API only if a watched company actually uses it.
- **Browser extension, outreach drafts, weekly AI summary** — stretch list
  in PLAN §11, unchanged.

## Suggested cadence

M0+M1 can land in a day; demo after M2 (that's the reveal to Andy — see
docs/DEMO.md when it exists). M3+M4 next; M5 deserves unhurried attention
and live testing on real postings; M6 closes the loop. Andy will have
opinions from the moment he sees M2 — from then on, treat him as the product
owner and fold his requests into milestone prompts.

---

## Session log & handoff notes (updated after M7b)

**State: M0–M6 complete; gloss items M7a and M7b landed.** M7a (merged,
PR #7) added the optional PIN gate for non-local access. M7b added Ashby
and Workable fillers on the exact Greenhouse/Lever pattern: fixture forms
model real `jobs.ashbyhq.com` (`_systemfield_*` ids, form-tab URL at
`…/application`) and `apply.workable.com` (`data-ui` attributes, form at
`…/apply`) markup; `ats.apply_url` rewrites to the form page only on the
boards' own hosts (company-site embeds and file:// fixtures pass through
untouched); both kinds joined `ats.SUPPORTED`, and the /apply settings
page + save route now iterate `ats.SUPPORTED` dynamically instead of a
hardcoded pair (regression-tested with a fake kind). Full filler matrix
mirrored per new ATS: fill accuracy, unmatched-required refusal, CAPTCHA
refusal, end-to-end auto-submit. Greenhouse/Lever fillers untouched.
Remaining M7 items: M7c–M7f below. Live verification on Andy's machine is
still owed for everything browser/network-shaped (now including one real
Ashby and one real Workable assisted apply).

**Earlier state (after M6):** M0–M5 were merged to `main` (PR #3); M6 was
built on `claude/main-branch-review-test-xz4rc1` after a review pass over
the merged main (one real finding: a double-start race in apply session
launch, fixed with a regression test). M6 delivered: PWA manifest +
root-scope service worker + Android share-target into capture (icons are
checked-in PNGs generated by a stdlib script — no build step); ntfy
notifier (/notify page, digest once per local day at a configured hour,
due reminders pushed exactly once via reminders.notified_at); metrics
page (applications/week, response rate by source and score band);
watchlist sources for Greenhouse/Lever/Ashby public boards with a +10
scoring boost; Adzuna + USAJOBS adapters with keys entered in the UI
(profile table, env fallback, merged into config only at fetch time,
sources hidden until keys exist); docs/RUNNING.md + docs/PHONE.md
zero-jargon guides linked from README. Version bumped to 0.2.0. Still 4
migrations — 004 had already added reminders.notified_at for M6.

**Owner context (unchanged, important):** the requester is non-technical,
building Wingman as a gift for Andy. (1) Every Andy-specific parameter
must be enterable in the app UI — honored through M5 (per-ATS auto-submit
toggles, daily cap, cooldown are all on /apply). Keep it for M6: ntfy
topic, watchlist companies, Adzuna/USAJOBS keys get a settings UI (env
fallback allowed, UI path required). (2) **M6 is the requester's
acceptance test**: idiot-proof zero-jargon run guides (Windows/Mac
dev-mode, no systemd) + phone guide (same Wi-Fi, Tailscale optional,
add-to-home-screen; no standalone APK — say so plainly) in docs/, linked
from README. Send UI screenshots after each milestone — done for M5.

**Working notes for the next session:**
- All planned milestones are done. Remaining work is specced as
  ready-to-paste prompts in §M7 above (written by Fable before access
  ended; sized for Sonnet). Do M7a (PIN gate) before Andy exposes the
  app beyond localhost. The other standing item is the first live
  verification pass on Andy's machine — fillers, watchlist fetches, and
  ntfy pushes were all verified on fixtures only (the sandbox has no
  outbound network and no display).
- Sandbox facts that still hold: fixtures + local servers for tests;
  headless Chromium at /opt/pw-browsers/chromium (tests auto-detect it;
  `WINGMAN_BROWSER` overrides). A real `claude` CLI exists at
  /opt/node22/bin/claude.
- Review cadence that worked: inline review (finder subagents hit usage
  limits); verify candidates empirically before fixing; every fix gets a
  regression test.
- Deliberate decisions (don't re-litigate without cause): one
  applications row per job; remote=NULL passes remote-only filters;
  threshold in profile table; capture may fetch private-network URLs
  (single-user localhost app, size-capped); auto-submit records the
  application even when no confirmation page was detected (avoids
  double-applying; screenshot + confirmed=false mark it for review);
  engine flows always run in worker threads (sync Playwright must not
  share a thread with another live sync-Playwright loop — tests mirror
  this); "response" in metrics means interviewing/offer/rejected —
  applied-and-silent and ghosted count against the response rate; the
  ntfy topic and board API keys are treated as secrets (never in events
  or raw_json; keys merged into adapter config only at fetch time).
