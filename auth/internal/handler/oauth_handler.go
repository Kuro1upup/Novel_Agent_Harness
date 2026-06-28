package handler

import (
	"net/http"

	"github.com/gin-gonic/gin"
)

// OAuthHandler holds placeholder handlers for OAuth endpoints.
type OAuthHandler struct{}

// NewOAuthHandler creates a new OAuthHandler.
func NewOAuthHandler() *OAuthHandler {
	return &OAuthHandler{}
}

// LoginRedirect handles GET /api/auth/oauth/:provider
// Returns 501 Not Implemented — OAuth integration is planned but not yet available.
func (h *OAuthHandler) LoginRedirect(c *gin.Context) {
	provider := c.Param("provider")
	c.JSON(http.StatusNotImplemented, gin.H{
		"success": false,
		"error":   "OAuth 登录尚未实现",
		"detail":  "Third-party login via " + provider + " is planned. Please use email registration for now.",
	})
}

// Callback handles GET /api/auth/oauth/:provider/callback
// Returns 501 Not Implemented — OAuth integration is planned but not yet available.
func (h *OAuthHandler) Callback(c *gin.Context) {
	provider := c.Param("provider")
	c.JSON(http.StatusNotImplemented, gin.H{
		"success": false,
		"error":   "OAuth 回调尚未实现",
		"detail":  "OAuth callback for " + provider + " is not yet implemented.",
	})
}
