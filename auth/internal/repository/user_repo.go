package repository

import (
	"crypto/rand"
	"database/sql"
	"encoding/hex"
	"fmt"
	"log"
	"strings"
	"time"

	"second-brain/auth/internal/domain"
	pwdcrypto "second-brain/auth/internal/pkg/crypto"

	"github.com/go-sql-driver/mysql"
)

// UserRepo implements MySQL-backed user persistence.
type UserRepo struct {
	db *sql.DB
}

// NewUserRepo creates a new UserRepo with the given database connection.
func NewUserRepo(db *sql.DB) *UserRepo {
	return &UserRepo{db: db}
}

// Register inserts a new user. method must be "email" or "phone".
// The provided contact becomes the default nickname and is marked verified.
func (r *UserRepo) Register(email, phone, password, method string) (*domain.User, error) {
	hashHex, saltHex, err := pwdcrypto.HashPassword(password)
	if err != nil {
		return nil, fmt.Errorf("hash password: %w", err)
	}

	now := time.Now().UTC()

	// Determine the default nickname from the chosen registration method.
	nickname := email
	if method == "phone" {
		nickname = phone
	}

	emailVerified := method == "email"
	phoneVerified := method == "phone"

	result, err := r.db.Exec(
		`INSERT INTO users (email, phone, password_hash, salt, nickname, bio,
		 email_verified, phone_verified, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`,
		email, phone, hashHex, saltHex, nickname, "",
		emailVerified, phoneVerified, now,
	)
	if err != nil {
		if me, ok := err.(*mysql.MySQLError); ok && me.Number == 1062 {
			if strings.Contains(me.Message, "uk_users_email") {
				return nil, fmt.Errorf("该邮箱已被注册")
			}
			return nil, fmt.Errorf("该联系方式已被注册")
		}
		return nil, fmt.Errorf("insert user: %w", err)
	}

	id, _ := result.LastInsertId()
	return &domain.User{
		ID:            id,
		Email:         email,
		Phone:         phone,
		Nickname:      nickname,
		EmailVerified: emailVerified,
		PhoneVerified: phoneVerified,
		CreatedAt:     now,
	}, nil
}

// Login verifies credentials by looking up the user via email OR phone.
// The login parameter can be either an email address or a phone number.
func (r *UserRepo) Login(login, password string) (*domain.User, string, error) {
	var u domain.User
	var hashHex, saltHex string
	var createdAt time.Time
	var emailVerified, phoneVerified bool

	err := r.db.QueryRow(
		`SELECT id, email, phone, password_hash, salt, nickname, avatar_url,
		        age, gender, bio, email_verified, phone_verified, created_at
		 FROM users WHERE email = ? OR phone = ?`, login, login,
	).Scan(&u.ID, &u.Email, &u.Phone, &hashHex, &saltHex,
		&u.Nickname, &u.AvatarURL, &u.Age, &u.Gender, &u.Bio,
		&emailVerified, &phoneVerified, &createdAt)
	if err == sql.ErrNoRows {
		return nil, "", fmt.Errorf("邮箱/手机号或密码错误")
	}
	if err != nil {
		return nil, "", fmt.Errorf("query user: %w", err)
	}
	u.EmailVerified = emailVerified
	u.PhoneVerified = phoneVerified
	u.CreatedAt = createdAt

	if !pwdcrypto.VerifyPassword(password, hashHex, saltHex) {
		return nil, "", fmt.Errorf("邮箱/手机号或密码错误")
	}

	// Generate legacy random token.
	token, err := generateRandomToken()
	if err != nil {
		return nil, "", fmt.Errorf("generate token: %w", err)
	}

	// Retry up to 3 times on duplicate token collision.
	var tokenID int64
	for attempt := 0; attempt < 3; attempt++ {
		result, err := r.db.Exec(
			`INSERT INTO user_tokens (user_id, token, created_at) VALUES (?, ?, ?)`,
			u.ID, token, time.Now().UTC(),
		)
		if err != nil {
			if me, ok := err.(*mysql.MySQLError); ok && me.Number == 1062 {
				token, _ = generateRandomToken()
				continue
			}
			return nil, "", fmt.Errorf("insert token: %w", err)
		}
		tokenID, _ = result.LastInsertId()
		break
	}
	if tokenID == 0 {
		return nil, "", fmt.Errorf("failed to generate unique token after retries")
	}

	return &u, token, nil
}

