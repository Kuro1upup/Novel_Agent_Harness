package handler

import (
	"bytes"
	"io"
	"log"
	"net/http"
	"strconv"
	"strings"

	"github.com/gin-gonic/gin"
	"github.com/minio/minio-go/v7"
	"github.com/minio/minio-go/v7/pkg/credentials"

	"second-brain/auth/internal/middleware"
	"second-brain/auth/internal/pkg/config"
	"second-brain/auth/internal/service"
)

// AuthHandler holds HTTP handlers for auth endpoints.
type AuthHandler struct {
	svc *service.AuthService
	cfg *config.Config
}

// NewAuthHandler creates a new AuthHandler.
func NewAuthHandler(svc *service.AuthService, cfg *config.Config) *AuthHandler {
	return &AuthHandler{svc: svc, cfg: cfg}
}

// ── Request/Response DTOs ──

type SendCodeRequest struct {
	Email  string `json:"email"`
	Phone  string `json:"phone"`
	Method string `json:"method" binding:"required"` // "email" or "phone"
}

type RegisterRequest struct {
	Email    string `json:"email"`
	Phone    string `json:"phone"`
	Password string `json:"password" binding:"required,min=6"`
	Code     string `json:"code" binding:"required,len=6"`
	Method   string `json:"method" binding:"required"` // "email" or "phone"
}

type LoginRequest struct {
	Login    string `json:"login" binding:"required"` // email or phone
	Password string `json:"password" binding:"required"`
}

type BootstrapLocalUserRequest struct {
	Email         string `json:"email" binding:"required"`
	Password      string `json:"password" binding:"required,min=8"`
	Nickname      string `json:"nickname"`
	ResetPassword bool   `json:"reset_password"`
}

type SendLoginVerifyCodeRequest struct {
	Method string `json:"method" binding:"required"`
}

type VerifyContactRequest struct {
	Method string `json:"method" binding:"required"`
	Code   string `json:"code" binding:"required,len=6"`
}

type AddContactRequest struct {
	Method string `json:"method" binding:"required"` // "email" or "phone"
	Value  string `json:"value" binding:"required"`  // the email/phone to add
	Code   string `json:"code" binding:"required,len=6"`
}

type ChangePasswordRequest struct {
	CurrentPassword string `json:"current_password" binding:"required"`
	NewPassword     string `json:"new_password" binding:"required,min=6"`
}

type ForgotPasswordRequest struct {
	Email  string `json:"email"`
	Phone  string `json:"phone"`
	Method string `json:"method" binding:"required"` // "email" or "phone"
}

type ResetPasswordRequest struct {
	Token       string `json:"token" binding:"required"`
	NewPassword string `json:"new_password" binding:"required,min=6"`
}

type ProfileUpdateRequest struct {
	Nickname  string `json:"nickname"`
	AvatarURL string `json:"avatar_url"`
	Age       int    `json:"age"`
	Gender    string `json:"gender"`
	Bio       string `json:"bio"`
	Birthday  string `json:"birthday"`
}

// ── Handlers ──

// SendRegisterCode handles POST /api/auth/send-code.
func (h *AuthHandler) SendRegisterCode(c *gin.Context) {
	var req SendCodeRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"detail": "参数错误：method 为必填项（email 或 phone）"})
		return
	}
	if req.Method == "phone" && !h.cfg.PhoneRegistrationEnabled {
		c.JSON(http.StatusForbidden, gin.H{"detail": "当前部署已关闭手机号注册"})
		return
	}
	if err := h.svc.SendRegisterCode(req.Email, req.Phone, req.Method); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"detail": err.Error()})
		return
	}
	c.JSON(http.StatusOK, gin.H{"success": true, "message": "验证码已发送"})
}

// Register handles POST /api/auth/register.
// method must be "email" or "phone" — registers via ONE contact method.
func (h *AuthHandler) Register(c *gin.Context) {
	var req RegisterRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"detail": "参数错误：密码至少6位，验证码6位，method为必填项"})
		return
	}
	if req.Method == "phone" && !h.cfg.PhoneRegistrationEnabled {
		c.JSON(http.StatusForbidden, gin.H{"detail": "当前部署已关闭手机号注册"})
		return
	}

	user, err := h.svc.Register(req.Email, req.Phone, req.Password, req.Code, req.Method)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"detail": err.Error()})
		return
	}

	c.JSON(http.StatusOK, gin.H{"success": true, "user": map[string]interface{}{
		"id":             user.ID,
		"email":          user.Email,
		"phone":          user.Phone,
		"nickname":       user.Nickname,
		"email_verified": user.EmailVerified,
		"phone_verified": user.PhoneVerified,
		"created_at":     user.CreatedAt.Format("2006-01-02T15:04:05Z07:00"),
	}})
}

