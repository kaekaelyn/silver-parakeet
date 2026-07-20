-- Track when an application last changed (board ordering, audit) and
-- when a reminder was last pushed to a notifier (M6 ntfy digest needs it
-- to avoid re-pushing the same reminder every day).

ALTER TABLE applications ADD COLUMN updated_at TEXT;
ALTER TABLE reminders ADD COLUMN notified_at TEXT;

UPDATE applications SET updated_at = coalesce(applied_at, datetime('now'));