// GetByToken looks up a user by their session token.
func (r *UserRepo) GetByToken(token string) (*domain.User, error) {
	var u domain.User
	var createdAt, lastUsedAt time.Time
	var emailVerified, phoneVerified bool

	err := r.db.QueryRow(
		`SELECT u.id, u.email, u.phone, u.nickname, u.avatar_url,
		        u.age, u.gender, u.bio, u.email_verified, u.phone_verified,
		        u.created_at, t.last_used_at
		 FROM users u
		 JOIN user_tokens t ON u.id = t.user_id
		 WHERE t.token = ?`, token,
	).Scan(&u.ID, &u.Email, &u.Phone, &u.Nickname, &u.AvatarURL,
		&u.Age, &u.Gender, &u.Bio, &emailVerified, &phoneVerified,
		&createdAt, &lastUsedAt)

	if err == sql.ErrNoRows {
		err = r.db.QueryRow(
			`SELECT id, email, phone, nickname, avatar_url,
			        age, gender, bio, email_verified, phone_verified, created_at
			 FROM users WHERE token = ?`, token,
		).Scan(&u.ID, &u.Email, &u.Phone, &u.Nickname, &u.AvatarURL,
			&u.Age, &u.Gender, &u.Bio, &emailVerified, &phoneVerified, &createdAt)
		if err == sql.ErrNoRows {
			return nil, nil
		}
		if err != nil {
			return nil, fmt.Errorf("legacy token query: %w", err)
		}
		u.EmailVerified = emailVerified
		u.PhoneVerified = phoneVerified
		u.CreatedAt = createdAt
		return &u, nil
	}
	if err != nil {
		return nil, fmt.Errorf("token query: %w", err)
	}
	u.EmailVerified = emailVerified
	u.PhoneVerified = phoneVerified
	u.CreatedAt = createdAt

	go func() {
		if _, err := r.db.Exec(`UPDATE user_tokens SET last_used_at = ? WHERE token = ?`,
			time.Now().UTC(), token); err != nil {
			log.Printf("WARNING: update last_used_at failed: %v", err)
		}
	}()

	return &u, nil
}

// GetProfile returns a user's public profile (no password hash).
func (r *UserRepo) GetProfile(userID int64) (map[string]interface{}, error) {
	var u domain.User
	var createdAt time.Time
	var emailVerified, phoneVerified bool
	var birthday sql.NullString

	err := r.db.QueryRow(
		`SELECT id, email, phone, nickname, avatar_url,
		        age, gender, bio, birthday, email_verified, phone_verified, created_at
		 FROM users WHERE id = ?`, userID,
	).Scan(&u.ID, &u.Email, &u.Phone, &u.Nickname, &u.AvatarURL,
		&u.Age, &u.Gender, &u.Bio, &birthday, &emailVerified, &phoneVerified, &createdAt)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("get profile: %w", err)
	}
	u.CreatedAt = createdAt
	u.EmailVerified = emailVerified
	u.PhoneVerified = phoneVerified

	if birthday.Valid {
		u.Birthday = birthday.String
	}

	return map[string]interface{}{
		"id":             u.ID,
		"email":          u.Email,
		"phone":          u.Phone,
		"nickname":       u.Nickname,
		"avatar_url":     u.AvatarURL,
		"age":            u.Age,
		"gender":         u.Gender,
		"bio":            u.Bio,
		"birthday":       u.Birthday,
		"email_verified": u.EmailVerified,
		"phone_verified": u.PhoneVerified,
		"created_at":     u.CreatedAt.Format(time.RFC3339),
	}, nil
}

