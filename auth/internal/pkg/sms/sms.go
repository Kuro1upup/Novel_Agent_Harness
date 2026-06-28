// Package sms provides a Tencent Cloud SMS client using the v5 REST API
// with AppID + AppKey authentication (no SecretId/SecretKey required).
package sms

import (
	"bytes"
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"math/rand"
	"net/http"
	"time"
)

const (
	sendSmsURL = "https://yun.tim.qq.com/v5/tlssmssvr/sendmultisms2"
)

// Config holds SMS client configuration.
type Config struct {
	AppID      string // SMS SDK App ID (1401142936)
	AppKey     string // SMS SDK App Key
	SignName   string // Approved SMS signature
	TemplateID string // Approved SMS template ID
}

// Client wraps the Tencent Cloud SMS REST API.
type Client struct {
	appID      string
	appKey     string
	signName   string
	templateID string
	httpClient *http.Client
}

// NewClient creates a new SMS Client.
func NewClient(cfg Config) *Client {
	return &Client{
		appID:      cfg.AppID,
		appKey:     cfg.AppKey,
		signName:   cfg.SignName,
		templateID: cfg.TemplateID,
		httpClient: &http.Client{Timeout: 10 * time.Second},
	}
}

type smsPhone struct {
	NationCode string `json:"nationcode"`
	Mobile     string `json:"mobile"`
}

type smsRequest struct {
	Tel    []smsPhone `json:"tel"`
	Type   int        `json:"type"`   // 0 = normal SMS
	Sign   string     `json:"sign"`   // signature name
	TplID  int        `json:"tpl_id"` // template ID
	Params []string   `json:"params"` // template parameters
	Sig    string     `json:"sig"`    // SHA256 signature
	Time   int64      `json:"time"`   // unix timestamp
	Extend string     `json:"extend"`
	Ext    string     `json:"ext"`
}

type smsResponse struct {
	Result int    `json:"result"`
	ErrMsg string `json:"errmsg"`
	Ext    string `json:"ext"`
	Fee    int    `json:"fee"`
	Sid    string `json:"sid"`
}

// SendCode sends a verification code SMS to the given phone number.
// phone should be in national format, e.g. "13800000000".
// nationCode is "86" for China.
func (c *Client) SendCode(phone, code string) (string, error) {
	// return c.sendSms(phone, "86", []string{code})
	log.Println("本地生成验证码，验证码为：" + code + "，用户：" + phone + "。因为短信发送系统暂时未生效，验证码未实际发送。")
	return "", nil
}

// SendPasswordResetLink sends a password reset link via SMS.
func (c *Client) SendPasswordResetLink(phone, resetLink string) (string, error) {
	// return c.sendSms(phone, "86", []string{resetLink})
	log.Println("本地生成密码重置链接，链接为：" + resetLink + "，用户：" + phone + "。因为短信发送系统暂时未生效，密码重置链接未实际发送。")
	return "", nil
}

func (c *Client) sendSms(phone, nationCode string, params []string) (string, error) {
	random := rand.Int63n(999999)
	curTime := time.Now().Unix()

	// Build signature: sha256(appkey + random + curTime + phone)
	sig := smsSignature(c.appKey, random, curTime, phone)

	reqBody := smsRequest{
		Tel: []smsPhone{
			{NationCode: nationCode, Mobile: phone},
		},
		Type:   0,
		Sign:   c.signName,
		TplID:  mustAtoi(c.templateID),
		Params: params,
		Sig:    sig,
		Time:   curTime,
		Extend: "",
		Ext:    "",
	}

	bodyBytes, err := json.Marshal(reqBody)
	if err != nil {
		return "", fmt.Errorf("marshal sms request: %w", err)
	}

	url := fmt.Sprintf("%s?sdkappid=%s&random=%d", sendSmsURL, c.appID, random)
	resp, err := c.httpClient.Post(url, "application/json", bytes.NewReader(bodyBytes))
	if err != nil {
		return "", fmt.Errorf("sms http request: %w", err)
	}
	defer resp.Body.Close()

	respBytes, err := io.ReadAll(resp.Body)
	if err != nil {
		return "", fmt.Errorf("read sms response: %w", err)
	}

	var smsResp smsResponse
	if err := json.Unmarshal(respBytes, &smsResp); err != nil {
		return "", fmt.Errorf("unmarshal sms response: %w, body=%s", err, string(respBytes))
	}

	if smsResp.Result != 0 {
		return "", fmt.Errorf("sms send failed: result=%d, errmsg=%s", smsResp.Result, smsResp.ErrMsg)
	}

	log.Printf("SMS sent to %s%s, sid=%s", nationCode, maskPhone(phone), smsResp.Sid)
	return smsResp.Sid, nil
}

// smsSignature computes sha256(appkey + random + curTime + phones).
func smsSignature(appKey string, random int64, curTime int64, phones ...string) string {
	data := fmt.Sprintf("%s%d%d", appKey, random, curTime)
	for _, p := range phones {
		data += p
	}
	h := sha256.Sum256([]byte(data))
	return fmt.Sprintf("%x", h)
}

func mustAtoi(s string) int {
	var n int
	fmt.Sscanf(s, "%d", &n)
	return n
}

func maskPhone(phone string) string {
	if len(phone) >= 7 {
		return phone[:3] + "****" + phone[len(phone)-4:]
	}
	return "****"
}
