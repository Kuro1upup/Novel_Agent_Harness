package handler

import (
	"errors"
	"log"
	"net/http"
	"strconv"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/shopspring/decimal"

	"second-brain/billing/internal/domain"
	"second-brain/billing/internal/middleware"
	"second-brain/billing/internal/pkg/config"
	"second-brain/billing/internal/service"
)

// BillingHandler holds HTTP handlers for billing endpoints.
type BillingHandler struct {
	svc *service.BillingService
	cfg *config.Config
}

// NewBillingHandler creates a new BillingHandler.
func NewBillingHandler(svc *service.BillingService, cfg *config.Config) *BillingHandler {
	return &BillingHandler{svc: svc, cfg: cfg}
}

// ── Request DTOs ──

type RechargeRequest struct {
	UserID        int64   `json:"user_id" binding:"required"`
	AmountYuan    float64 `json:"amount_yuan" binding:"required"`
	Note          string  `json:"note"`
	AdminPassword string  `json:"admin_password" binding:"required"`
}

type InitBalanceRequest struct {
	UserID int64 `json:"user_id" binding:"required"`
}

type RecordUsageRequest struct {
	EventID         string `json:"event_id"`
	UserID          int64  `json:"user_id" binding:"required"`
	Model           string `json:"model" binding:"required"`
	Subsystem       string `json:"subsystem" binding:"required"`
	InputTokens     int    `json:"input_tokens"`
	CacheHitTokens  int    `json:"cache_hit_tokens"`
	CacheMissTokens int    `json:"cache_miss_tokens"`
	OutputTokens    int    `json:"output_tokens"`
}

// ── Response DTOs (float64 for frontend compatibility) ──

type UsageDailyResponse struct {
	Date                 string  `json:"date"`
	Model                string  `json:"model"`
	Subsystem            string  `json:"subsystem"`
	TotalInputTokens     int     `json:"total_input_tokens"`
	TotalCacheHitTokens  int     `json:"total_cache_hit_tokens"`
	TotalCacheMissTokens int     `json:"total_cache_miss_tokens"`
	TotalOutputTokens    int     `json:"total_output_tokens"`
	TotalTokens          int     `json:"total_tokens"`
	CostYuan             float64 `json:"cost_yuan"`
}

type BillItemResponse struct {
	Model                string  `json:"model"`
	BillMonth            string  `json:"bill_month"`
	TotalInputTokens     int     `json:"total_input_tokens"`
	TotalCacheHitTokens  int     `json:"total_cache_hit_tokens"`
	TotalCacheMissTokens int     `json:"total_cache_miss_tokens"`
	TotalOutputTokens    int     `json:"total_output_tokens"`
	CostYuan             float64 `json:"cost_yuan"`
}

type ModelCostResponse struct {
	Model           string  `json:"model"`
	BillMonth       string  `json:"bill_month"`
	InputTokens     int     `json:"input_tokens"`
	CacheHitTokens  int     `json:"cache_hit_tokens"`
	CacheMissTokens int     `json:"cache_miss_tokens"`
	OutputTokens    int     `json:"output_tokens"`
	CostYuan        float64 `json:"cost_yuan"`
}

type RechargeResponse struct {
	ID         int64   `json:"id"`
	AmountYuan float64 `json:"amount_yuan"`
	Note       string  `json:"note"`
	CreatedAt  string  `json:"created_at"`
}

// ── Conversion helpers ──

func toUsageDailyItems(items []domain.UsageDailyItem) []UsageDailyResponse {
	out := make([]UsageDailyResponse, len(items))
	for i, item := range items {
		out[i] = UsageDailyResponse{
			Date:                 item.Date,
			Model:                item.Model,
			Subsystem:            item.Subsystem,
			TotalInputTokens:     item.TotalInputTokens,
			TotalCacheHitTokens:  item.TotalCacheHitTokens,
			TotalCacheMissTokens: item.TotalCacheMissTokens,
			TotalOutputTokens:    item.TotalOutputTokens,
			TotalTokens:          item.TotalTokens,
			CostYuan:             item.CostYuan.InexactFloat64(),
		}
	}
	return out
}

func toBillItemResponses(items []domain.BillItem) []BillItemResponse {
	out := make([]BillItemResponse, len(items))
	for i, item := range items {
		out[i] = BillItemResponse{
			Model:                item.Model,
			BillMonth:            item.BillMonth,
			TotalInputTokens:     item.TotalInputTokens,
			TotalCacheHitTokens:  item.TotalCacheHitTokens,
			TotalCacheMissTokens: item.TotalCacheMissTokens,
			TotalOutputTokens:    item.TotalOutputTokens,
			CostYuan:             item.CostYuan.InexactFloat64(),
		}
	}
	return out
}