// UpdateProfile applies whitelisted profile field updates.
func (r *UserRepo) UpdateProfile(userID int64, data map[string]interface{}) (map[string]interface{}, error) {
	allowedFields := map[string]bool{
		"nickname": true, "avatar_url": true, "age": true, "gender": true, "bio": true, "birthday": true,
	}

	var setClauses []string
	var args []interface{}

	for key, val := range data {
		if !allowedFields[key] {
			continue
		}
		setClauses = append(setClauses, key+" = ?")
		args = append(args, val)
	}

	if len(setClauses) == 0 {
		return r.GetProfile(userID)
	}

	args = append(args, userID)
	query := fmt.Sprintf("UPDATE users SET %s WHERE id = ?",
		strings.Join(setClauses, ", "))

	if _, err := r.db.Exec(query, args...); err != nil {
		return nil, fmt.Errorf("update profile: %w", err)
	}

	return r.GetProfile(userID)
}

// ── Checks ──

// CheckEmailExists returns true if the email is already registered.
func (r *UserRepo) CheckEmailExists(email string) (bool, error) {
	if email == "" {
		return false, nil
	}
	var count int
	err := r.db.QueryRow(`SELECT COUNT(*) FROM users WHERE email = ?`, email).Scan(&count)
	if err != nil {
		return false, fmt.Errorf("check email: %w", err)
	}
	return count > 0, nil
}

// CheckPhoneExists returns true if the phone is already registered.
func (r *UserRepo) CheckPhoneExists(phone string) (bool, error) {
	if phone == "" {
		return false, nil
	}
	var count int
	err := r.db.QueryRow(`SELECT COUNT(*) FROM users WHERE phone = ?`, phone).Scan(&count)
	if err != nil {
		return false, fmt.Errorf("check phone: %w", err)
	}
	return count > 0, nil
}

// ── User lookup ──

// GetByID fetches a user by primary key (public fields only).
func (r *UserRepo) GetByID(userID int64) (*domain.User, error) {
	var u domain.User
	var createdAt time.Time
	var emailVerified, phoneVerified bool

	err := r.db.QueryRow(
		`SELECT id, email, phone, nickname, email_verified, phone_verified, created_at
		 FROM users WHERE id = ?`, userID,
	).Scan(&u.ID, &u.Email, &u.Phone, &u.Nickname, &emailVerified, &phoneVerified, &createdAt)
	if err == sql.ErrNoRows {
		return nil, fmt.Errorf("用户不存在")
	}
	if err != nil {
		return nil, fmt.Errorf("get user: %w", err)
	}
	u.EmailVerified = emailVerified
	u.PhoneVerified = phoneVerified
	u.CreatedAt = createdAt
	return &u, nil
}

// GetByIDFull returns user with password hash and salt.
func (r *UserRepo) GetByIDFull(userID int64) (*domain.User, error) {
	var u domain.User
	var createdAt time.Time
	var emailVerified, phoneVerified bool

	err := r.db.QueryRow(
		`SELECT id, email, phone, password_hash, salt, nickname,
		        email_verified, phone_verified, created_at
		 FROM users WHERE id = ?`, userID,
	).Scan(&u.ID, &u.Email, &u.Phone, &u.PasswordHash, &u.Salt, &u.Nickname,
		&emailVerified, &phoneVerified, &createdAt)
	if err == sql.ErrNoRows {
		return nil, fmt.Errorf("用户不存在")
	}
	if err != nil {
		return nil, fmt.Errorf("get user full: %w", err)
	}
	u.EmailVerified = emailVerified
	u.PhoneVerified = phoneVerified
	u.CreatedAt = createdAt
	return &u, nil
}

// FindByEmail fetches basic user info by email and returns nil when absent.
func (r *UserRepo) FindByEmail(email string) (*domain.User, error) {
	var u domain.User
	var createdAt time.Time
	var emailVerified, phoneVerified bool

	err := r.db.QueryRow(
		`SELECT id, email, phone, nickname, email_verified, phone_verified, created_at
		 FROM users WHERE email = ?`, email,
	).Scan(&u.ID, &u.Email, &u.Phone, &u.Nickname, &emailVerified, &phoneVerified, &createdAt)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("get by email: %w", err)
	}
	u.EmailVerified = emailVerified
	u.PhoneVerified = phoneVerified
	u.CreatedAt = createdAt
	return &u, nil
}

