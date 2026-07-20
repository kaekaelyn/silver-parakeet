"""The apply engine (PLAN §5): ATS detection, form fillers, guarded submit.

Tier 1 (default) fills a visible browser and the human submits. Tier 2
(opt-in, per-ATS) may submit unattended — but never with unmatched
required fields, never on a CAPTCHA, never over the daily cap or inside
a company cooldown. Those guardrails are tested behavior.
"""