// Capabilities exposes deployment-level authentication options to clients.
func (h *AuthHandler) Capabilities(c *gin.Context) {
	c.JSON(http.StatusOK, gin.H{
		"phone_registration_enabled": h.cfg.PhoneRegistrationEnabled,
	})
}

// BootstrapLocalUser creates the explicitly configured local-only account.
func (h *AuthHandler) BootstrapLocalUser(c *gin.Context) {
	if !h.cfg.LocalBootstrapEnabled {
		c.JSON(http.StatusForbidden, gin.H{"detail": "当前部署未启用本地账号初始化"})
		return
	}
	var req BootstrapLocalUserRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"detail": "邮箱必填，密码至少 8 位"})
		return
	}
	user, created, err := h.svc.BootstrapLocalUser(
		req.Email,
		req.Password,
		req.Nickname,
		req.ResetPassword,
	)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"detail": err.Error()})
		return
	}
	c.JSON(http.StatusOK, gin.H{
		"success": true,
		"created": created,
		"user":    h.svc.UserResponse(user),
	})
}

// Login handles POST /api/auth/login. Accepts email OR phone as login identifier.
func (h *AuthHandler) Login(c *gin.Context) {
	var req LoginRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"detail": "登录名（邮箱或手机号）和密码不能为空"})
		return
	}

	result, err := h.svc.Login(req.Login, req.Password)
	if err != nil {
		c.JSON(http.StatusUnauthorized, gin.H{"detail": "邮箱/手机号或密码错误"})
		return
	}

	resp := gin.H{
		"success": true,
		"token":   result["token"],
		"user":    result["user"],
	}
	if needsVerify, ok := result["needs_verification"]; ok {
		resp["needs_verification"] = needsVerify
	}
	if methods, ok := result["verification_methods"]; ok {
		resp["verification_methods"] = methods
	}

	c.JSON(http.StatusOK, resp)
}

// SendLoginVerifyCode handles POST /api/auth/send-verify-code (authenticated).
func (h *AuthHandler) SendLoginVerifyCode(c *gin.Context) {
	userID := middleware.GetUserID(c)
	var req SendLoginVerifyCodeRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"detail": "参数错误"})
		return
	}
	if err := h.svc.SendLoginVerifyCode(userID, req.Method); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"detail": err.Error()})
		return
	}
	c.JSON(http.StatusOK, gin.H{"success": true, "message": "验证码已发送"})
}

// VerifyContact handles POST /api/auth/verify-contact (authenticated).
func (h *AuthHandler) VerifyContact(c *gin.Context) {
	userID := middleware.GetUserID(c)
	var req VerifyContactRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"detail": "参数错误"})
		return
	}
	if err := h.svc.VerifyContact(userID, req.Method, req.Code); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"detail": err.Error()})
		return
	}
	c.JSON(http.StatusOK, gin.H{"success": true, "message": "验证成功"})
}

