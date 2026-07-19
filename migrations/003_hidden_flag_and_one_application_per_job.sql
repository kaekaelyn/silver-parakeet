-- Hiding a job is a job attribute, not a pipeline state: move it out of
-- applications.state (which M3 will use for the real pipeline) into a
-- flag on jobs, and guarantee at most one application row per job.

ALTER TABLE jobs ADD COLUMN hidden INTEGER NOT NULL DEFAULT 0;

UPDATE jobs SET hidden = 1
 WHERE id IN (SELECT job_id FROM applications WHERE state = 'hidden');
DELETE FROM applications WHERE state = 'hidden';

DELETE FROM applications
 WHERE id NOT IN (SELECT MIN(id) FROM applications GROUP BY job_id);
CREATE UNIQUE INDEX idx_applications_job_id ON applications(job_id);
