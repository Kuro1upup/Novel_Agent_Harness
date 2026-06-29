package repository

import (
	"database/sql"
	"fmt"
	"log"
)

// DDL statements for billing tables (matching Python exactly).
const (
	ddlTokenUsageRecords = `
	CREATE TABLE IF NOT EXISTS token_usage_records (
		id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
		event_id VARCHAR(128) NULL,
		user_id BIGINT UNSIGNED NOT NULL,
		model VARCHAR(128) NOT NULL,
		subsystem VARCHAR(64) NOT NULL,
		input_tokens INT UNSIGNED NOT NULL DEFAULT 0,
		cache_hit_tokens INT UNSIGNED NOT NULL DEFAULT 0,
		cache_miss_tokens INT UNSIGNED NOT NULL DEFAULT 0,
		output_tokens INT UNSIGNED NOT NULL DEFAULT 0,
		total_tokens INT UNSIGNED NOT NULL DEFAULT 0,
		created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
		PRIMARY KEY (id),
		UNIQUE KEY uq_usage_event_id (event_id),
		KEY idx_usage_user_created (user_id, created_at),
		KEY idx_usage_user_month (user_id, created_at, model)
	) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci`

	ddlBills = `
	CREATE TABLE IF NOT EXISTS bills (
		id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
		user_id BIGINT UNSIGNED NOT NULL,
		bill_month VARCHAR(7) NOT NULL COMMENT 'YYYY-MM',
		model VARCHAR(128) NOT NULL,
		total_input_tokens INT UNSIGNED NOT NULL DEFAULT 0,
		total_cache_hit_tokens INT UNSIGNED NOT NULL DEFAULT 0,
		total_cache_miss_tokens INT UNSIGNED NOT NULL DEFAULT 0,
		total_output_tokens INT UNSIGNED NOT NULL DEFAULT 0,
		cost_yuan DECIMAL(12,6) NOT NULL DEFAULT 0.000000,
		created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
		updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
		PRIMARY KEY (id),
		UNIQUE KEY uq_bills_user_month_model (user_id, bill_month, model)
	) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci`

	ddlRecharges = `
	CREATE TABLE IF NOT EXISTS recharges (
		id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
		user_id BIGINT UNSIGNED NOT NULL,
		amount_yuan DECIMAL(12,2) NOT NULL DEFAULT 0.00,
		note VARCHAR(500) NOT NULL DEFAULT '',
		created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
		PRIMARY KEY (id),
		KEY idx_recharges_user (user_id, created_at)
	) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci`
)

// EnsureSchema creates billing tables if they don't exist.
func EnsureSchema(db *sql.DB) error {
	statements := []string{ddlTokenUsageRecords, ddlBills, ddlRecharges}

	for _, stmt := range statements {
		if _, err := db.Exec(stmt); err != nil {
			return fmt.Errorf("ensure schema: %w", err)
		}
	}

	usageUpgradeStmts := []string{
		"ALTER TABLE token_usage_records ADD COLUMN event_id VARCHAR(128) NULL AFTER id",
		"CREATE UNIQUE INDEX uq_usage_event_id ON token_usage_records (event_id)",
	}
	for _, stmt := range usageUpgradeStmts {
		if _, err := db.Exec(stmt); err != nil && !isDuplicateSchemaError(err) {
			return fmt.Errorf("upgrade usage schema: %w", err)
		}
	}

	log.Println("Billing tables ensured successfully")
	return nil
}

func isDuplicateSchemaError(err error) bool {
	if err == nil {
		return false
	}
	message := err.Error()
	return contains(message, "Duplicate column name") ||
		contains(message, "Duplicate key name") ||
		contains(message, "Error 1060") ||
		contains(message, "Error 1061")
}

func contains(s, substr string) bool {
	for i := 0; i <= len(s)-len(substr); i++ {
		if s[i:i+len(substr)] == substr {
			return true
		}
	}
	return false
}
