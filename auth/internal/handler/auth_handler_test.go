package handler

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/gin-gonic/gin"

	"second-brain/auth/internal/pkg/config"
)

func TestPhoneRegistrationIsDisabled(t *testing.T) {
	gin.SetMode(gin.TestMode)
	authHandler := NewAuthHandler(nil, &config.Config{PhoneRegistrationEnabled: false})
	router := gin.New()
	router.POST("/send-code", authHandler.SendRegisterCode)
	router.POST("/register", authHandler.Register)

	requests := []struct {
		path string
		body string
	}{
		{"/send-code", `{"method":"phone","phone":"13800000000"}`},
		{"/register", `{"method":"phone","phone":"13800000000","password":"secret","code":"123456"}`},
	}
	for _, item := range requests {
		request := httptest.NewRequest(http.MethodPost, item.path, strings.NewReader(item.body))
		request.Header.Set("Content-Type", "application/json")
		response := httptest.NewRecorder()
		router.ServeHTTP(response, request)
		if response.Code != http.StatusForbidden {
			t.Fatalf("%s returned %d, expected %d", item.path, response.Code, http.StatusForbidden)
		}
		if !strings.Contains(response.Body.String(), "已关闭手机号注册") {
			t.Fatalf("%s returned unexpected response: %s", item.path, response.Body.String())
		}
	}
}

func TestCapabilitiesExposePhoneRegistrationSetting(t *testing.T) {
	gin.SetMode(gin.TestMode)
	authHandler := NewAuthHandler(nil, &config.Config{PhoneRegistrationEnabled: true})
	router := gin.New()
	router.GET("/capabilities", authHandler.Capabilities)

	request := httptest.NewRequest(http.MethodGet, "/capabilities", nil)
	response := httptest.NewRecorder()
	router.ServeHTTP(response, request)

	if response.Code != http.StatusOK {
		t.Fatalf("returned %d, expected %d", response.Code, http.StatusOK)
	}
	if !strings.Contains(response.Body.String(), `"phone_registration_enabled":true`) {
		t.Fatalf("unexpected response: %s", response.Body.String())
	}
}

func TestLocalBootstrapIsDisabledUnlessExplicitlyEnabled(t *testing.T) {
	gin.SetMode(gin.TestMode)
	authHandler := NewAuthHandler(nil, &config.Config{LocalBootstrapEnabled: false})
	router := gin.New()
	router.POST("/bootstrap", authHandler.BootstrapLocalUser)

	request := httptest.NewRequest(
		http.MethodPost,
		"/bootstrap",
		strings.NewReader(`{"email":"author@local.test","password":"local-password"}`),
	)
	request.Header.Set("Content-Type", "application/json")
	response := httptest.NewRecorder()
	router.ServeHTTP(response, request)

	if response.Code != http.StatusForbidden {
		t.Fatalf("returned %d, expected %d", response.Code, http.StatusForbidden)
	}
	if !strings.Contains(response.Body.String(), "未启用本地账号初始化") {
		t.Fatalf("unexpected response: %s", response.Body.String())
	}
}
