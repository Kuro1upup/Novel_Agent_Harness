package domain

import "time"

// User represents a registered user (matches Python User entity fields).
type User struct {
	ID            int64     `json:"id"`
	Email         string    `json:"email"`
	Phone         string    `json:"phone,omitempty"`
	PasswordHash  string    `json:"-"`
	Salt          string    `json:"-"`
	Nickname      string    `json:"nickname"`
	AvatarURL     string    `json:"avatar_url"`
	Age           int       `json:"age"`
	Gender        string    `json:"gender"`
	Bio           string    `json:"bio"`
	Birthday      string    `json:"birthday,omitempty"`
	EmailVerified bool      `json:"email_verified"`
	PhoneVerified bool      `json:"phone_verified"`
	CreatedAt     time.Time `json:"created_at"`
}

// LoginResult is returned from a successful login.
type LoginResult struct {
	Token string `json:"token"`
	User  User   `json:"user"`
}

// ProfileData mirrors the Python "profile" dict shape.
type ProfileData struct {
	Nickname  string `json:"nickname"`
	AvatarURL string `json:"avatar_url"`
	Age       int    `json:"age"`
	Gender    string `json:"gender"`
	Bio       string `json:"bio"`
}

// JWTClaims carries the standard JWT claims plus user info.
type JWTClaims struct {
	UserID int64  `json:"user_id"`
	Email  string `json:"email"`
}
