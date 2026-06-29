package service

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"net/mail"
	"strings"
	"time"

	"second-brain/auth/internal/domain"
	"second-brain/auth/internal/pkg/crypto"
	"second-brain/auth/internal/repository"
)

// AuthService orchestrates auth business logic.
type AuthService struct {
	repo            *repository.UserRepo
	jwtSecret       string
	billingURL      string
	internalAPIKey  string
	verificationSvc *VerificationService
	httpClient      *http.Client
}

// NewAuthService creates a new AuthService.
func NewAuthService(repo *repository.UserRepo, jwtSecret, billingURL, internalAPIKey string, verificationSvc *VerificationService) *AuthService {
	return &AuthService{
		repo:            repo,
		jwtSecret:       jwtSecret,
		billingURL:      billingURL,
		internalAPIKey:  internalAPIKey,
		verificationSvc: verificationSvc,
		httpClient:      &http.Client{Timeout: 10 * time.Second},
	}
}

// ── Registration ──

// Register creates a new user after verifying the registration code.
// method is "email" or "phone" — the user registers via ONE method only.
// The chosen contact is marked verified, and becomes the default nickname.
func (s *AuthService) Register(email, phone, password, code, method string) (*domain.User, error) {
	if (method != "email" && method != "phone") || (method == "email" && email == "") || (method == "phone" && phone == "") {
		return nil, fmt.Errorf("请选择一种注册方式并填写对应信息")
	}
	if code == "" {
		return nil, fmt.Errorf("验证码不能为空")
	}

	ctx := context.Background()

	// Verify the code against the chosen target.
	target := email
	if method == "phone" {
		target = phone
	}
	if _, err := s.verificationSvc.VerifyCode(ctx, target, code, PurposeRegister); err != nil {
		return nil, err
	}

	// Create the user — the repo sets default nickname and verified flags.
	user, err := s.repo.Register(email, phone, password, method)
	if err != nil {
		return nil, err
	}

	// Best-effort: regular self-registration should not fail because Billing is temporarily down.
	go func(userID int64) {
		if err := s.initBalance(userID); err != nil {
			log.Printf("WARNING: init-balance failed for user=%d: %v", userID, err)
		}
	}(user.ID)

	return user, nil
}

// BootstrapLocalUser creates a verified local email account without a delivery code.
// Existing accounts are returned unchanged unless resetPassword is explicitly requested.
func (s *AuthService) BootstrapLocalUser(
	email, password, nickname string,
	resetPassword bool,
) (*domain.User, bool, error) {
	email = strings.ToLower(strings.TrimSpace(email))
	nickname = strings.TrimSpace(nickname)
	address, err := mail.ParseAddress(email)
	if err != nil || address.Address != email {
		return nil, false, fmt.Errorf("请输入有效邮箱地址")
	}
	if len(password) < 8 {
		return nil, false, fmt.Errorf("本地账号密码至少需要 8 位")
	}

	user, err := s.repo.FindByEmail(email)
	if err != nil {
		return nil, false, err
	}
	if user != nil {
		if resetPassword {
			if err := s.repo.UpdatePassword(user.ID, password); err != nil {
				return nil, false, err
			}
		}
		if !user.EmailVerified {
			if err := s.repo.MarkEmailVerified(user.ID); err != nil {
				return nil, false, err
			}
			user.EmailVerified = true
		}
		if err := s.initBalance(user.ID); err != nil {
			return nil, false, err
		}
		return user, false, nil
	}

	user, err = s.repo.Register(email, "", password, "email")
	if err != nil {
		// A concurrent bootstrap may have created the same account.
		user, findErr := s.repo.FindByEmail(email)
		if findErr != nil {
			return nil, false, findErr
		}
		if user == nil {
			return nil, false, err
		}
		if err := s.initBalance(user.ID); err != nil {
			return nil, false, err
		}
		return user, false, nil
	}
	if nickname != "" {
		profile, err := s.repo.UpdateProfile(user.ID, map[string]interface{}{"nickname": nickname})
		if err != nil {
			return nil, false, err
		}
		user.Nickname, _ = profile["nickname"].(string)
	}
	if err := s.initBalance(user.ID); err != nil {
		return nil, false, err
	}
	return user, true, nil
}

