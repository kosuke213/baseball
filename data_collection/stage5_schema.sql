PRAGMA foreign_keys=ON;
CREATE TABLE research_datasets (
 dataset_id TEXT PRIMARY KEY, artifact_id TEXT NOT NULL REFERENCES artifacts,
 title TEXT NOT NULL, doi TEXT NOT NULL, scope TEXT NOT NULL, country TEXT,
 reported_participants INTEGER, observed_identifiable_participants INTEGER NOT NULL,
 limitations TEXT NOT NULL
);
CREATE TABLE research_participants (
 participant_id TEXT PRIMARY KEY, dataset_id TEXT NOT NULL REFERENCES research_datasets,
 source_id TEXT NOT NULL, UNIQUE(dataset_id,source_id)
);
CREATE TABLE research_measurements (
 measurement_id INTEGER PRIMARY KEY,
 dataset_id TEXT NOT NULL REFERENCES research_datasets,
 participant_id TEXT REFERENCES research_participants,
 metric TEXT NOT NULL, condition TEXT NOT NULL,
 statistic TEXT NOT NULL CHECK(statistic IN
 ('individual','categorical','participant_summary','cohort_summary','correlation','pitch_cycle_summary')),
 value REAL, sd REAL CHECK(sd>=0), reported_n INTEGER CHECK(reported_n>0), n_unit TEXT,
 source_unit TEXT, normalized_value REAL, normalized_sd REAL, normalized_unit TEXT,
 artifact_id TEXT NOT NULL REFERENCES artifacts, source_location TEXT NOT NULL,
 raw_text TEXT NOT NULL,
 CHECK(source_unit IS NOT NULL OR normalized_value IS NULL),
 CHECK((normalized_value IS NULL AND normalized_unit IS NULL) OR
       (normalized_value IS NOT NULL AND normalized_unit IS NOT NULL)),
 UNIQUE(dataset_id,participant_id,metric,condition,statistic,source_location)
);
CREATE INDEX research_by_metric ON research_measurements(metric,statistic);
CREATE TABLE stage5_game_coverage (
 game_id TEXT PRIMARY KEY REFERENCES games,
 coverage TEXT NOT NULL CHECK(coverage IN ('validated_plays','game_log_only')),
 validation_note TEXT NOT NULL
);
CREATE TABLE stage5_source_review (
 source TEXT PRIMARY KEY, status TEXT NOT NULL, evidence_url TEXT NOT NULL,
 evidence_sha256 TEXT, finding TEXT NOT NULL
);
CREATE VIEW research_confirmed_speeds AS
 SELECT * FROM research_measurements
 WHERE normalized_unit='m/s' AND metric IN ('velocity','exit_velocity','bat_speed');
