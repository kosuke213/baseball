PRAGMA foreign_keys=ON;
CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE artifacts (
 artifact_id TEXT PRIMARY KEY, sha256 TEXT NOT NULL, byte_count INTEGER NOT NULL CHECK(byte_count>0),
 metadata_json TEXT NOT NULL
);
CREATE TABLE source_schemas (
 artifact_id TEXT PRIMARY KEY REFERENCES artifacts, member TEXT NOT NULL,
 columns_json TEXT NOT NULL, scanned_rows INTEGER NOT NULL CHECK(scanned_rows>=0)
);
CREATE TABLE teams (
 team_id TEXT PRIMARY KEY, namespace TEXT NOT NULL CHECK(namespace='retrosheet'),
 source_code TEXT NOT NULL UNIQUE, display_name TEXT
);
CREATE TABLE team_seasons (
 team_id TEXT NOT NULL REFERENCES teams, season INTEGER NOT NULL,
 league_code TEXT NOT NULL, artifact_id TEXT NOT NULL REFERENCES artifacts, source_row INTEGER NOT NULL,
 PRIMARY KEY(team_id,season)
);
CREATE TABLE parks (
 park_id TEXT PRIMARY KEY, namespace TEXT NOT NULL CHECK(namespace='retrosheet'), source_code TEXT NOT NULL UNIQUE,
 name_as_published TEXT, city TEXT, region TEXT, opened_raw TEXT, closed_raw TEXT,
 metadata_status TEXT NOT NULL CHECK(metadata_status IN ('documented','unresolved')),
 artifact_id TEXT REFERENCES artifacts, source_row INTEGER, raw_json TEXT
);
CREATE TABLE games (
 game_id TEXT PRIMARY KEY, source_game_id TEXT NOT NULL UNIQUE, season INTEGER NOT NULL,
 start_date TEXT NOT NULL, game_number TEXT NOT NULL,
 visiting_team_id TEXT NOT NULL REFERENCES teams, home_team_id TEXT NOT NULL REFERENCES teams,
 park_id TEXT NOT NULL REFERENCES parks,
 visiting_runs INTEGER NOT NULL CHECK(visiting_runs>=0), home_runs INTEGER NOT NULL CHECK(home_runs>=0),
 outs INTEGER NOT NULL CHECK(outs>=0), attendance INTEGER CHECK(attendance>=0),
 duration_minutes INTEGER CHECK(duration_minutes>=0), visiting_line_score TEXT, home_line_score TEXT,
 completion_info_raw TEXT, acquisition_code TEXT, additional_info_raw TEXT,
 artifact_id TEXT NOT NULL REFERENCES artifacts, source_row INTEGER NOT NULL, raw_json TEXT NOT NULL,
 FOREIGN KEY(visiting_team_id,season) REFERENCES team_seasons,
 FOREIGN KEY(home_team_id,season) REFERENCES team_seasons
);
CREATE TABLE game_team_stats (
 game_id TEXT NOT NULL REFERENCES games, side INTEGER NOT NULL CHECK(side IN (0,1)),
 team_id TEXT NOT NULL REFERENCES teams,
 at_bats INTEGER, hits INTEGER, doubles INTEGER, triples INTEGER, home_runs INTEGER,
 walks INTEGER, strikeouts INTEGER, PRIMARY KEY(game_id,side)
);
CREATE TABLE people (
 person_id TEXT PRIMARY KEY, chadwick_uuid TEXT NOT NULL UNIQUE,
 name_first TEXT, name_last TEXT, birth_year INTEGER,
 artifact_id TEXT NOT NULL REFERENCES artifacts, source_row INTEGER NOT NULL, raw_json TEXT NOT NULL
);
CREATE TABLE identifiers (
 namespace TEXT NOT NULL, identifier TEXT NOT NULL, person_id TEXT NOT NULL REFERENCES people,
 artifact_id TEXT NOT NULL REFERENCES artifacts, source_row INTEGER NOT NULL,
 PRIMARY KEY(namespace,identifier,person_id)
);
CREATE TABLE player_matches (
 retrosheet_id TEXT PRIMARY KEY, status TEXT NOT NULL CHECK(status IN ('matched','unmatched','ambiguous')),
 person_id TEXT REFERENCES people, candidate_count INTEGER NOT NULL CHECK(candidate_count>=0),
 CHECK((status='matched' AND candidate_count=1 AND person_id IS NOT NULL)
 OR (status='unmatched' AND candidate_count=0 AND person_id IS NULL)
 OR (status='ambiguous' AND candidate_count>1 AND person_id IS NULL))
);
CREATE TABLE plays (
 game_id TEXT NOT NULL REFERENCES games, play_number INTEGER NOT NULL CHECK(play_number>0),
 inning INTEGER NOT NULL CHECK(inning>0), half INTEGER NOT NULL CHECK(half IN (0,1)),
 batting_side INTEGER NOT NULL CHECK(batting_side IN (0,1)), event_date TEXT NOT NULL,
 batting_team_id TEXT NOT NULL REFERENCES teams, pitching_team_id TEXT NOT NULL REFERENCES teams,
 park_id TEXT NOT NULL REFERENCES parks,
 batter_retro_id TEXT NOT NULL, pitcher_retro_id TEXT NOT NULL,
 event_raw TEXT NOT NULL, pbp_type TEXT NOT NULL,
 visiting_score_pre INTEGER NOT NULL CHECK(visiting_score_pre>=0), home_score_pre INTEGER NOT NULL CHECK(home_score_pre>=0),
 outs_pre INTEGER NOT NULL CHECK(outs_pre BETWEEN 0 AND 3), outs_post INTEGER NOT NULL CHECK(outs_post BETWEEN outs_pre AND 3),
 runs INTEGER NOT NULL CHECK(runs>=0),
 runner1_pre TEXT, runner2_pre TEXT, runner3_pre TEXT, runner1_post TEXT, runner2_post TEXT, runner3_post TEXT,
 balls INTEGER, strikes INTEGER, count_raw TEXT, pitches_raw TEXT, pitch_count INTEGER,
 plate_appearance INTEGER NOT NULL, at_bat INTEGER NOT NULL, single INTEGER NOT NULL,
 double INTEGER NOT NULL, triple INTEGER NOT NULL, home_run INTEGER NOT NULL,
 walk INTEGER NOT NULL, strikeout INTEGER NOT NULL, intentional_walk INTEGER NOT NULL,
 batter_hand TEXT, pitcher_hand TEXT,
 artifact_id TEXT NOT NULL REFERENCES artifacts, source_row INTEGER NOT NULL,
 PRIMARY KEY(game_id,play_number),
 CHECK(outs_pre<3 OR (event_raw='NP' AND outs_post=3 AND plate_appearance=0 AND runs=0))
);
CREATE INDEX plays_batter ON plays(batter_retro_id,game_id);
CREATE INDEX plays_pitcher ON plays(pitcher_retro_id,game_id);
CREATE TABLE game_checks (
 game_id TEXT PRIMARY KEY REFERENCES games, status TEXT NOT NULL CHECK(status IN ('pass','review_required','missing_plays')),
 play_rows INTEGER NOT NULL, counters_json TEXT NOT NULL, failures_json TEXT NOT NULL
);
CREATE TABLE excluded_game_groups (
 artifact_id TEXT NOT NULL REFERENCES artifacts, source_game_id TEXT NOT NULL,
 game_type TEXT NOT NULL, reason TEXT NOT NULL, row_count INTEGER NOT NULL,
 PRIMARY KEY(artifact_id,source_game_id)
);
CREATE TABLE stations (
 station_id TEXT PRIMARY KEY, namespace TEXT NOT NULL, source_code TEXT NOT NULL,
 display_name TEXT NOT NULL, timezone TEXT NOT NULL
);
CREATE TABLE weather_observations (
 station_id TEXT NOT NULL REFERENCES stations, timestamp_utc TEXT NOT NULL, timestamp_local TEXT NOT NULL,
 metric TEXT NOT NULL, unit TEXT NOT NULL, value REAL, raw_text TEXT NOT NULL,
 parse_status TEXT NOT NULL CHECK(parse_status IN ('numeric','categorical','empty','symbol_or_flagged')),
 cell_attributes_json TEXT NOT NULL, artifact_id TEXT NOT NULL REFERENCES artifacts, source_row INTEGER NOT NULL,
 PRIMARY KEY(station_id,timestamp_utc,metric)
);
CREATE TABLE secondary_claims (
 claim_id TEXT PRIMARY KEY, subject_label TEXT NOT NULL, claim_type TEXT NOT NULL,
 verification_status TEXT NOT NULL, person_id TEXT REFERENCES people,
 artifact_id TEXT NOT NULL REFERENCES artifacts, source_row INTEGER NOT NULL, raw_json TEXT NOT NULL
);
CREATE VIEW game_results AS
 SELECT game_id,season,start_date,game_number,visiting_team_id,home_team_id,
 visiting_runs,home_runs,outs,park_id,attendance,duration_minutes FROM games;
CREATE VIEW analysis_plays AS
 SELECT p.*,b.person_id AS batter_person_id,t.person_id AS pitcher_person_id,
 b.status AS batter_match_status,t.status AS pitcher_match_status
 FROM plays p JOIN game_checks q ON q.game_id=p.game_id AND q.status='pass'
 LEFT JOIN player_matches b ON b.retrosheet_id=p.batter_retro_id
 LEFT JOIN player_matches t ON t.retrosheet_id=p.pitcher_retro_id
 WHERE p.pbp_type='full';