// SendRegisterCode sends a verification code for new user registration.
// Checks uniqueness of the provided contact before sending.
func (s *AuthService) SendRegisterCode(email, phone, method string) error {
	ctx := context.Background()

	if method == "email" {
		if email == "" {
			return fmt.Errorf("请填写邮箱地址")
		}
		exists, err := s.repo.CheckEmailExists(email)
		if err != nil {
			return err
		}
		if exists {
			return fmt.Errorf("该邮箱已被注册")
		}
		return s.verificationSvc.SendEmailCode(ctx, 0, email, email, PurposeRegister)
	}

	if method == "phone" {
		if phone == "" {
			return fmt.Errorf("请填写手机号")
		}
		exists, err := s.repo.CheckPhoneExists(phone)
		if err != nil {
			return err
		}
		if exists {
			return fmt.Errorf("该手机号已被注册")
		}
		return s.verificationSvc.SendSmsCode(ctx, 0, phone, PurposeRegister)
	}

	return fmt.Errorf("请选择验证方式：邮箱或手机号")
}

// ── Login ──

// Login verifies credentials (login can be email OR phone) and returns a JWT token + user info.
func (s *AuthService) Login(login, password string) (map[string]interface{}, error) {
	user, legacyToken, err := s.repo.Login(login, password)
	if err != nil {
		return nil, err
	}

	// Generate JWT for inter-service auth.
	jwtToken, err := crypto.GenerateToken(s.jwtSecret, user.ID, user.Email)
	if err != nil {
		jwtToken = legacyToken
	}

	// Check if user needs verification (has unverified contact method).
	needsVerification := false
	verificationMethods := []string{}
	if user.Email != "" && !user.EmailVerified {
		needsVerification = true
		verificationMethods = append(verificationMethods, "email")
	}
	if user.Phone != "" && !user.PhoneVerified {
		needsVerification = true
		verificationMethods = append(verificationMethods, "phone")
	}

	result := map[string]interface{}{
		"token": jwtToken,
		"user":  s.buildUserDict(user),
	}

	if needsVerification {
		result["needs_verification"] = true
		result["verification_methods"] = verificationMethods
	}

	return result, nil
}

// ── Post-login verification (verify existing unverified contact) ──

// SendLoginVerifyCode sends a verification code to the user's existing email or phone.
func (s *AuthService) SendLoginVerifyCode(userID int64, method string) error {
	user, err := s.repo.GetByID(userID)
	if err != nil {
		return err
	}

	ctx := context.Background()
	userName := user.Nickname
	if userName == "" {
		userName = user.Email
	}

	switch method {
	case "email":
		if user.Email == "" {
			return fmt.Errorf("未绑定邮箱")
		}
		return s.verificationSvc.SendEmailCode(ctx, userID, user.Email, userName, PurposeLoginVerify)
	case "phone":
		if user.Phone == "" {
			return fmt.Errorf("未绑定手机号")
		}
		return s.verificationSvc.SendSmsCode(ctx, userID, user.Phone, PurposeLoginVerify)
	default:
		return fmt.Errorf("不支持的验证方式: %s", method)
	}
}

// VerifyContact verifies the user's existing email or phone with a code.
func (s *AuthService) VerifyContact(userID int64, method, code string) error {
	user, err := s.repo.GetByID(userID)
	if err != nil {
		return err
	}

	ctx := context.Background()
	var target string

	switch method {
	case "email":
		target = user.Email
		if target == "" {
			return fmt.Errorf("未绑定邮箱")
		}
	case "phone":
		target = user.Phone
		if target == "" {
			return fmt.Errorf("未绑定手机号")
		}
	default:
		return fmt.Errorf("不支持的验证方式: %s", method)
	}

	if _, err := s.verificationSvc.VerifyCode(ctx, target, code, PurposeLoginVerify); err != nil {
		return err
	}

	if method == "email" {
		return s.repo.MarkEmailVerified(userID)
	}
	return s.repo.MarkPhoneVerified(userID)
}

// ── Add second contact method (post-registration) ──

