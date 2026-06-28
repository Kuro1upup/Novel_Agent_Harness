package repository

import (
	"database/sql"
	"fmt"
	"log"
)

// DDL statements — separated for clarity.
const (
	ddlUsers = `
		CREATE TABLE IF NOT EXISTS users (
			id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
			email VARCHAR(255) NOT NULL,
			password_hash VARCHAR(512) NOT NULL DEFAULT '',
			salt VARCHAR(128) NOT NULL DEFAULT '',
			nickname VARCHAR(100) NOT NULL DEFAULT '',
			avatar_url VARCHAR(500) NOT NULL DEFAULT '',
			age INT NOT NULL DEFAULT 0,
			gender VARCHAR(10) NOT NULL DEFAULT '',
			bio VARCHAR(500) NOT NULL DEFAULT '',
			created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
			PRIMARY KEY (id),
			UNIQUE KEY uk_users_email (email)
		) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci`

	ddlUserTokens = `
		CREATE TABLE IF NOT EXISTS user_tokens (
			id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
			user_id BIGINT UNSIGNED NOT NULL,
			token VARCHAR(255) NOT NULL,
			created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
			last_used_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
			PRIMARY KEY (id),
			UNIQUE KEY uk_user_tokens_token (token),
			KEY idx_user_tokens_user (user_id)
		) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci`

	// Profile column migrations (ALTER TABLE — idempotent with IF NOT EXISTS style)
	ddlProfileColumns = `
		ALTER TABLE users
			ADD COLUMN IF NOT EXISTS nickname VARCHAR(100) NOT NULL DEFAULT '',
			ADD COLUMN IF NOT EXISTS avatar_url VARCHAR(500) NOT NULL DEFAULT '',
			ADD COLUMN IF NOT EXISTS age INT NOT NULL DEFAULT 0,
			ADD COLUMN IF NOT EXISTS gender VARCHAR(10) NOT NULL DEFAULT '',
			ADD COLUMN IF NOT EXISTS bio VARCHAR(500) NOT NULL DEFAULT ''`

	// Auth upgrade: phone + verification columns.
	ddlUserPhone = `
		ALTER TABLE users
			ADD COLUMN IF NOT EXISTS phone VARCHAR(20) NOT NULL DEFAULT '',
			ADD COLUMN IF NOT EXISTS email_verified TINYINT(1) NOT NULL DEFAULT 0,
			ADD COLUMN IF NOT EXISTS phone_verified TINYINT(1) NOT NULL DEFAULT 0`

	// Verification codes table (for registration + login verification).
	ddlVerificationCodes = `
		CREATE TABLE IF NOT EXISTS verification_codes (
			id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
			user_id BIGINT UNSIGNED NOT NULL DEFAULT 0,
			target VARCHAR(255) NOT NULL COMMENT 'email or phone',
			code VARCHAR(6) NOT NULL,
			purpose TINYINT NOT NULL COMMENT '1=register, 2=login_verify',
			expires_at TIMESTAMP NOT NULL,
			used TINYINT(1) NOT NULL DEFAULT 0,
			used_at TIMESTAMP NULL,
			sent_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
			PRIMARY KEY (id),
			KEY idx_vc_target_purpose (target, purpose),
			KEY idx_vc_user_purpose (user_id, purpose),
			KEY idx_vc_expires (expires_at)
		) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci`

	// Password reset tokens table.
	ddlPasswordResetTokens = `
		CREATE TABLE IF NOT EXISTS password_reset_tokens (
			id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
			user_id BIGINT UNSIGNED NOT NULL,
			token VARCHAR(64) NOT NULL,
			expires_at TIMESTAMP NOT NULL,
			used TINYINT(1) NOT NULL DEFAULT 0,
			created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
			PRIMARY KEY (id),
			UNIQUE KEY uk_prt_token (token),
			KEY idx_prt_user (user_id)
		) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci`
)

// EnsureSchema creates tables and migrates columns if they don't exist.
func EnsureSchema(db *sql.DB) error {
	statements := []string{ddlUsers, ddlUserTokens, ddlVerificationCodes, ddlPasswordResetTokens}

	for _, stmt := range statements {
		if _, err := db.Exec(stmt); err != nil {
			return fmt.Errorf("ensure schema: %w", err)
		}
	}

	// Profile columns — ALTER TABLE is not idempotent in MySQL 8.0, so try gracefully.
	// MySQL 8.0.32+ supports IF NOT EXISTS for ALTER TABLE ADD COLUMN.
	// For older versions, we catch and ignore "Duplicate column" errors.
	profileStmts := []string{
		"ALTER TABLE users ADD COLUMN nickname VARCHAR(100) NOT NULL DEFAULT ''",
		"ALTER TABLE users ADD COLUMN avatar_url VARCHAR(500) NOT NULL DEFAULT ''",
		"ALTER TABLE users ADD COLUMN age INT NOT NULL DEFAULT 0",
		"ALTER TABLE users ADD COLUMN gender VARCHAR(10) NOT NULL DEFAULT ''",
		"ALTER TABLE users ADD COLUMN bio VARCHAR(500) NOT NULL DEFAULT ''",
	}
	for _, stmt := range profileStmts {
		_, err := db.Exec(stmt)
		if err != nil {
			// MySQL error 1060 = Duplicate column name — ignore.
			if isDupColumnError(err) {
				continue
			}
			log.Printf("WARNING: profile column migration failed (non-fatal): %v", err)
		}
	}

	// Auth upgrade: phone + verification columns (idempotent).
	authUpgradeStmts := []string{
		"ALTER TABLE users ADD COLUMN phone VARCHAR(20) NOT NULL DEFAULT ''",
		"ALTER TABLE users ADD COLUMN email_verified TINYINT(1) NOT NULL DEFAULT 0",
		"ALTER TABLE users ADD COLUMN phone_verified TINYINT(1) NOT NULL DEFAULT 0",
		"ALTER TABLE users ADD COLUMN birthday DATE NULL",
	}
	for _, stmt := range authUpgradeStmts {
		_, err := db.Exec(stmt)
		if err != nil {
			if isDupColumnError(err) {
				continue
			}
			log.Printf("WARNING: auth upgrade column migration failed (non-fatal): %v", err)
		}
	}

	log.Println("Auth schema ensured successfully")
	return nil
}

func isDupColumnError(err error) bool {
	return err != nil && (contains(err.Error(), "Duplicate column name") ||
		contains(err.Error(), "Error 1060"))
}

func contains(s, substr string) bool {
	return len(s) >= len(substr) && searchSubstring(s, substr)
}

func searchSubstring(s, substr string) bool {
	for i := 0; i <= len(s)-len(substr); i++ {
		if s[i:i+len(substr)] == substr {
			return true
		}
	}
	return false
}
