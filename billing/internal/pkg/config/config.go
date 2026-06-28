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
		MySQLUser:      getEnv("MYSQL_USER", "sql_copilot"),
		MySQLPassword:  getEnv("MYSQL_PASSWORD", "sql_copilot_password"),
		MySQLDatabase:  getEnv("MYSQL_DATABASE", "sql_copilot"),
		RedisHost:      getEnv("REDIS_HOST", "localhost"),
		RedisPort:      getEnv("REDIS_PORT", "6379"),
		RedisPassword:  getEnv("REDIS_PASSWORD", "myredissecret"),
		InternalAPIKey: getEnv("INTERNAL_API_KEY", "internal-key-change-me"),
		AdminPassword:  getEnv("ADMIN_PASSWORD", "7ujm<KI*"),
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
