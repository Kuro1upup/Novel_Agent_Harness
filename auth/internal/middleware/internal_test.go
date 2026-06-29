package middleware

import (
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/gin-gonic/gin"
)

func TestInternalAuthMiddleware(t *testing.T) {
	gin.SetMode(gin.TestMode)
	router := gin.New()
	router.Use(InternalAuthMiddleware("shared-secret"))
	router.POST("/internal", func(c *gin.Context) {
		c.Status(http.StatusNoContent)
	})

	for _, item := range []struct {
		name   string
		key    string
		status int
	}{
		{name: "missing", status: http.StatusForbidden},
		{name: "incorrect", key: "wrong", status: http.StatusForbidden},
		{name: "accepted", key: "shared-secret", status: http.StatusNoContent},
	} {
		t.Run(item.name, func(t *testing.T) {
			request := httptest.NewRequest(http.MethodPost, "/internal", nil)
			if item.key != "" {
				request.Header.Set("X-Internal-Api-Key", item.key)
			}
			response := httptest.NewRecorder()
			router.ServeHTTP(response, request)
			if response.Code != item.status {
				t.Fatalf("returned %d, expected %d", response.Code, item.status)
			}
		})
	}
}
