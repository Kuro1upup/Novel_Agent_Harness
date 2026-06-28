package repository

import (
	"context"
	"database/sql"
	"fmt"
	"time"
)

// SaveVerificationCode invalidates existing codes for the same target+purpose,
// then inserts a new one. Runs inside a transaction.
func (r *UserRepo) SaveVerificationCode(ctx context.Context, userID int64, target, code string, purpose int, expiresAt time.Time) error {
	tx, err := r.db.BeginTx(ctx, nil)
	if err != nil {
		return fmt.Errorf("begin tx: %w", err)
	}
	defer tx.Rollback()

	// Invalidate old unused codes for the same target+purpose.
	_, err = tx.ExecContext(ctx,
		`UPDATE verification_codes SET used = 1, used_at = NOW()
		 WHERE target = ? AND purpose = ? AND used = 0 AND expires_at > NOW()`,
		target, purpose,
	)
	if err != nil {
		return fmt.Errorf("invalidate old codes: %w", err)
	}

	// Insert the new code.
	_, err = tx.ExecContext(ctx,
		`INSERT INTO verification_codes (user_id, target, code, purpose, expires_at)
		 VALUES (?, ?, ?, ?, ?)`,
		userID, target, code, purpose, expiresAt,
	)
	if err != nil {
		return fmt.Errorf("insert code: %w", err)
	}

	return tx.Commit()
}

// ConsumeVerificationCode atomically validates and marks a code as used.
// Returns the user_id associated with the code entry.
// Uses SELECT ... FOR UPDATE to prevent concurrent consumption.
func (r *UserRepo) ConsumeVerificationCode(ctx context.Context, target, code string, purpose int) (int64, error) {
	tx, err := r.db.BeginTx(ctx, &sql.TxOptions{Isolation: sql.LevelReadCommitted})
	if err != nil {
		return 0, fmt.Errorf("begin tx: %w", err)
	}
	defer tx.Rollback()

	var id, userID int64
	var expiresAt time.Time
	var used int

	err = tx.QueryRowContext(ctx,
		`SELECT id, user_id, expires_at, used
		 FROM verification_codes
		 WHERE target = ? AND code = ? AND purpose = ?
		 ORDER BY id DESC LIMIT 1
		 FOR UPDATE`,
		target, code, purpose,
	).Scan(&id, &userID, &expiresAt, &used)
	if err == sql.ErrNoRows {
		return 0, fmt.Errorf("验证码无效")
	}
	if err != nil {
		return 0, fmt.Errorf("query code: %w", err)
	}

	if used == 1 {
		return 0, fmt.Errorf("验证码已使用")
	}

	if time.Now().UTC().After(expiresAt) {
		return 0, fmt.Errorf("验证码已过期")
	}

	// Mark as used.
	_, err = tx.ExecContext(ctx,
		`UPDATE verification_codes SET used = 1, used_at = NOW() WHERE id = ?`, id,
	)
	if err != nil {
		return 0, fmt.Errorf("mark code used: %w", err)
	}

	if err := tx.Commit(); err != nil {
		return 0, fmt.Errorf("commit: %w", err)
	}

	return userID, nil
}

// SavePasswordResetToken stores a password reset token for a user.
func (r *UserRepo) SavePasswordResetToken(ctx context.Context, userID int64, token string, expiresAt time.Time) error {
	_, err := r.db.ExecContext(ctx,
		`INSERT INTO password_reset_tokens (user_id, token, expires_at) VALUES (?, ?, ?)`,
		userID, token, expiresAt,
	)
	if err != nil {
		return fmt.Errorf("insert reset token: %w", err)
	}
	return nil
}

// ConsumePasswordResetToken validates, consumes, and returns the user_id
// for a password reset token. Returns an error if invalid, expired, or already used.
func (r *UserRepo) ConsumePasswordResetToken(ctx context.Context, token string) (int64, error) {
	tx, err := r.db.BeginTx(ctx, &sql.TxOptions{Isolation: sql.LevelReadCommitted})
	if err != nil {
		return 0, fmt.Errorf("begin tx: %w", err)
	}
	defer tx.Rollback()

	var id, userID int64
	var expiresAt time.Time
	var used int

	err = tx.QueryRowContext(ctx,
		`SELECT id, user_id, expires_at, used
		 FROM password_reset_tokens
		 WHERE token = ?
		 FOR UPDATE`, token,
	).Scan(&id, &userID, &expiresAt, &used)
	if err == sql.ErrNoRows {
		return 0, fmt.Errorf("重置链接无效")
	}
	if err != nil {
		return 0, fmt.Errorf("query token: %w", err)
	}

	if used == 1 {
		return 0, fmt.Errorf("重置链接已使用")
	}

	if time.Now().UTC().After(expiresAt) {
		return 0, fmt.Errorf("重置链接已过期，请在 5 分钟内使用")
	}

	_, err = tx.ExecContext(ctx,
		`UPDATE password_reset_tokens SET used = 1 WHERE id = ?`, id,
	)
	if err != nil {
		return 0, fmt.Errorf("mark token used: %w", err)
	}

	if err := tx.Commit(); err != nil {
		return 0, fmt.Errorf("commit: %w", err)
	}

	return userID, nil
}