// GetByEmail fetches basic user info by email.
func (r *UserRepo) GetByEmail(email string) (*domain.User, error) {
	user, err := r.FindByEmail(email)
	if err != nil {
		return nil, err
	}
	if user == nil {
		return nil, fmt.Errorf("用户不存在")
	}
	return user, nil
}

// GetByPhone fetches basic user info by phone.
func (r *UserRepo) GetByPhone(phone string) (*domain.User, error) {
	var u domain.User
	var createdAt time.Time
	var emailVerified, phoneVerified bool

	err := r.db.QueryRow(
		`SELECT id, email, phone, nickname, email_verified, phone_verified, created_at
		 FROM users WHERE phone = ?`, phone,
	).Scan(&u.ID, &u.Email, &u.Phone, &u.Nickname, &emailVerified, &phoneVerified, &createdAt)
	if err == sql.ErrNoRows {
		return nil, fmt.Errorf("用户不存在")
	}
	if err != nil {
		return nil, fmt.Errorf("get by phone: %w", err)
	}
	u.EmailVerified = emailVerified
	u.PhoneVerified = phoneVerified
	u.CreatedAt = createdAt
	return &u, nil
}

// ── Verification updates ──

// MarkEmailVerified sets email_verified = 1 for the given user.
func (r *UserRepo) MarkEmailVerified(userID int64) error {
	_, err := r.db.Exec(`UPDATE users SET email_verified = 1 WHERE id = ?`, userID)
	if err != nil {
		return fmt.Errorf("mark email verified: %w", err)
	}
	return nil
}

// MarkPhoneVerified sets phone_verified = 1 for the given user.
func (r *UserRepo) MarkPhoneVerified(userID int64) error {
	_, err := r.db.Exec(`UPDATE users SET phone_verified = 1 WHERE id = ?`, userID)
	if err != nil {
		return fmt.Errorf("mark phone verified: %w", err)
	}
	return nil
}

// ── Contact method management (adding second method post-registration) ──

// UpdateEmail sets the email address for a user (used when adding email to phone-registered user).
func (r *UserRepo) UpdateEmail(userID int64, email string) error {
	_, err := r.db.Exec(
		`UPDATE users SET email = ?, email_verified = 1 WHERE id = ?`,
		email, userID,
	)
	if err != nil {
		if me, ok := err.(*mysql.MySQLError); ok && me.Number == 1062 {
			return fmt.Errorf("该邮箱已被注册")
		}
		return fmt.Errorf("update email: %w", err)
	}
	return nil
}

// UpdatePhone sets the phone number for a user (used when adding phone to email-registered user).
func (r *UserRepo) UpdatePhone(userID int64, phone string) error {
	_, err := r.db.Exec(
		`UPDATE users SET phone = ?, phone_verified = 1 WHERE id = ?`,
		phone, userID,
	)
	if err != nil {
		if me, ok := err.(*mysql.MySQLError); ok && me.Number == 1062 {
			return fmt.Errorf("该手机号已被注册")
		}
		return fmt.Errorf("update phone: %w", err)
	}
	return nil
}

// ── Password ──

// UpdatePassword hashes the new password and updates the user record.
func (r *UserRepo) UpdatePassword(userID int64, newPassword string) error {
	hashHex, saltHex, err := pwdcrypto.HashPassword(newPassword)
	if err != nil {
		return fmt.Errorf("hash password: %w", err)
	}
	_, err = r.db.Exec(
		`UPDATE users SET password_hash = ?, salt = ? WHERE id = ?`,
		hashHex, saltHex, userID,
	)
	if err != nil {
		return fmt.Errorf("update password: %w", err)
	}
	return nil
}

// InvalidateUserTokens removes all session tokens for a user.
func (r *UserRepo) InvalidateUserTokens(userID int64) error {
	_, err := r.db.Exec(`DELETE FROM user_tokens WHERE user_id = ?`, userID)
	if err != nil {
		return fmt.Errorf("invalidate tokens: %w", err)
	}
	return nil
}

// generateRandomToken creates a URL-safe random token (32 bytes, hex-encoded = 64 chars).
func generateRandomToken() (string, error) {
	b := make([]byte, 32)
	if _, err := rand.Read(b); err != nil {
		return "", err
	}
	return hex.EncodeToString(b), nil
}
