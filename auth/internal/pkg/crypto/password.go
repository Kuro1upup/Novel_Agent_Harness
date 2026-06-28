package crypto

import (
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"

	"golang.org/x/crypto/pbkdf2"
)

const (
	// Must match Python: 100000 iterations, SHA-256, 32-byte salt.
	pbkdf2Iterations = 100000
	pbkdf2KeyLen     = 32 // SHA-256 produces 32-byte output
	saltLen          = 32
)

// HashPassword hashes a plaintext password using PBKDF2-HMAC-SHA256.
// Returns the hex-encoded hash and hex-encoded salt.
// This is compatible with Python's hashlib.pbkdf2_hmac('sha256', password, salt, 100000).
func HashPassword(password string) (hashHex string, saltHex string, err error) {
	salt := make([]byte, saltLen)
	if _, err := rand.Read(salt); err != nil {
		return "", "", err
	}

	hash := pbkdf2.Key([]byte(password), salt, pbkdf2Iterations, pbkdf2KeyLen, sha256.New)
	return hex.EncodeToString(hash), hex.EncodeToString(salt), nil
}

// VerifyPassword checks a password against a stored hash and salt.
// Uses hmac.Equal for constant-time comparison (matches Python's hmac.compare_digest).
func VerifyPassword(password, hashHex, saltHex string) bool {
	salt, err := hex.DecodeString(saltHex)
	if err != nil {
		return false
	}
	expectedHash, err := hex.DecodeString(hashHex)
	if err != nil {
		return false
	}

	computed := pbkdf2.Key([]byte(password), salt, pbkdf2Iterations, pbkdf2KeyLen, sha256.New)
	return hmac.Equal(computed, expectedHash)
}
