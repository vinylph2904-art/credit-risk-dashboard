USE home_credit_ml;

-- Thông tin quản lý hồ sơ demo, tách khỏi đặc trưng nghiên cứu.
CREATE TABLE IF NOT EXISTS demo_profiles (
    profile_id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    source_application_id BIGINT NOT NULL UNIQUE,
    case_label VARCHAR(100) NOT NULL,
    assignee VARCHAR(80) NOT NULL DEFAULT '',
    review_status VARCHAR(24) NOT NULL DEFAULT 'new',
    is_archived TINYINT NOT NULL DEFAULT 0,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    CONSTRAINT fk_demo_source FOREIGN KEY (source_application_id)
        REFERENCES application_features(SK_ID_CURR) ON DELETE RESTRICT,
    CONSTRAINT ck_demo_status CHECK (review_status IN ('new', 'in_review', 'reviewed')),
    CONSTRAINT ck_demo_archived CHECK (is_archived IN (0, 1)),
    INDEX ix_demo_queue (is_archived, review_status)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS model_versions (
    model_version VARCHAR(40) PRIMARY KEY,
    case_id VARCHAR(40) NOT NULL,
    model_path VARCHAR(255) NOT NULL,
    model_sha256 CHAR(64) NOT NULL,
    policy_sha256 CHAR(64) NOT NULL,
    feature_n SMALLINT NOT NULL,
    threshold DOUBLE NOT NULL,
    registered_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    CONSTRAINT ck_version_threshold CHECK (threshold >= 0 AND threshold <= 1),
    CONSTRAINT ck_version_features CHECK (feature_n > 0)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS scoring_events (
    event_id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    profile_id BIGINT NOT NULL,
    model_version VARCHAR(40) NOT NULL,
    score DOUBLE NOT NULL,
    threshold DOUBLE NOT NULL,
    alert TINYINT NOT NULL,
    input_sha256 CHAR(64) NOT NULL,
    -- Giữ nguyên chuỗi JSON để đối soát hash và chữ số của đầu vào DOUBLE.
    input_snapshot LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
    scored_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    CONSTRAINT fk_event_profile FOREIGN KEY (profile_id)
        REFERENCES demo_profiles(profile_id) ON DELETE RESTRICT,
    CONSTRAINT fk_event_version FOREIGN KEY (model_version)
        REFERENCES model_versions(model_version) ON DELETE RESTRICT,
    CONSTRAINT ck_event_score CHECK (score >= 0 AND score <= 1),
    CONSTRAINT ck_event_threshold CHECK (threshold >= 0 AND threshold <= 1),
    CONSTRAINT ck_event_alert CHECK (alert IN (0, 1)),
    CONSTRAINT ck_event_snapshot_json CHECK (JSON_VALID(input_snapshot)),
    INDEX ix_event_latest (profile_id, model_version, event_id),
    INDEX ix_event_time (scored_at)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS review_notes (
    note_id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    event_id BIGINT NOT NULL,
    author VARCHAR(80) NOT NULL,
    content TEXT NOT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    CONSTRAINT fk_note_event FOREIGN KEY (event_id)
        REFERENCES scoring_events(event_id) ON DELETE RESTRICT,
    INDEX ix_note_event (event_id)
) ENGINE=InnoDB;
