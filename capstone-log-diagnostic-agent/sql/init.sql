CREATE TABLE IF NOT EXISTS validated_incidents (
    incident_id TEXT PRIMARY KEY,
    application TEXT NOT NULL,
    component TEXT,
    error_family TEXT,
    symptoms TEXT NOT NULL,
    validated_diagnosis TEXT NOT NULL,
    evidence_summary TEXT NOT NULL,
    resolution TEXT,
    validation_status TEXT NOT NULL CHECK (validation_status = 'validated'),
    review_status TEXT NOT NULL CHECK (review_status IN ('confirmed', 'corrected')),
    reviewed_by TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    embedding VECTOR(384) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Safe migration path for a table created by an earlier prototype.
ALTER TABLE validated_incidents
    ADD COLUMN IF NOT EXISTS review_status TEXT NOT NULL DEFAULT 'confirmed';
ALTER TABLE validated_incidents
    ADD COLUMN IF NOT EXISTS reviewed_by TEXT NOT NULL DEFAULT 'legacy_import';

CREATE TABLE IF NOT EXISTS incident_memory (
    incident_id TEXT PRIMARY KEY,
    state JSONB NOT NULL,
    final_report JSONB,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS human_reviews (
    review_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    incident_id TEXT NOT NULL,
    reviewer TEXT NOT NULL,
    decision TEXT NOT NULL CHECK (decision IN ('confirm', 'correct', 'reject')),
    corrected_root_cause TEXT,
    actual_remediation TEXT,
    notes TEXT,
    reviewed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS agent_audit_events (
    event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    incident_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