func toModelCostResponses(items []domain.ModelCostItem) []ModelCostResponse {
	out := make([]ModelCostResponse, len(items))
	for i, item := range items {
		out[i] = ModelCostResponse{
			Model:           item.Model,
			BillMonth:       item.BillMonth,
			InputTokens:     item.InputTokens,
			CacheHitTokens:  item.CacheHitTokens,
			CacheMissTokens: item.CacheMissTokens,
			OutputTokens:    item.OutputTokens,
			CostYuan:        item.CostYuan.InexactFloat64(),
		}
	}
	return out
}

func toRechargeResponses(items []domain.RechargeItem) []RechargeResponse {
	out := make([]RechargeResponse, len(items))
	for i, item := range items {
		out[i] = RechargeResponse{
			ID:         item.ID,
			AmountYuan: item.AmountYuan.InexactFloat64(),
			Note:       item.Note,
			CreatedAt:  item.CreatedAt.Format(time.RFC3339),
		}
	}
	return out
}

// ── Helpers ──

func defaultStartDate() string {
	return time.Now().UTC().Format("2006-01") + "-01"
}

func defaultEndDate() string {
	return time.Now().UTC().Format("2006-01-02")
}

// ── Public Endpoints ──

// GetUsage handles GET /api/billing/usage.
func (h *BillingHandler) GetUsage(c *gin.Context) {
	userID := middleware.GetUserID(c)
	startDate := c.DefaultQuery("start_date", defaultStartDate())
	endDate := c.DefaultQuery("end_date", defaultEndDate())
	page, _ := strconv.Atoi(c.DefaultQuery("page", "1"))
	pageSize, _ := strconv.Atoi(c.DefaultQuery("page_size", "20"))
	if page < 1 {
		page = 1
	}
	if pageSize < 1 || pageSize > 200 {
		pageSize = 20
	}

	result, err := h.svc.GetDailyUsage(userID, startDate, endDate, page, pageSize)
	if err != nil {
		log.Printf("GetDailyUsage error: %v", err)
		c.JSON(http.StatusInternalServerError, gin.H{"success": false, "error": err.Error()})
		return
	}

	items, _ := result.Items.([]domain.UsageDailyItem)

	c.JSON(http.StatusOK, gin.H{
		"success":                 true,
		"items":                   toUsageDailyItems(items),
		"total_count":             result.TotalCount,
		"page":                    result.Page,
		"page_size":               result.PageSize,
		"total_tokens":            result.TotalTokens,
		"total_input_tokens":      result.TotalInputTokens,
		"total_cache_hit_tokens":  result.TotalCacheHitTokens,
		"total_cache_miss_tokens": result.TotalCacheMissTokens,
		"total_output_tokens":     result.TotalOutputTokens,
		"total_cost":              result.TotalCost.InexactFloat64(),
		"start_date":              startDate,
		"end_date":                endDate,
	})
}

// GetBills handles GET /api/billing/bills.
func (h *BillingHandler) GetBills(c *gin.Context) {
	userID := middleware.GetUserID(c)
	startDate := c.DefaultQuery("start_date", defaultStartDate())
	endDate := c.DefaultQuery("end_date", defaultEndDate())
	page, _ := strconv.Atoi(c.DefaultQuery("page", "1"))
	pageSize, _ := strconv.Atoi(c.DefaultQuery("page_size", "20"))
	if page < 1 {
		page = 1
	}
	if pageSize < 1 || pageSize > 200 {
		pageSize = 20
	}

	result, err := h.svc.GetBills(userID, startDate, endDate, page, pageSize)
	if err != nil {
		log.Printf("GetBills error: %v", err)
		c.JSON(http.StatusInternalServerError, gin.H{"success": false, "error": err.Error()})
		return
	}

	items, _ := result.Items.([]domain.BillItem)

	c.JSON(http.StatusOK, gin.H{
		"success":                 true,
		"items":                   toBillItemResponses(items),
		"total_count":             result.TotalCount,
		"page":                    result.Page,
		"page_size":               result.PageSize,
		"total_input_tokens":      result.TotalInputTokens,
		"total_cache_hit_tokens":  result.TotalCacheHitTokens,
		"total_cache_miss_tokens": result.TotalCacheMissTokens,
		"total_output_tokens":     result.TotalOutputTokens,
		"total_cost":              result.TotalCost.InexactFloat64(),
		"start_date":              startDate,
		"end_date":                endDate,
	})
}

