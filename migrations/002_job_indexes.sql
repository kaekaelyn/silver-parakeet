-- Indexes for columns the ingestion path queries: dedupe checks look up
-- jobs by url, and the sources page aggregates jobs by source_id.

CREATE INDEX idx_jobs_url ON jobs(url);
CREATE INDEX idx_jobs_source_id ON jobs(source_id);
