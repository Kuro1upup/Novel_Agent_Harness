// Package email provides a Tencent Cloud Simple Email Service (SES) client
// using the HTTP REST API with TC3-HMAC-SHA256 signing (no SDK dependency).
package email

import (
	"bytes"
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"strconv"
	"strings"
	"time"
)

const (
	TemplateLoginVerify   = 50933
	TemplatePasswordReset = 50934

	FromAddress  = "second_brain@email.dsppt.site"
	SiteName     = "Second Brain"
	SupportEmail = "gxl77504@outlook.com"

	DefaultValidMinutes = 5

	sesEndpoint = "ses.tencentcloudapi.com"
	sesService  = "ses"
	sesVersion  = "2020-10-02"
	sesAction   = "SendEmail"
)

// Config holds the Email client configuration.
type Config struct {
	SecretID  string
	SecretKey string
	Region    string
}

// Client wraps the Tencent Cloud SES REST API.
type Client struct {
	secretID  string
	secretKey string
	region    string
	hc        *http.Client
}

// NewClient creates a new SES Client.
func NewClient(cfg Config) (*Client, error) {
	if cfg.Region == "" {
		cfg.Region = "ap-guangzhou"
	}
	return &Client{
		secretID:  cfg.SecretID,
		secretKey: cfg.SecretKey,
		region:    cfg.Region,
		hc:        &http.Client{Timeout: 10 * time.Second},
	}, nil
}

// SendVerificationCode sends a verification code email.
func (c *Client) SendVerificationCode(ctx context.Context, toEmail, userName, code string) error {
	templateData := fmt.Sprintf(
		`{"site_name":"%s","user_name":"%s","valid_minutes":"%d","verification_code":"%s","support_email":"%s","current_year":"%s"}`,
		SiteName, escapeJSON(userName), DefaultValidMinutes, code, SupportEmail, currentYear(),
	)
	return c.send(ctx, toEmail, TemplateLoginVerify, templateData, "Second Brain 登录验证码")
}

// SendPasswordResetLink sends a password reset link email.
func (c *Client) SendPasswordResetLink(ctx context.Context, toEmail, userName, resetLink string) error {
	templateData := fmt.Sprintf(
		`{"site_name":"%s","user_name":"%s","valid_minutes":"%d","reset_link":"%s","support_email":"%s","current_year":"%s"}`,
		SiteName, escapeJSON(userName), DefaultValidMinutes, resetLink, SupportEmail, currentYear(),
	)
	return c.send(ctx, toEmail, TemplatePasswordReset, templateData, "Second Brain 密码重置")
}

// ── TC3-HMAC-SHA256 REST API call ──

type sesBody struct {
	FromEmailAddress string   `json:"FromEmailAddress"`
	Destination      []string `json:"Destination"`
	Subject          string   `json:"Subject"`
	Template         sesTmpl  `json:"Template"`
	TriggerType      int      `json:"TriggerType"`
}

type sesTmpl struct {
	TemplateID   int    `json:"TemplateID"`
	TemplateData string `json:"TemplateData"`
}

type sesResponse struct {
	Response struct {
		MessageId string `json:"MessageId"`
		RequestId string `json:"RequestId"`
		Error     struct {
			Code    string `json:"Code"`
			Message string `json:"Message"`
		} `json:"Error"`
	} `json:"Response"`
}

func (c *Client) send(ctx context.Context, toEmail string, templateID int64, templateData, subject string) error {
	body := sesBody{
		FromEmailAddress: FromAddress,
		Destination:      []string{toEmail},
		Subject:          subject,
		Template:         sesTmpl{TemplateID: int(templateID), TemplateData: templateData},
		TriggerType:      1,
	}

	payload, _ := json.Marshal(body)
	req, err := http.NewRequestWithContext(ctx, "POST", "https://"+sesEndpoint, bytes.NewReader(payload))
	if err != nil {
		return fmt.Errorf("build request: %w", err)
	}

	timestamp := time.Now().UTC().Unix()
	date := time.Now().UTC().Format("2006-01-02")
	hashedPayload := sha256Hex(payload)

	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Host", sesEndpoint)
	req.Header.Set("X-TC-Action", sesAction)
	req.Header.Set("X-TC-Version", sesVersion)
	req.Header.Set("X-TC-Timestamp", strconv.FormatInt(timestamp, 10))
	req.Header.Set("X-TC-Region", c.region)

	// TC3 signature.
	canonicalHeaders := fmt.Sprintf("content-type:application/json\nhost:%s\n", sesEndpoint)
	signedHeaders := "content-type;host"
	canonicalRequest := fmt.Sprintf("POST\n/\n\n%s\n%s\n%s", canonicalHeaders, signedHeaders, hashedPayload)

	algorithm := "TC3-HMAC-SHA256"
	credentialScope := fmt.Sprintf("%s/%s/tc3_request", date, sesService)
	stringToSign := fmt.Sprintf("%s\n%d\n%s\n%s", algorithm, timestamp, credentialScope, sha256Hex([]byte(canonicalRequest)))

	signature := tc3Sign(c.secretKey, date, sesService, stringToSign)
	authorization := fmt.Sprintf("%s Credential=%s/%s, SignedHeaders=%s, Signature=%s",
		algorithm, c.secretID, credentialScope, signedHeaders, signature)
	req.Header.Set("Authorization", authorization)

	resp, err := c.hc.Do(req)
	if err != nil {
		return fmt.Errorf("ses http request: %w", err)
	}
	defer resp.Body.Close()

	respBytes, _ := io.ReadAll(resp.Body)
	var apiResp sesResponse
	if err := json.Unmarshal(respBytes, &apiResp); err != nil {
		return fmt.Errorf("unmarshal ses response: %w (body=%s)", err, string(respBytes))
	}

	if apiResp.Response.Error.Code != "" {
		return fmt.Errorf("ses error: %s - %s", apiResp.Response.Error.Code, apiResp.Response.Error.Message)
	}

	log.Printf("Email sent to %s, template=%d, message_id=%s", maskEmail(toEmail), templateID, apiResp.Response.MessageId)
	return nil
}

// ── TC3 signing helpers ──

func sha256Hex(data []byte) string {
	h := sha256.Sum256(data)
	return hex.EncodeToString(h[:])
}

func tc3Sign(secretKey, date, service, stringToSign string) string {
	mac := func(key []byte, data string) []byte {
		m := hmac.New(sha256.New, key)
		m.Write([]byte(data))
		return m.Sum(nil)
	}
	secretDate := mac([]byte("TC3"+secretKey), date)
	secretService := mac(secretDate, service)
	secretSigning := mac(secretService, "tc3_request")
	return hex.EncodeToString(mac(secretSigning, stringToSign))
}

// ── Helpers ──

func escapeJSON(s string) string {
	s = strings.ReplaceAll(s, `\`, `\\`)
	s = strings.ReplaceAll(s, `"`, `\"`)
	return s
}

func currentYear() string {
	return strconv.Itoa(time.Now().Year())
}

func maskEmail(email string) string {
	at := strings.Index(email, "@")
	if at > 1 {
		return email[:1] + "***" + email[at:]
	}
	return email
}