// GetBalance handles GET /api/billing/balance.
func (h *BillingHandler) GetBalance(c *gin.Context) {
	userID := middleware.GetUserID(c)
	startDate := c.DefaultQuery("start_date", defaultStartDate())
	endDate := c.DefaultQuery("end_date", defaultEndDate())

	result, err := h.svc.GetBalance(userID, startDate, endDate)
	if err != nil {
		log.Printf("GetBalance error: %v", err)
		c.JSON(http.StatusInternalServerError, gin.H{"success": false, "error": err.Error()})
		return
	}

	c.JSON(http.StatusOK, gin.H{
		"success":           true,
		"total_recharge":    result.TotalRecharge.InexactFloat64(),
		"total_consumption": result.TotalConsumption.InexactFloat64(),
		"balance":           result.Balance.InexactFloat64(),
		"model_costs":       toModelCostResponses(result.ModelCosts),
		"recharges":         toRechargeResponses(result.Recharges),
	})
}

// Recharge handles POST /api/billing/recharges (admin only).
func (h *BillingHandler) Recharge(c *gin.Context) {
	var req RechargeRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"detail": "参数错误"})
		return
	}

	if req.AdminPassword != h.cfg.AdminPassword {
		c.JSON(http.StatusOK, gin.H{"success": false, "error": "鉴权失败：管理员密码错误"})
		return
	}

	if req.AmountYuan <= 0 {
		c.JSON(http.StatusOK, gin.H{"success": false, "error": "充值金额必须大于 0"})
		return
	}

	amount := decimal.NewFromFloat(req.AmountYuan)
	note := req.Note
	if note == "" {
		note = "管理员充值"
	}

	rid, err := h.svc.RecordRecharge(req.UserID, amount, note)
	if err != nil {
		log.Printf("Recharge error: %v", err)
		c.JSON(http.StatusInternalServerError, gin.H{"success": false, "error": err.Error()})
		return
	}

	log.Printf("Admin recharge: user=%d amount=%s id=%d", req.UserID, amount.String(), rid)
	c.JSON(http.StatusOK, gin.H{"success": true, "id": rid})
}

// ListRecharges handles GET /api/billing/recharges.
func (h *BillingHandler) ListRecharges(c *gin.Context) {
	userID := middleware.GetUserID(c)
	startDate := c.DefaultQuery("start_date", "")
	endDate := c.DefaultQuery("end_date", "")

	items, err := h.svc.GetRecharges(userID, startDate, endDate)
	if err != nil {
		log.Printf("ListRecharges error: %v", err)
		c.JSON(http.StatusInternalServerError, gin.H{"success": false, "error": err.Error()})
		return
	}

	c.JSON(http.StatusOK, gin.H{"success": true, "items": toRechargeResponses(items)})
}

// ── Internal Endpoints ──

// RecordUsageInternal handles POST /api/billing/internal/usage (HTTP alternative to Redis).
func (h *BillingHandler) RecordUsageInternal(c *gin.Context) {
	var req RecordUsageRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"detail": "参数错误"})
		return
	}

	id, err := h.svc.RecordUsageEvent(req.EventID, req.UserID, req.Model, req.Subsystem,
		req.InputTokens, req.CacheHitTokens, req.CacheMissTokens, req.OutputTokens)
	if err != nil {
		log.Printf("RecordUsage internal error: %v", err)
		if errors.Is(err, service.ErrInvalidBillingRequest) {
			c.JSON(http.StatusBadRequest, gin.H{"detail": err.Error()})
			return
		}
		c.JSON(http.StatusInternalServerError, gin.H{"success": false, "error": err.Error()})
		return
	}

	c.JSON(http.StatusOK, gin.H{"success": true, "id": id})
}

// CheckBalanceInternal handles GET /api/billing/internal/balance-check.
func (h *BillingHandler) CheckBalanceInternal(c *gin.Context) {
	userIDStr := c.Query("user_id")
	userID, err := strconv.ParseInt(userIDStr, 10, 64)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"detail": "user_id is required"})
		return
	}

	balance, err := h.svc.CheckBalance(userID)
	if err != nil {
		log.Printf("CheckBalance error: %v", err)
		c.JSON(http.StatusInternalServerError, gin.H{"success": false, "error": err.Error()})
		return
	}

	c.JSON(http.StatusOK, gin.H{
		"success":     true,
		"balance":     balance.InexactFloat64(),
		"is_negative": balance.IsNegative(),
	})
}

// InitBalanceInternal handles POST /api/billing/internal/init-balance.
func (h *BillingHandler) InitBalanceInternal(c *gin.Context) {
	var req InitBalanceRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"detail": "user_id is required"})
		return
	}

	id, err := h.svc.InitBalance(req.UserID)
	if err != nil {
		log.Printf("InitBalance error: %v", err)
		if errors.Is(err, service.ErrInvalidBillingRequest) {
			c.JSON(http.StatusBadRequest, gin.H{"detail": err.Error()})
			return
		}
		c.JSON(http.StatusInternalServerError, gin.H{"success": false, "error": err.Error()})
		return
	}

	c.JSON(http.StatusOK, gin.H{"success": true, "id": id})
}
