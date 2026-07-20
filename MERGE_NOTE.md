# Branch Merge: Syncing execution guide → main

On 2026-07-20, merged the most current work from `claude/wingman-execution-guide-iaisef` into main.

The execution guide branch contained M0-M5 complete implementations, with all review fixes and hardening.

**What was merged:**
- M0: Scaffold + hardened failure paths
- M1: Source adapters, dedupe, polling
- M1 fixes: Parsing, dedupe, robustness improvements
- M2: Boolean query, heuristic scoring, criteria editor
- M2 fixes: Scoring, redirect security, dedupe enforcement
- M3: Tracker, vault, capture, reminders, backup
- M3 fixes: History loss, reminder suppression, capture hardening
- M4: AI providers, batch scoring, cover letters
- M4 fixes: Pending count, batch race, rationale strictness
- M5: Apply engine, ATS detection, Greenhouse/Lever fillers, auto-submit

**Status:** All milestones M0-M5 now on main. Ready for M6 work.
