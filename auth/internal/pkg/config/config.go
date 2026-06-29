package config

import (
	"os"
	"strconv"
)

// Config holds all configuration for the auth service.
type Config struct {
	ServerPort               string
	JWTSecret                string
	MySQLHost                string
	MySQLPort                string
	MySQLUser                string
	MySQLPassword            string
	MySQLDatabase            string
	MinIOEndpoint            string
	MinIOAccessKey           string
	MinIOSecretKey           string
	MinIOBucket              string
	BillingServiceURL        string
	InternalAPIKey           string
	PhoneRegistrationEnabled bool

	// Tencent Cloud SMS (REST API with AppID/AppKey).
	SMSAppID      string
	SMSAppKey     string
	SMSSignName   string
	SMSTemplateID string

	// Tencent Cloud SES (email — SDK requires SecretId/SecretKey).
	TencentSecretID  string
	TencentSecretKey string
	SESRegion        string

	// Frontend URL for building reset links etc.
	FrontendURL string
}

// Load reads configuration from environment variables with sensible defaults.
func Load() *Config {
	return &Config{
		ServerPort:        getEnv("SERVER_PORT", "8001"),
		JWTSecret:         getEnv("JWT_SECRET", "change-me-in-production"),
		MySQLHost:         getEnv("MYSQL_HOST", "localhost"),
		MySQLPort:         getEnv("MYSQL_PORT", "3306"),
		MySQLUser:         getEnv("MYSQL_USER", "novel_agent"),
		MySQLPassword:     getEnv("MYSQL_PASSWORD", "novel_agent_password"),
		MySQLDatabase:     getEnv("MYSQL_DATABASE", "novel_auth"),
		MinIOEndpoint:     getEnv("MINIO_ENDPOINT", "localhost:20000"),
		MinIOAccessKey:    getEnv("MINIO_ACCESS_KEY", "minioadmin"),
		MinIOSecretKey:    getEnv("MINIO_SECRET_KEY", "minioadmin"),
		MinIOBucket:       getEnv("MINIO_BUCKET", "novel-auth"),
		BillingServiceURL: getEnv("BILLING_SERVICE_URL", "http://billing:8002"),
		InternalAPIKey: getEnv(
			"BILLING_INTERNAL_API_KEY",
			getEnv("INTERNAL_API_KEY", "internal-key-change-me"),
		),
		PhoneRegistrationEnabled: getEnvBool("PHONE_REGISTRATION_ENABLED", false),

		// SMS (REST API with AppID/AppKey).
		SMSAppID:      getEnv("SMS_APP_ID", ""),
		SMSAppKey:     getEnv("SMS_APP_KEY", ""),
		SMSSignName:   getEnv("SMS_SIGN_NAME", ""),
		SMSTemplateID: getEnv("SMS_TEMPLATE_ID", ""),

		// Email (SES SDK).
		TencentSecretID:  getEnv("TENCENT_SECRET_ID", ""),
		TencentSecretKey: getEnv("TENCENT_SECRET_KEY", ""),
		SESRegion:        getEnv("SES_REGION", "ap-guangzhou"),

		// Frontend.
		FrontendURL: getEnv("FRONTEND_URL", "http://localhost:5173"),
	}
}

// DSN returns a MySQL Data Source Name string.
func (c *Config) DSN() string {
	return c.MySQLUser + ":" + c.MySQLPassword +
		"@tcp(" + c.MySQLHost + ":" + c.MySQLPort + ")/" +
		c.MySQLDatabase + "?charset=utf8mb4&parseTime=true&loc=UTC"
}

func getEnv(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

func getEnvBool(key string, fallback bool) bool {
	value := os.Getenv(key)
	if value == "" {
		return fallback
	}
	parsed, err := strconv.ParseBool(value)
	if err != nil {
		return fallback
	}
	return parsed
}
