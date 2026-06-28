package middleware

import (
	"net/http"
	"strings"

	"second-brain/auth/internal/pkg/crypto"
	"second-brain/auth/internal/repository"

	"github.com/gin-gonic/gin"
)

// AuthMiddleware returns a Gin middleware that validates JWT Bearer tokens.
// On success, it sets "user_id" and "user_email" in the Gin context.
func AuthMiddleware(repo *repository.UserRepo, jwtSecret string) gin.HandlerFunc {
	return func(c *gin.Context) {
		authHeader := c.GetHeader("Authorization")
		if authHeader == "" {
			c.JSON(http.StatusUnauthorized, gin.H{"detail": "未提供认证信息"})
			c.Abort()
			return
		}

		parts := strings.SplitN(authHeader, " ", 2)
		if len(parts) != 2 || !strings.EqualFold(parts[0], "bearer") {
			c.JSON(http.StatusUnauthorized, gin.H{"detail": "认证格式错误"})
			c.Abort()
			return
		}

		tokenString := strings.TrimSpace(parts[1])
		if tokenString == "" {
			c.JSON(http.StatusUnauthorized, gin.H{"detail": "认证格式错误"})
			c.Abort()
			return
		}

		// Try JWT first.
		claims, err := crypto.ValidateToken(jwtSecret, tokenString)
		if err == nil {
			c.Set("user_id", claims.UserID)
			c.Set("user_email", claims.Email)
			c.Next()
			return
		}

		// Fallback: try legacy token.
		user, err := repo.GetByToken(tokenString)
		if err != nil || user == nil {
			c.JSON(http.StatusUnauthorized, gin.H{"detail": "认证已失效，请重新登录"})
			c.Abort()
			return
		}

		c.Set("user_id", user.ID)
		c.Set("user_email", user.Email)
		c.Next()
	}
}

// GetUserID extracts the authenticated user ID from the Gin context.
func GetUserID(c *gin.Context) int64 {
	id, _ := c.Get("user_id")
	if id == nil {
		return 0
	}
	return id.(int64)
}

// GetUserEmail extracts the authenticated user email from the Gin context.
func GetUserEmail(c *gin.Context) string {
	email, _ := c.Get("user_email")
	if email == nil {
		return ""
	}
	return email.(string)
}
