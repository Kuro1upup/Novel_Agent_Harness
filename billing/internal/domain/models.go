package domain

import (
	"time"

	"github.com/shopspring/decimal"
)

// TokenUsageRecord represents a raw per-request token usage entry.
type TokenUsageRecord struct {
	ID              int64     `json:"id"`
	EventID         string    `json:"event_id,omitempty"`
	UserID          int64     `json:"user_id"`
	Model           string    `json:"model"`
	Subsystem       string    `json:"subsystem"`
	InputTokens     int       `json:"input_tokens"`
	CacheHitTokens  int       `json:"cache_hit_tokens"`
	CacheMissTokens int       `json:"cache_miss_tokens"`
	OutputTokens    int       `json:"output_tokens"`
	TotalTokens     int       `json:"total_tokens"`
	CreatedAt       time.Time `json:"created_at"`
}

// BillItem is a monthly aggregated bill for one model.
type BillItem struct {
	Model                string          `json:"model"`
	BillMonth            string          `json:"bill_month"` // "YYYY-MM"
	TotalInputTokens     int             `json:"total_input_tokens"`
	TotalCacheHitTokens  int             `json:"total_cache_hit_tokens"`
	TotalCacheMissTokens int             `json:"total_cache_miss_tokens"`
	TotalOutputTokens    int             `json:"total_output_tokens"`
	CostYuan             decimal.Decimal `json:"cost_yuan"`
}

// UsageDailyItem is a daily usage breakdown entry.
type UsageDailyItem struct {
	Date                 string          `json:"date"`
	Model                string          `json:"model"`
	Subsystem            string          `json:"subsystem"`
	TotalInputTokens     int             `json:"total_input_tokens"`
	TotalCacheHitTokens  int             `json:"total_cache_hit_tokens"`
	TotalCacheMissTokens int             `json:"total_cache_miss_tokens"`
	TotalOutputTokens    int             `json:"total_output_tokens"`
	TotalTokens          int             `json:"total_tokens"`
	CostYuan             decimal.Decimal `json:"cost_yuan"`
}

// PaginatedResult is a generic paginated query result with aggregated totals.
type PaginatedResult struct {
	Items                interface{}     `json:"items"`
	TotalCount           int             `json:"total_count"`
	Page                 int             `json:"page"`
	PageSize             int             `json:"page_size"`
	TotalTokens          int             `json:"total_tokens"`
	TotalInputTokens     int             `json:"total_input_tokens"`
	TotalCacheHitTokens  int             `json:"total_cache_hit_tokens"`
	TotalCacheMissTokens int             `json:"total_cache_miss_tokens"`
	TotalOutputTokens    int             `json:"total_output_tokens"`
	TotalCost            decimal.Decimal `json:"total_cost"`
}

// BalanceResult holds the full balance breakdown.
type BalanceResult struct {
	TotalRecharge    decimal.Decimal `json:"total_recharge"`
	TotalConsumption decimal.Decimal `json:"total_consumption"`
	Balance          decimal.Decimal `json:"balance"`
	ModelCosts       []ModelCostItem `json:"model_costs"`
	Recharges        []RechargeItem  `json:"recharges"`
}

// ModelCostItem is a per-model cost breakdown.
type ModelCostItem struct {
	Model           string          `json:"model"`
	BillMonth       string          `json:"bill_month"`
	InputTokens     int             `json:"input_tokens"`
	CacheHitTokens  int             `json:"cache_hit_tokens"`
	CacheMissTokens int             `json:"cache_miss_tokens"`
	OutputTokens    int             `json:"output_tokens"`
	CostYuan        decimal.Decimal `json:"cost_yuan"`
}

// RechargeItem represents a recharge record.
type RechargeItem struct {
	ID         int64           `json:"id"`
	AmountYuan decimal.Decimal `json:"amount_yuan"`
	Note       string          `json:"note"`
	CreatedAt  time.Time       `json:"created_at"`
}

// LLMUsageEvent is the Redis stream event published after each LLM call.
type LLMUsageEvent struct {
	UserID          int64  `json:"user_id"`
	Model           string `json:"model"`
	Subsystem       string `json:"subsystem"`
	InputTokens     int    `json:"input_tokens"`
	CacheHitTokens  int    `json:"cache_hit_tokens"`
	CacheMissTokens int    `json:"cache_miss_tokens"`
	OutputTokens    int    `json:"output_tokens"`
	TotalTokens     int    `json:"total_tokens"`
	Timestamp       string `json:"timestamp"`
}
