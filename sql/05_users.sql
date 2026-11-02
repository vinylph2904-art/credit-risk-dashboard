USE home_credit_ml;

CREATE TABLE IF NOT EXISTS users (
    id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(80) CHARACTER SET ascii COLLATE ascii_general_ci NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    full_name VARCHAR(100) NOT NULL,
    role VARCHAR(24) NOT NULL,
    is_active TINYINT NOT NULL DEFAULT 1,
    session_version INT NOT NULL DEFAULT 1,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    CONSTRAINT ck_user_role CHECK (role IN ('admin','risk_manager','analyst')),
    CONSTRAINT ck_user_active CHECK (is_active IN (0,1))
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS user_audit (
    audit_id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    actor_user_id BIGINT NULL,
    action VARCHAR(40) NOT NULL,
    target_user_id BIGINT NULL,
    detail VARCHAR(255) NOT NULL DEFAULT '',
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    FOREIGN KEY (actor_user_id) REFERENCES users(id) ON DELETE RESTRICT,
    FOREIGN KEY (target_user_id) REFERENCES users(id) ON DELETE RESTRICT
) ENGINE=InnoDB;
