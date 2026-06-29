package service

import (
	"github.com/shopspring/decimal"

	"second-brain/billing/internal/domain"
	"second-brain/billing/internal/repository"
)

// BillingService orchestrates billing business logic.
type BillingService struct {
	repo *repository.BillingRepo
}

// NewBillingService creates a new BillingService.
func NewBillingService(repo *repository.BillingRepo) *BillingService {
	return &BillingService{repo: repo}
}

// RecordUsage records a token usage event and updates the monthly bill.
func (s *BillingService) RecordUsage(userID int64, model, subsystem string,
	inputTokens, cacheHitTokens, cacheMissTokens, outputTokens int) (int64, error) {
	return s.RecordUsageEvent(
		"",
		userID,
		model,
		subsystem,
		inputTokens,
		cacheHitTokens,
		cacheMissTokens,
		outputTokens,
	)
}

// RecordUsageEvent records an idempotent stream event and updates its monthly bill atomically.
func (s *BillingService) RecordUsageEvent(eventID string, userID int64, model, subsystem string,
	inputTokens, cacheHitTokens, cacheMissTokens, outputTokens int) (int64, error) {
	total := inputTokens + outputTokens
	record := &domain.TokenUsageRecord{
		EventID:         eventID,
		UserID:          userID,
		Model:           model,
		Subsystem:       subsystem,
		InputTokens:     inputTokens,
		CacheHitTokens:  cacheHitTokens,
		CacheMissTokens: cacheMissTokens,
		OutputTokens:    outputTokens,
		TotalTokens:     total,
	}
	return s.repo.RecordUsage(record)
}

// GetBills returns paginated monthly bills.
func (s *BillingService) GetBills(userID int64, startDate, endDate string,
	page, pageSize int) (*domain.PaginatedResult, error) {
	return s.repo.GetBills(userID, startDate, endDate, page, pageSize)
}

// GetDailyUsage returns paginated daily usage.
func (s *BillingService) GetDailyUsage(userID int64, startDate, endDate string,
	page, pageSize int) (*domain.PaginatedResult, error) {
	return s.repo.GetDailyUsage(userID, startDate, endDate, page, pageSize)
}

// RecordRecharge adds funds to a user's account.
func (s *BillingService) RecordRecharge(userID int64, amountYuan decimal.Decimal, note string) (int64, error) {
	return s.repo.RecordRecharge(userID, amountYuan, note)
}

// GetRecharges returns recharge history, optionally filtered by date range.
func (s *BillingService) GetRecharges(userID int64, startDate, endDate string) ([]domain.RechargeItem, error) {
	return s.repo.GetRecharges(userID, startDate, endDate)
}

// InitBalance gives a new user their initial balance.
func (s *BillingService) InitBalance(userID int64) (int64, error) {
	return s.repo.InitBalance(userID)
}

// GetBalance returns the full balance breakdown.
func (s *BillingService) GetBalance(userID int64, startDate, endDate string) (*domain.BalanceResult, error) {
	return s.repo.GetBalance(userID, startDate, endDate)
}

// CheckBalance returns just the balance amount.
func (s *BillingService) CheckBalance(userID int64) (decimal.Decimal, error) {
	return s.repo.CheckBalance(userID)
}