// SendAddContactCode handles POST /api/auth/send-add-contact-code (authenticated).
// Sends code for adding a new email/phone to an existing verified user.
func (h *AuthHandler) SendAddContactCode(c *gin.Context) {
	userID := middleware.GetUserID(c)
	var req struct {
		Method string `json:"method" binding:"required"`
		Value  string `json:"value" binding:"required"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"detail": "参数错误"})
		return
	}
	if err := h.svc.SendAddContactCode(userID, req.Method, req.Value); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"detail": err.Error()})
		return
	}
	c.JSON(http.StatusOK, gin.H{"success": true, "message": "验证码已发送"})
}

// AddContact handles POST /api/auth/add-contact (authenticated).
// Verifies the code and adds the new email/phone to the user.
func (h *AuthHandler) AddContact(c *gin.Context) {
	userID := middleware.GetUserID(c)
	var req AddContactRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"detail": "参数错误"})
		return
	}
	if err := h.svc.AddContact(userID, req.Method, req.Value, req.Code); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"detail": err.Error()})
		return
	}
	c.JSON(http.StatusOK, gin.H{"success": true, "message": "添加成功"})
}

// ChangePassword handles PUT /api/auth/password (authenticated).
func (h *AuthHandler) ChangePassword(c *gin.Context) {
	userID := middleware.GetUserID(c)
	var req ChangePasswordRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"detail": "参数错误"})
		return
	}
	if err := h.svc.ChangePassword(userID, req.CurrentPassword, req.NewPassword); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"detail": err.Error()})
		return
	}
	c.JSON(http.StatusOK, gin.H{"success": true, "message": "密码修改成功"})
}

// ForgotPassword handles POST /api/auth/forgot-password (public).
func (h *AuthHandler) ForgotPassword(c *gin.Context) {
	var req ForgotPasswordRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"detail": "参数错误：method 为必填项（email 或 phone）"})
		return
	}
	if err := h.svc.SendPasswordResetLink(req.Email, req.Phone, req.Method); err != nil {
		log.Printf("ForgotPassword error: %v", err)
	}
	msg := "如果该邮箱已注册，重置链接已发送"
	if req.Method == "phone" {
		msg = "如果该手机号已注册，重置链接已发送"
	}
	c.JSON(http.StatusOK, gin.H{"success": true, "message": msg})
}

// ResetPassword handles POST /api/auth/reset-password (public).
func (h *AuthHandler) ResetPassword(c *gin.Context) {
	var req ResetPasswordRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"detail": "参数错误"})
		return
	}
	if err := h.svc.CompletePasswordReset(req.Token, req.NewPassword); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"detail": err.Error()})
		return
	}
	c.JSON(http.StatusOK, gin.H{"success": true, "message": "密码重置成功"})
}

// ── Delivery status callbacks ──

// SmsCallback handles POST /api/auth/callback/sms.
func (h *AuthHandler) SmsCallback(c *gin.Context) {
	var reports []map[string]interface{}
	if err := c.ShouldBindJSON(&reports); err != nil {
		body, _ := io.ReadAll(c.Request.Body)
		log.Printf("SMS callback: bad JSON: %v, body=%s", err, string(body))
		c.JSON(http.StatusOK, gin.H{"result": 0, "errmsg": "OK"})
		return
	}
	for _, report := range reports {
		status, _ := report["report_status"].(string)
		sid, _ := report["sid"].(string)
		desc, _ := report["description"].(string)
		log.Printf("SMS delivery: sid=%s status=%s desc=%s", sid, status, desc)
	}
	c.JSON(http.StatusOK, gin.H{"result": 0, "errmsg": "OK"})
}

// EmailCallback handles POST /api/auth/callback/email.
func (h *AuthHandler) EmailCallback(c *gin.Context) {
	var data map[string]interface{}
	if err := c.ShouldBindJSON(&data); err != nil {
		body, _ := io.ReadAll(c.Request.Body)
		log.Printf("Email callback: bad JSON: %v, body=%s", err, string(body))
		c.JSON(http.StatusOK, gin.H{"result": 0, "errmsg": "OK"})
		return
	}
	log.Printf("Email delivery callback: %+v", data)
	c.JSON(http.StatusOK, gin.H{"result": 0, "errmsg": "OK"})
}

// ── Existing handlers (unchanged logic) ──

// Me handles GET /api/auth/me.
func (h *AuthHandler) Me(c *gin.Context) {
	userID := middleware.GetUserID(c)
	profile, err := h.svc.GetProfile(userID)
	if err != nil || profile == nil {
		c.JSON(http.StatusNotFound, gin.H{"detail": "用户不存在"})
		return
	}
	c.JSON(http.StatusOK, gin.H{"success": true, "user": profile})
}

// GetProfile handles GET /api/auth/profile.
func (h *AuthHandler) GetProfile(c *gin.Context) {
	userID := middleware.GetUserID(c)
	profile, err := h.svc.GetProfile(userID)
	if err != nil || profile == nil {
		c.JSON(http.StatusNotFound, gin.H{"detail": "用户不存在"})
		return
	}
	c.JSON(http.StatusOK, gin.H{"success": true, "profile": profile})
}

// UpdateProfile handles PUT /api/auth/profile.
func (h *AuthHandler) UpdateProfile(c *gin.Context) {
	userID := middleware.GetUserID(c)
	var req ProfileUpdateRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"detail": err.Error()})
		return
	}

	data := map[string]interface{}{}
	if req.Nickname != "" {
		data["nickname"] = req.Nickname
	}
	if req.AvatarURL != "" {
		data["avatar_url"] = req.AvatarURL
	}
	if req.Age > 0 {
		data["age"] = req.Age
	}
	if req.Gender != "" {
		data["gender"] = req.Gender
	}
	if req.Bio != "" {
		// Validate bio length: max 36 Chinese characters (runes)
		bioRunes := []rune(req.Bio)
		if len(bioRunes) > 36 {
			c.JSON(http.StatusBadRequest, gin.H{"detail": "个人简介最长不超过36个汉字"})
			return
		}
		data["bio"] = req.Bio
	}
	if req.Birthday != "" {
		data["birthday"] = req.Birthday
	}

	profile, err := h.svc.UpdateProfile(userID, data)
	if err != nil {
		log.Printf("UpdateProfile error: %v", err)
		c.JSON(http.StatusInternalServerError, gin.H{"detail": "更新个人信息失败"})
		return
	}
	c.JSON(http.StatusOK, gin.H{"success": true, "profile": profile})
}

// UploadAvatar handles POST /api/auth/avatar.
func (h *AuthHandler) UploadAvatar(c *gin.Context) {
	userID := middleware.GetUserID(c)

	file, header, err := c.Request.FormFile("file")
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"detail": "请选择文件"})
		return
	}
	defer file.Close()

	allowedTypes := map[string]string{
		"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "image/gif": "gif",
	}
	contentType := header.Header.Get("Content-Type")
	ext, ok := allowedTypes[contentType]
	if !ok {
		c.JSON(http.StatusBadRequest, gin.H{"detail": "仅支持 PNG / JPEG / WebP / GIF 格式"})
		return
	}

	if header.Size > 2*1024*1024 {
		c.JSON(http.StatusBadRequest, gin.H{"detail": "头像大小不能超过 2 MB"})
		return
	}

	fileBytes, err := io.ReadAll(file)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"detail": "读取文件失败"})
		return
	}

	minioClient, err := minio.New(h.cfg.MinIOEndpoint, &minio.Options{
		Creds:  credentials.NewStaticV4(h.cfg.MinIOAccessKey, h.cfg.MinIOSecretKey, ""),
		Secure: false,
	})
	if err != nil {
		log.Printf("MinIO client error: %v", err)
		c.JSON(http.StatusInternalServerError, gin.H{"detail": "存储服务不可用"})
		return
	}

	objectKey := "avatars/" + strconv.FormatInt(userID, 10) + "/avatar." + ext
	_, err = minioClient.PutObject(c.Request.Context(), h.cfg.MinIOBucket, objectKey,
		bytes.NewReader(fileBytes), int64(len(fileBytes)),
		minio.PutObjectOptions{ContentType: contentType})
	if err != nil {
		log.Printf("MinIO upload error: %v", err)
		c.JSON(http.StatusInternalServerError, gin.H{"detail": "头像上传失败"})
		return
	}

	avatarURL := "/api/auth/avatar/" + strconv.FormatInt(userID, 10)
	h.svc.UpdateProfile(userID, map[string]interface{}{"avatar_url": avatarURL})

	c.JSON(http.StatusOK, gin.H{"success": true, "avatar_url": avatarURL})
}

// GetAvatar handles GET /api/auth/avatar/:user_id.
func (h *AuthHandler) GetAvatar(c *gin.Context) {
	userID := c.Param("user_id")

	minioClient, err := minio.New(h.cfg.MinIOEndpoint, &minio.Options{
		Creds:  credentials.NewStaticV4(h.cfg.MinIOAccessKey, h.cfg.MinIOSecretKey, ""),
		Secure: false,
	})
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"detail": "存储服务不可用"})
		return
	}

	for _, ext := range []string{"png", "jpg", "webp", "gif"} {
		objectKey := "avatars/" + userID + "/avatar." + ext
		obj, err := minioClient.GetObject(c.Request.Context(), h.cfg.MinIOBucket, objectKey, minio.GetObjectOptions{})
		if err != nil {
			continue
		}
		data, err := io.ReadAll(obj)
		obj.Close()
		if err != nil {
			continue
		}
		contentType := "image/" + ext
		if ext == "jpg" {
			contentType = "image/jpeg"
		}
		c.Data(http.StatusOK, contentType, data)
		return
	}

	c.JSON(http.StatusNotFound, gin.H{"detail": "头像不存在"})
}

// Verify handles GET /api/auth/verify (internal endpoint for backend).
func (h *AuthHandler) Verify(c *gin.Context) {
	authHeader := c.GetHeader("Authorization")
	if authHeader == "" {
		c.JSON(http.StatusUnauthorized, gin.H{"detail": "未提供认证信息"})
		return
	}

	tokenString := strings.TrimPrefix(authHeader, "Bearer ")
	tokenString = strings.TrimSpace(tokenString)

	user, err := h.svc.VerifyToken(tokenString)
	if err != nil || user == nil {
		c.JSON(http.StatusUnauthorized, gin.H{"detail": "认证已失效，请重新登录"})
		return
	}

	c.JSON(http.StatusOK, gin.H{"success": true, "user": user})
}
