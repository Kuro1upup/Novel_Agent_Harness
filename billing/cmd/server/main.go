package main

import (
	"context"
	"database/sql"
	"fmt"
	"log"
	"net/http"
	"os"
	"os/signal"
	"path/filepath"
	"syscall"

	"github.com/gin-gonic/gin"
	_ "github.com/go-sql-driver/mysql"
	"github.com/joho/godotenv"
	"github.com/redis/go-redis/v9"

	"second-brain/billing/internal/handler"
	"second-brain/billing/internal/middleware"
	"second-brain/billing/internal/pkg/config"
	"second-brain/billing/internal/pkg/logger"
	"second-brain/billing/internal/repository"
	"second-brain/billing/internal/service"
)

func init() {
	// Auto-load .env from the billing/ project root (two levels up from cmd/server).
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
		LogName: "billing",
	})
	if err != nil {
		log.Fatalf("Failed to initialize logger: %v", err)
	}
	defer appLogger.Close()
	appLogger.StartRotation()

	// Redirect all standard log calls to the dual-output logger.
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

	// ── Redis ──
	redisAddr := fmt.Sprintf("%s:%s", cfg.RedisHost, cfg.RedisPort)
	redisClient := redis.NewClient(&redis.Options{
		Addr:     redisAddr,
		Password: cfg.RedisPassword,
		DB:       0,
	})
	defer redisClient.Close()

	if err := redisClient.Ping(context.Background()).Err(); err != nil {
		log.Printf("WARNING: Redis not available at %s: %v — usage events will be missed", redisAddr, err)
	} else {
		log.Println("Redis connected")
	}

	// ── Wiring ──
	billingRepo := repository.NewBillingRepo(db)
	billingSvc := service.NewBillingService(billingRepo)
	billingHandler := handler.NewBillingHandler(billingSvc, cfg)

	// ── Redis consumer ──
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	usageConsumerStarted := false
	if redisClient.Ping(context.Background()).Err() == nil {
		consumer := service.NewUsageConsumer(redisClient, billingSvc)
		consumer.Start(ctx)
		usageConsumerStarted = true
	}

	// ── Gin ──
	// Route Gin's own access logs and errors to the dual-output logger.
	gin.DefaultWriter = appLogger.Writer()
	gin.DefaultErrorWriter = appLogger.Writer()
	r := gin.Default()

	// Public endpoints (JWT-protected).
	billing := r.Group("/api/billing")
	billing.Use(middleware.AuthMiddleware(cfg.JWTSecret))
	{
		billing.GET("/usage", billingHandler.GetUsage)
		billing.GET("/bills", billingHandler.GetBills)
		billing.GET("/balance", billingHandler.GetBalance)
		billing.GET("/recharges", billingHandler.ListRecharges)
	}

	// Admin-only (no JWT, uses admin password).
	r.POST("/api/billing/recharges", billingHandler.Recharge)

	// Internal endpoints (protected by X-Internal-Api-Key).
	internal := r.Group("/api/billing/internal")
	internal.Use(middleware.InternalAuthMiddleware(cfg.InternalAPIKey))
	{
		internal.POST("/usage", billingHandler.RecordUsageInternal)
		internal.GET("/balance-check", billingHandler.CheckBalanceInternal)
		internal.POST("/init-balance", billingHandler.InitBalanceInternal)
	}

	// Health.
	r.GET("/api/health", func(c *gin.Context) {
		redisHealthy := redisClient.Ping(c.Request.Context()).Err() == nil
		status := "healthy"
		if !redisHealthy || !usageConsumerStarted {
			status = "degraded"
		}
		c.JSON(http.StatusOK, gin.H{
			"status":                 status,
			"service":                "billing",
			"redis_connected":        redisHealthy,
			"usage_consumer_started": usageConsumerStarted,
		})
	})

	// ── Graceful shutdown ──
	sigCh := make(chan os.Signal, 1)
	signal.Notify(sigCh, syscall.SIGINT, syscall.SIGTERM)

	go func() {
		<-sigCh
		log.Println("Shutting down billing service...")
		cancel()
		appLogger.Close()
		os.Exit(0)
	}()

	addr := fmt.Sprintf(":%s", cfg.ServerPort)
	log.Printf("Billing service starting on %s", addr)
	if err := r.Run(addr); err != nil {
		log.Fatalf("Server failed: %v", err)
	}
}