// SendAddContactCode sends a verification code for adding a NEW email/phone to the existing user.
// Checks uniqueness of the new contact before sending.
func (s *AuthService) SendAddContactCode(userID int64, method, value string) error {
	if value == "" {
		return fmt.Errorf("请填写要添加的%v", map[string]string{"email": "邮箱", "phone": "手机号"}[method])
	}

	ctx := context.Background()

	switch method {
	case "email":
		exists, err := s.repo.CheckEmailExists(value)
		if err != nil {
			return err
		}
		if exists {
			return fmt.Errorf("该邮箱已被注册")
		}
		return s.verificationSvc.SendEmailCode(ctx, userID, value, value, PurposeLoginVerify)
	case "phone":
		exists, err := s.repo.CheckPhoneExists(value)
		if err != nil {
			return err
		}
		if exists {
			return fmt.Errorf("该手机号已被注册")
		}
		return s.verificationSvc.SendSmsCode(ctx, userID, value, PurposeLoginVerify)
	default:
		return fmt.Errorf("不支持的验证方式: %s", method)
	}
}

// AddContact verifies the code and adds the new email/phone to the existing user.
func (s *AuthService) AddContact(userID int64, method, value, code string) error {
	if value == "" || code == "" {
		return fmt.Errorf("参数不完整")
	}

	ctx := context.Background()

	// Verify the code.
	if _, err := s.verificationSvc.VerifyCode(ctx, value, code, PurposeLoginVerify); err != nil {
		return err
	}

	// Update the user record (also marks as verified).
	switch method {
	case "email":
		return s.repo.UpdateEmail(userID, value)
	case "phone":
		return s.repo.UpdatePhone(userID, value)
	default:
		return fmt.Errorf("不支持的验证方式: %s", method)
	}
}

// ── Password management ──

// ChangePassword verifies the current password and updates to the new one.
func (s *AuthService) ChangePassword(userID int64, currentPassword, newPassword string) error {
	user, err := s.repo.GetByIDFull(userID)
	if err != nil {
		return err
	}

	if !crypto.VerifyPassword(currentPassword, user.PasswordHash, user.Salt) {
		return fmt.Errorf("当前密码错误")
	}

	if err := s.repo.UpdatePassword(userID, newPassword); err != nil {
		return err
	}

	go func() {
		if err := s.repo.InvalidateUserTokens(userID); err != nil {
			log.Printf("WARNING: invalidate tokens for user=%d failed: %v", userID, err)
		}
	}()

	return nil
}

// ── Password reset ──

// SendPasswordResetLink sends a password reset link via email or SMS.
func (s *AuthService) SendPasswordResetLink(email, phone, method string) error {
	ctx := context.Background()

	var user *domain.User
	var err error
	var target string

	switch method {
	case "email":
		if email == "" {
			return fmt.Errorf("请填写邮箱地址")
		}
		target = email
		user, err = s.repo.GetByEmail(email)
	case "phone":
		if phone == "" {
			return fmt.Errorf("请填写手机号")
		}
		target = phone
		user, err = s.repo.GetByPhone(phone)
	default:
		return fmt.Errorf("不支持的重置方式")
	}

	if err != nil || user == nil {
		log.Printf("Password reset requested for unknown contact: method=%s target=%s", method, maskContact(target, method))
		return nil // Don't reveal whether the contact exists
	}

	token, err := s.verificationSvc.CreatePasswordResetToken(ctx, user.ID)
	if err != nil {
		return fmt.Errorf("create reset token: %w", err)
	}

	resetLink := s.verificationSvc.BuildResetLink(token)
	userName := user.Nickname
	if userName == "" {
		if user.Email != "" {
			userName = user.Email
		} else {
			userName = user.Phone
		}
	}

	switch method {
	case "email":
		if err := s.verificationSvc.SendPasswordResetEmail(ctx, email, userName, resetLink); err != nil {
			return fmt.Errorf("send reset email: %w", err)
		}
		log.Printf("Password reset link sent to %s for user=%d", maskEmailStatic(email), user.ID)
	case "phone":
		if err := s.verificationSvc.SendPasswordResetSms(phone, resetLink); err != nil {
			return fmt.Errorf("send reset sms: %w", err)
		}
		log.Printf("Password reset link sent via SMS to %s for user=%d", maskPhone(phone), user.ID)
	}

	return nil
}

