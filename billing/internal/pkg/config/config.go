package config

import "os"

// Config holds all configuration for the billing service.
type Config struct {
	ServerPort     string
	JWTSecret      string
	MySQLHost      string
	MySQLPort      string
	MySQLUser      string
	MySQLPassword  string
	MySQLDatabase  string
	RedisHost      string
	RedisPort      string
	RedisPassword  string
	InternalAPIKey string
	AdminPassword  string
}

// Load reads configuration from environment variables with sensible defaults.
func Load() *Config {
	return &Config{
		ServerPort:     getEnv("SERVER_PORT", "8002"),
		JWTSecret:      getEnv("JWT_SECRET", "change-me-in-production"),
		MySQLHost:      getEnv("MYSQL_HOST", "localhost"),
		MySQLPort:      getEnv("MYSQL_PORT", "3306"),
		MySQLUser:      getEnv("MYSQL_USER", "novel_agent"),
		MySQLPassword:  getEnv("MYSQL_PASSWORD", "novel_agent_password"),
		MySQLDatabase:  getEnv("MYSQL_DATABASE", "novel_billing"),
		RedisHost:      getEnv("REDIS_HOST", "localhost"),
		RedisPort:      getEnv("REDIS_PORT", "20005"),
		RedisPassword:  getEnv("REDIS_PASSWORD", "myredissecret"),
		InternalAPIKey: getEnv(
			"BILLING_INTERNAL_API_KEY",
			getEnv("INTERNAL_API_KEY", "internal-key-change-me"),
		),
		AdminPassword: getEnv("ADMIN_PASSWORD", "change-me-in-production"),
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
