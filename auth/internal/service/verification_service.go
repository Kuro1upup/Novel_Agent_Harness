package service

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"fmt"
	"math/big"
	"sync"
	"time"

	"second-brain/auth/internal/pkg/email"
	"second-brain/auth/internal/pkg/sms"
	"second-brain/auth/internal/repository"
)

const (
	CodeLength        = 6
	CodeValidMinutes  = 5
	RateLimitSeconds  = 60
	ResetTokenMinutes = 5

	PurposeRegister    = 1
	PurposeLoginVerify = 2
)

// In-memory rate limiter: per-target last-send timestamp.
// Simpler and faster than a DB round-trip for rate-limiting decisions.
type rateLimiter struct {
	mu   sync.Mutex
	last map[string]time.Time // key = target + ":" + purpose
}

func newRateLimiter() *rateLimiter {
	return &rateLimiter{last: make(map[string]time.Time)}
}

func (rl *rateLimiter) allow(target string, purpose int) (time.Duration, bool) {
	key := fmt.Sprintf("%s:%d", target, purpose)
	rl.mu.Lock()
	defer rl.mu.Unlock()
	now := time.Now()
	if last, ok := rl.last[key]; ok {
		elapsed := now.Sub(last)
		if elapsed < RateLimitSeconds*time.Second {
			return RateLimitSeconds*time.Second - elapsed, false
		}
	}
	rl.last[key] = now
	return 0, true
}

// VerificationService handles verification code generation, delivery, and validation.
type VerificationService struct {
	repo        *repository.UserRepo
	smsClient   *sms.Client
	emailClient *email.Client
	rateLimiter *rateLimiter
	frontendURL string
}

// NewVerificationService creates a new VerificationService.
// smsClient and emailClient may be nil if not configured.
func NewVerificationService(repo *repository.UserRepo, smsClient *sms.Client, emailClient *email.Client, frontendURL string) *VerificationService {
	return &VerificationService{
		repo:        repo,
		smsClient:   smsClient,
		emailClient: emailClient,
		rateLimiter: newRateLimiter(),
		frontendURL: frontendURL,
	}
}

// GenerateCode creates a random 6-digit code.
func (s *VerificationService) GenerateCode() (string, error) {
	n, err := rand.Int(rand.Reader, big.NewInt(1000000))
	if err != nil {
		return "", fmt.Errorf("generate code: %w", err)
	}
	return fmt.Sprintf("%06d", n.Int64()), nil
}

// SendEmailCode sends a verification code to an email address.
// Handles rate limiting and stores the code in the database.
func (s *VerificationService) SendEmailCode(ctx context.Context, userID int64, emailAddr, userName string, purpose int) error {
	if s.emailClient == nil {
		return fmt.Errorf("邮件服务未配置")
	}

	// Rate limit check.
	wait, ok := s.rateLimiter.allow(emailAddr, purpose)
	if !ok {
		return fmt.Errorf("请 %d 秒后重试", int(wait.Seconds())+1)
	}

	// Generate code.
	code, err := s.GenerateCode()
	if err != nil {
		return err
	}

	// Store in DB.
	expiresAt := time.Now().UTC().Add(CodeValidMinutes * time.Minute)
	if err := s.repo.SaveVerificationCode(ctx, userID, emailAddr, code, purpose, expiresAt); err != nil {
		return fmt.Errorf("保存验证码失败: %w", err)
	}

	// Send via email.
	displayName := userName
	if displayName == "" {
		displayName = emailAddr
	}
	if err := s.emailClient.SendVerificationCode(ctx, emailAddr, displayName, code); err != nil {
		return fmt.Errorf("发送邮件失败: %w", err)
	}
	return nil
}

// SendSmsCode sends a verification code to a phone number.
func (s *VerificationService) SendSmsCode(ctx context.Context, userID int64, phone string, purpose int) error {
	if s.smsClient == nil {
		return fmt.Errorf("短信服务未配置")
	}

	// Rate limit check.
	wait, ok := s.rateLimiter.allow(phone, purpose)
	if !ok {
		return fmt.Errorf("请 %d 秒后重试", int(wait.Seconds())+1)
	}

	// Generate code.
	code, err := s.GenerateCode()
	if err != nil {
		return err
	}

	// Store in DB.
	expiresAt := time.Now().UTC().Add(CodeValidMinutes * time.Minute)
	if err := s.repo.SaveVerificationCode(ctx, userID, phone, code, purpose, expiresAt); err != nil {
		return fmt.Errorf("保存验证码失败: %w", err)
	}

	// Send via SMS.
	if _, err := s.smsClient.SendCode(phone, code); err != nil {
		return fmt.Errorf("发送短信失败: %w", err)
	}
	return nil
}

// VerifyCode checks a code against the DB and marks it used if valid.
// Returns the user_id from the code record.
func (s *VerificationService) VerifyCode(ctx context.Context, target, code string, purpose int) (int64, error) {
	return s.repo.ConsumeVerificationCode(ctx, target, code, purpose)
}

// CreatePasswordResetToken creates a time-limited token for password reset.
func (s *VerificationService) CreatePasswordResetToken(ctx context.Context, userID int64) (string, error) {
	b := make([]byte, 32)
	if _, err := rand.Read(b); err != nil {
		return "", fmt.Errorf("generate token: %w", err)
	}
	token := hex.EncodeToString(b)

	expiresAt := time.Now().UTC().Add(ResetTokenMinutes * time.Minute)
	if err := s.repo.SavePasswordResetToken(ctx, userID, token, expiresAt); err != nil {
		return "", fmt.Errorf("save reset token: %w", err)
	}
	return token, nil
}

// BuildResetLink constructs the relative reset link path for password reset.
// The domain (https://www.dsppt.site) is embedded in the email/SMS templates.
func (s *VerificationService) BuildResetLink(token string) string {
	return fmt.Sprintf("reset-password?token=%s", token)
}

// ConsumePasswordResetToken validates and consumes a reset token, returning the user ID.
func (s *VerificationService) ConsumePasswordResetToken(ctx context.Context, token string) (int64, error) {
	return s.repo.ConsumePasswordResetToken(ctx, token)
}

// SendPasswordResetEmail sends a password reset link email to the user.
func (s *VerificationService) SendPasswordResetEmail(ctx context.Context, toEmail, userName, resetLink string) error {
	if s.emailClient == nil {
		return fmt.Errorf("邮件服务未配置")
	}
	return s.emailClient.SendPasswordResetLink(ctx, toEmail, userName, resetLink)
}

// SendPasswordResetSms sends a password reset link via SMS.
func (s *VerificationService) SendPasswordResetSms(phone, resetLink string) error {
	if s.smsClient == nil {
		return fmt.Errorf("短信服务未配置")
	}
	_, err := s.smsClient.SendPasswordResetLink(phone, resetLink)
	return err
}
