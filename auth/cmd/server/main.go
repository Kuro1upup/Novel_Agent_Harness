package main

import (
	"database/sql"
	"fmt"
	"log"
	"net/http"
	"os"
	"path/filepath"

	"github.com/gin-gonic/gin"
	_ "github.com/go-sql-driver/mysql"
	"github.com/joho/godotenv"

	"second-brain/auth/internal/handler"
	"second-brain/auth/internal/middleware"
	"second-brain/auth/internal/pkg/config"
	"second-brain/auth/internal/pkg/email"
	"second-brain/auth/internal/pkg/logger"
	"second-brain/auth/internal/pkg/sms"
	"second-brain/auth/internal/repository"
	"second-brain/auth/internal/service"
)

func init() {
	// Auto-load .env from the auth/ project root (two levels up from cmd/server).
	envCandidates := []string{
		filepath.Join(".", ".env"),
		filepath.Join("..", ".env"),
		filepath.Join("..", "..", ".env"),
	}

	loaded := false
	for _, p := range envCandidates {
		if _, err := os.Stat(p); err == nil {
			if err := godotenv.Load(p); err == nil {
				println("Loaded env from", p)
				loaded = true
				break
			}
		}
	}

	if !loaded {
		cwd, _ := os.Getwd()
		for _, p := range envCandidates {
			abs := filepath.Join(cwd, p)
			if _, err := os.Stat(abs); err == nil {
				if err := godotenv.Load(abs); err == nil {
					println("Loaded env from", abs)
					loaded = true
					break
				}
			}
		}
	}

	if !loaded {
		println("No .env file found, using system environment variables")
	}
}

func main() {
	// ── Logger (stdout + daily rotating file) ──
	appLogger, err := logger.New(logger.Config{
		LogDir:  os.Getenv("LOG_DIR"),
		LogName: "auth",
	})
	if err != nil {
		log.Fatalf("Failed to initialize logger: %v", err)
	}
	defer appLogger.Close()
	appLogger.StartRotation()

	log.SetOutput(appLogger.Writer())
	log.SetFlags(log.LstdFlags)

	cfg := config.Load()

	// ── MySQL ──
	db, err := sql.Open("mysql", cfg.DSN())
	if err != nil {
		log.Fatalf("Failed to open MySQL: %v", err)
	}
	db.SetMaxOpenConns(25)
	db.SetMaxIdleConns(10)
	defer db.Close()

	if err := db.Ping(); err != nil {
		log.Fatalf("Failed to ping MySQL: %v", err)
	}
	log.Println("MySQL connected")

	// ── Schema ──
	if err := repository.EnsureSchema(db); err != nil {
		log.Fatalf("Failed to ensure schema: %v", err)
	}

	// ── MinIO bucket ──
	if err := repository.EnsureBuckets(cfg); err != nil {
		log.Printf("WARNING: Failed to ensure MinIO bucket: %v", err)
	}

	// ── Tencent Cloud SMS Client ──
	var smsClient *sms.Client
	if cfg.SMSAppID != "" && cfg.SMSAppKey != "" {
		smsClient = sms.NewClient(sms.Config{
			AppID:      cfg.SMSAppID,
			AppKey:     cfg.SMSAppKey,
			SignName:   cfg.SMSSignName,
			TemplateID: cfg.SMSTemplateID,
		})
		log.Println("SMS client initialized")
	} else {
		// log.Println("WARNING: SMS not configured (missing SMS_APP_ID or SMS_APP_KEY)")
		log.Println("Skip to initialize sms client")
	}

	// ── Tencent Cloud Email Client ──
	var emailClient *email.Client
	if cfg.TencentSecretID != "" && cfg.TencentSecretKey != "" {
		emailClient, err = email.NewClient(email.Config{
			SecretID:  cfg.TencentSecretID,
			SecretKey: cfg.TencentSecretKey,
			Region:    cfg.SESRegion,
		})
		if err != nil {
			log.Printf("WARNING: Email client init failed: %v", err)
			emailClient = nil
		} else {
			log.Println("Email client initialized")
		}
	} else {
		log.Println("WARNING: Email not configured (missing TENCENT_SECRET_ID or TENCENT_SECRET_KEY)")
	}

	// ── Wiring ──
	userRepo := repository.NewUserRepo(db)
	verificationSvc := service.NewVerificationService(userRepo, smsClient, emailClient, cfg.FrontendURL)
	authSvc := service.NewAuthService(userRepo, cfg.JWTSecret, cfg.BillingServiceURL, cfg.BillingInternalAPIKey, verificationSvc)
	authHandler := handler.NewAuthHandler(authSvc, cfg)
	oauthHandler := handler.NewOAuthHandler()

	// ── Gin ──
	gin.DefaultWriter = appLogger.Writer()
	gin.DefaultErrorWriter = appLogger.Writer()
	r := gin.Default()

	// Public routes (no auth required).
	auth := r.Group("/api/auth")
	{
		auth.GET("/capabilities", authHandler.Capabilities)
		auth.POST("/send-code", authHandler.SendRegisterCode)
		auth.POST("/register", authHandler.Register)
		auth.POST("/login", authHandler.Login)
		auth.POST("/forgot-password", authHandler.ForgotPassword)
		auth.POST("/reset-password", authHandler.ResetPassword)

		// Delivery status callbacks.
		auth.POST("/callback/sms", authHandler.SmsCallback)
		auth.POST("/callback/email", authHandler.EmailCallback)

		auth.GET("/avatar/:user_id", authHandler.GetAvatar)

		oauth := auth.Group("/oauth")
		{
			oauth.GET("/:provider", oauthHandler.LoginRedirect)
			oauth.GET("/:provider/callback", oauthHandler.Callback)
		}
	}

	// Authenticated routes (JWT required).
	authProtected := r.Group("/api/auth")
	authProtected.Use(middleware.AuthMiddleware(userRepo, cfg.JWTSecret))
	{
		authProtected.GET("/me", authHandler.Me)
		authProtected.GET("/profile", authHandler.GetProfile)
		authProtected.PUT("/profile", authHandler.UpdateProfile)
		authProtected.POST("/avatar", authHandler.UploadAvatar)

		// Verification (post-login).
		authProtected.POST("/send-verify-code", authHandler.SendLoginVerifyCode)
		authProtected.POST("/verify-contact", authHandler.VerifyContact)

		// Add second contact method.
		authProtected.POST("/send-add-contact-code", authHandler.SendAddContactCode)
		authProtected.POST("/add-contact", authHandler.AddContact)

		// Password management.
		authProtected.PUT("/password", authHandler.ChangePassword)
	}

	// Internal routes.
	internal := r.Group("/api/auth")
	{
		internal.GET("/verify", authHandler.Verify)
	}

	localAdmin := r.Group("/api/auth/internal")
	localAdmin.Use(middleware.InternalAuthMiddleware(cfg.AuthInternalAPIKey))
	{
		localAdmin.POST("/bootstrap", authHandler.BootstrapLocalUser)
	}

	// Health.
	r.GET("/api/health", func(c *gin.Context) {
		c.JSON(http.StatusOK, gin.H{"status": "healthy", "service": "auth"})
	})

	addr := fmt.Sprintf(":%s", cfg.ServerPort)
	log.Printf("Auth service starting on %s", addr)
	if err := r.Run(addr); err != nil {
		log.Fatalf("Server failed: %v", err)
	}
}