// CompletePasswordReset consumes the token and sets the new password.
func (s *AuthService) CompletePasswordReset(token, newPassword string) error {
	ctx := context.Background()
	userID, err := s.verificationSvc.ConsumePasswordResetToken(ctx, token)
	if err != nil {
		return err
	}

	if err := s.repo.UpdatePassword(userID, newPassword); err != nil {
		return err
	}

	go func() {
		if err := s.repo.InvalidateUserTokens(userID); err != nil {
			log.Printf("WARNING: invalidate tokens for user=%d failed: %v", userID, err)
		}
	}()

	return nil
}

// ── Token / Profile ──

// GetCurrentUser validates a JWT or legacy token and returns the full user dict.
func (s *AuthService) GetCurrentUser(tokenString string) (map[string]interface{}, error) {
	claims, err := crypto.ValidateToken(s.jwtSecret, tokenString)
	if err == nil {
		profile, err := s.repo.GetProfile(claims.UserID)
		if err != nil {
			return nil, err
		}
		if profile == nil {
			return nil, fmt.Errorf("用户不存在")
		}
		return profile, nil
	}

	user, err := s.repo.GetByToken(tokenString)
	if err != nil {
		return nil, err
	}
	if user == nil {
		return nil, fmt.Errorf("认证已失效，请重新登录")
	}

	return s.buildUserDict(user), nil
}

// VerifyToken validates a Bearer token and returns the user (internal endpoint).
func (s *AuthService) VerifyToken(tokenString string) (map[string]interface{}, error) {
	return s.GetCurrentUser(tokenString)
}

// GetProfile returns the user's profile.
func (s *AuthService) GetProfile(userID int64) (map[string]interface{}, error) {
	return s.repo.GetProfile(userID)
}

// UpdateProfile updates allowed profile fields.
func (s *AuthService) UpdateProfile(userID int64, data map[string]interface{}) (map[string]interface{}, error) {
	return s.repo.UpdateProfile(userID, data)
}

// ── Helpers ──

func (s *AuthService) buildUserDict(user *domain.User) map[string]interface{} {
	return map[string]interface{}{
		"id":             user.ID,
		"email":          user.Email,
		"phone":          user.Phone,
		"nickname":       user.Nickname,
		"avatar_url":     user.AvatarURL,
		"age":            user.Age,
		"gender":         user.Gender,
		"bio":            user.Bio,
		"birthday":       user.Birthday,
		"email_verified": user.EmailVerified,
		"phone_verified": user.PhoneVerified,
		"created_at":     user.CreatedAt.Format(time.RFC3339),
	}
}

// UserResponse returns the public user representation shared by HTTP handlers.
func (s *AuthService) UserResponse(user *domain.User) map[string]interface{} {
	return s.buildUserDict(user)
}

func (s *AuthService) initBalance(userID int64) error {
	body := map[string]interface{}{
		"user_id": userID,
	}
	jsonBody, _ := json.Marshal(body)

	req, err := http.NewRequest("POST", s.billingURL+"/api/billing/internal/init-balance",
		bytes.NewReader(jsonBody))
	if err != nil {
		return fmt.Errorf("init-balance request build failed for user=%d: %w", userID, err)
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-Internal-Api-Key", s.internalAPIKey)

	resp, err := s.httpClient.Do(req)
	if err != nil {
		return fmt.Errorf("init-balance call failed for user=%d: %w", userID, err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("init-balance returned status=%d for user=%d", resp.StatusCode, userID)
	}
	log.Printf("Initial balance created for new user=%d", userID)
	return nil
}

func maskEmailStatic(email string) string {
	for i := 0; i < len(email); i++ {
		if email[i] == '@' && i > 1 {
			return email[:1] + "***" + email[i:]
		}
	}
	return email
}

func maskPhone(phone string) string {
	if len(phone) < 7 {
		return phone
	}
	return phone[:3] + "****" + phone[len(phone)-4:]
}

func maskContact(target, method string) string {
	if method == "email" {
		return maskEmailStatic(target)
	}
	return maskPhone(target)
}
