package repository

import (
	"database/sql"
	"errors"
	"fmt"
	"log"
	"time"

	"github.com/go-sql-driver/mysql"
	"github.com/shopspring/decimal"

	"second-brain/billing/internal/domain"
)

// BillingRepo implements MySQL-backed billing persistence.
type BillingRepo struct {
	db *sql.DB
}

// NewBillingRepo creates a new BillingRepo.
func NewBillingRepo(db *sql.DB) *BillingRepo {
	return &BillingRepo{db: db}
}

// ── Record Usage ──

// RecordUsage inserts a raw usage record and upserts the monthly bill.
func (r *BillingRepo) RecordUsage(record *domain.TokenUsageRecord) (int64, error) {
	tx, err := r.db.Begin()
	if err != nil {
		return 0, fmt.Errorf("begin usage transaction: %w", err)
	}
	defer tx.Rollback()

	id, err := insertUsage(tx, record)
	if err != nil {
		if record.EventID != "" && isDuplicateKeyError(err) {
			_ = tx.Rollback()
			var existingID int64
			queryErr := r.db.QueryRow(
				`SELECT id FROM token_usage_records WHERE event_id = ?`,
				record.EventID,
			).Scan(&existingID)
			if queryErr != nil {
				return 0, fmt.Errorf("find existing usage event: %w", queryErr)
			}
			return existingID, nil
		}
		return 0, err
	}
	if err := upsertBill(tx, record); err != nil {
		return 0, err
	}
	if err := tx.Commit(); err != nil {
		return 0, fmt.Errorf("commit usage transaction: %w", err)
	}
	log.Printf("Token usage recorded: user=%d model=%s subsystem=%s total=%d id=%d",
		record.UserID, record.Model, record.Subsystem, record.TotalTokens, id)
	return id, nil
}

func insertUsage(tx *sql.Tx, record *domain.TokenUsageRecord) (int64, error) {
	var eventID interface{}
	if record.EventID != "" {
		eventID = record.EventID
	}
	result, err := tx.Exec(
		`INSERT INTO token_usage_records
		 (event_id, user_id, model, subsystem, input_tokens, cache_hit_tokens,
		  cache_miss_tokens, output_tokens, total_tokens)
		 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`,
		eventID, record.UserID, record.Model, record.Subsystem,
		record.InputTokens, record.CacheHitTokens, record.CacheMissTokens,
		record.OutputTokens, record.TotalTokens,
	)
	if err != nil {
		return 0, fmt.Errorf("insert usage: %w", err)
	}
	id, _ := result.LastInsertId()
	return id, nil
}

func upsertBill(tx *sql.Tx, record *domain.TokenUsageRecord) error {
	billMonth := time.Now().UTC().Format("2006-01")
	cost := domain.CalculateCost(record.Model, record.CacheHitTokens, record.CacheMissTokens, record.OutputTokens)

	_, err := tx.Exec(
		`INSERT INTO bills
		 (user_id, bill_month, model, total_input_tokens,
		  total_cache_hit_tokens, total_cache_miss_tokens,
		  total_output_tokens, cost_yuan)
		 VALUES (?, ?, ?, ?, ?, ?, ?, ?)
		 ON DUPLICATE KEY UPDATE
		   total_input_tokens = total_input_tokens + VALUES(total_input_tokens),
		   total_cache_hit_tokens = total_cache_hit_tokens + VALUES(total_cache_hit_tokens),
		   total_cache_miss_tokens = total_cache_miss_tokens + VALUES(total_cache_miss_tokens),
		   total_output_tokens = total_output_tokens + VALUES(total_output_tokens),
		   cost_yuan = cost_yuan + VALUES(cost_yuan),
		   updated_at = CURRENT_TIMESTAMP`,
		record.UserID, billMonth, record.Model,
		record.InputTokens, record.CacheHitTokens, record.CacheMissTokens,
		record.OutputTokens, cost.String(),
	)
	if err != nil {
		return fmt.Errorf("upsert bill: %w", err)
	}
	return nil
}

func isDuplicateKeyError(err error) bool {
	var mysqlErr *mysql.MySQLError
	return errors.As(err, &mysqlErr) && mysqlErr.Number == 1062
}

// ── Recharges ──

// RecordRecharge inserts a recharge record.
func (r *BillingRepo) RecordRecharge(userID int64, amountYuan decimal.Decimal, note string) (int64, error) {
	result, err := r.db.Exec(
		`INSERT INTO recharges (user_id, amount_yuan, note) VALUES (?, ?, ?)`,
		userID, amountYuan.String(), note,
	)
	if err != nil {
		return 0, fmt.Errorf("insert recharge: %w", err)
	}
	id, _ := result.LastInsertId()
	log.Printf("Recharge recorded: user=%d amount=%s id=%d", userID, amountYuan.String(), id)
	return id, nil
}

// InitBalance creates an initial recharge for a new user (¥1.34).
func (r *BillingRepo) InitBalance(userID int64) (int64, error) {
	return r.RecordRecharge(userID, decimal.NewFromFloat(1.34), "新用户初始余额")
}

// GetRecharges returns recharge history for a user, optionally filtered by date range.
func (r *BillingRepo) GetRecharges(userID int64, startDate, endDate string) ([]domain.RechargeItem, error) {
	query := `SELECT id, amount_yuan, note, created_at FROM recharges WHERE user_id = ?`
	args := []interface{}{userID}

	if startDate != "" {
		query += " AND DATE(created_at) >= ?"
		args = append(args, startDate)
	}
	if endDate != "" {
		query += " AND DATE(created_at) <= ?"
		args = append(args, endDate)
	}
	query += " ORDER BY created_at DESC"

	rows, err := r.db.Query(query, args...)
	if err != nil {
		return nil, fmt.Errorf("query recharges: %w", err)
	}
	defer rows.Close()

	var items []domain.RechargeItem
	for rows.Next() {
		var item domain.RechargeItem
		var amountStr string
		var createdAt time.Time
		if err := rows.Scan(&item.ID, &amountStr, &item.Note, &createdAt); err != nil {
			return nil, fmt.Errorf("scan recharge: %w", err)
		}
		item.AmountYuan, _ = decimal.NewFromString(amountStr)
		item.CreatedAt = createdAt
		items = append(items, item)
	}
	return items, rows.Err()
}

// ── Balance ──

// GetBalance computes total recharge, total consumption, and balance.
// Summary totals (recharge, consumption, balance) are all-time (since registration).
// model_costs and recharges are filtered by startDate/endDate.
func (r *BillingRepo) GetBalance(userID int64, startDate, endDate string) (*domain.BalanceResult, error) {
	// Total recharge — all-time.
	var totalRechargeStr string
	err := r.db.QueryRow(
		`SELECT COALESCE(SUM(amount_yuan), 0) FROM recharges WHERE user_id = ?`,
		userID,
	).Scan(&totalRechargeStr)
	if err != nil {
		return nil, fmt.Errorf("query recharge total: %w", err)
	}
	totalRecharge, _ := decimal.NewFromString(totalRechargeStr)

	// All-time total consumption (for the summary card, unfiltered).
	var allTimeConsumptionStr string
	err = r.db.QueryRow(
		`SELECT COALESCE(SUM(cost_yuan), 0) FROM bills WHERE user_id = ?`,
		userID,
	).Scan(&allTimeConsumptionStr)
	if err != nil {
		return nil, fmt.Errorf("query all-time consumption: %w", err)
	}
	allTimeConsumption, _ := decimal.NewFromString(allTimeConsumptionStr)

	balance := totalRecharge.Sub(allTimeConsumption)

	// Per-model consumption (grouped by month + model).
	query := `SELECT model, bill_month,
		COALESCE(SUM(total_input_tokens), 0),
		COALESCE(SUM(total_cache_hit_tokens), 0),
		COALESCE(SUM(total_cache_miss_tokens), 0),
		COALESCE(SUM(total_output_tokens), 0),
		COALESCE(SUM(cost_yuan), 0)
	FROM bills WHERE user_id = ?`
	args := []interface{}{userID}

	if startDate != "" {
		query += " AND bill_month >= ?"
		args = append(args, startDate[:7])
	}
	if endDate != "" {
		query += " AND bill_month <= ?"
		args = append(args, endDate[:7])
	}
	query += " GROUP BY bill_month, model ORDER BY bill_month DESC, SUM(cost_yuan) DESC"

	rows, err := r.db.Query(query, args...)
	if err != nil {
		return nil, fmt.Errorf("query model costs: %w", err)
	}
	defer rows.Close()

	var modelCosts []domain.ModelCostItem

	for rows.Next() {
		var m domain.ModelCostItem
		var costStr string
		if err := rows.Scan(&m.Model, &m.BillMonth, &m.InputTokens, &m.CacheHitTokens,
			&m.CacheMissTokens, &m.OutputTokens, &costStr); err != nil {
			return nil, fmt.Errorf("scan model cost: %w", err)
		}
		m.CostYuan, _ = decimal.NewFromString(costStr)
		modelCosts = append(modelCosts, m)
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}

	recharges, _ := r.GetRecharges(userID, startDate, endDate)

	return &domain.BalanceResult{
		TotalRecharge:    totalRecharge,
		TotalConsumption: allTimeConsumption,
		Balance:          balance,
		ModelCosts:       modelCosts,
		Recharges:        recharges,
	}, nil
}

// ── Daily Usage ──

// GetDailyUsage returns paginated daily usage breakdown.
func (r *BillingRepo) GetDailyUsage(userID int64, startDate, endDate string,
	page, pageSize int) (*domain.PaginatedResult, error) {

	db := r.db

	// Aggregate totals for the range.
	var totalInput, totalCacheHit, totalCacheMiss, totalOutput, totalTokens int
	err := db.QueryRow(
		`SELECT COALESCE(SUM(input_tokens), 0), COALESCE(SUM(cache_hit_tokens), 0),
			COALESCE(SUM(cache_miss_tokens), 0), COALESCE(SUM(output_tokens), 0),
			COALESCE(SUM(total_tokens), 0)
		 FROM token_usage_records
		 WHERE user_id = ? AND created_at >= ? AND created_at < DATE_ADD(?, INTERVAL 1 DAY)`,
		userID, startDate, endDate,
	).Scan(&totalInput, &totalCacheHit, &totalCacheMiss, &totalOutput, &totalTokens)
	if err != nil {
		return nil, fmt.Errorf("query usage totals: %w", err)
	}

	// Compute overall cost.
	costRows, err := db.Query(
		`SELECT model,
			COALESCE(SUM(cache_hit_tokens), 0),
			COALESCE(SUM(cache_miss_tokens), 0),
			COALESCE(SUM(output_tokens), 0)
		 FROM token_usage_records
		 WHERE user_id = ? AND created_at >= ? AND created_at < DATE_ADD(?, INTERVAL 1 DAY)
		 GROUP BY model`,
		userID, startDate, endDate,
	)
	if err != nil {
		return nil, fmt.Errorf("query cost breakdown: %w", err)
	}
	defer costRows.Close()

	totalCost := decimal.Zero
	for costRows.Next() {
		var model string
		var cacheHit, cacheMiss, output int
		if err := costRows.Scan(&model, &cacheHit, &cacheMiss, &output); err != nil {
			continue
		}
		totalCost = totalCost.Add(domain.CalculateCost(model, cacheHit, cacheMiss, output))
	}

	// Count distinct groups.
	var totalCount int
	err = db.QueryRow(
		`SELECT COUNT(*) FROM (
			SELECT 1 FROM token_usage_records
			WHERE user_id = ? AND created_at >= ?
			AND created_at < DATE_ADD(?, INTERVAL 1 DAY)
			GROUP BY DATE(created_at), model, subsystem
		) t`,
		userID, startDate, endDate,
	).Scan(&totalCount)
	if err != nil {
		return nil, fmt.Errorf("count daily usage: %w", err)
	}

	// Paginated data.
	offset := (page - 1) * pageSize
	rows2, err := db.Query(
		`SELECT DATE(created_at) as date, model, subsystem,
			SUM(input_tokens), SUM(cache_hit_tokens), SUM(cache_miss_tokens),
			SUM(output_tokens), SUM(total_tokens)
		 FROM token_usage_records
		 WHERE user_id = ? AND created_at >= ?
		 AND created_at < DATE_ADD(?, INTERVAL 1 DAY)
		 GROUP BY DATE(created_at), model, subsystem
		 ORDER BY date DESC, model, subsystem
		 LIMIT ? OFFSET ?`,
		userID, startDate, endDate, pageSize, offset,
	)
	if err != nil {
		return nil, fmt.Errorf("query daily usage page: %w", err)
	}
	defer rows2.Close()

	var items []domain.UsageDailyItem
	for rows2.Next() {
		var item domain.UsageDailyItem
		var dateStr string
		if err := rows2.Scan(&dateStr, &item.Model, &item.Subsystem,
			&item.TotalInputTokens, &item.TotalCacheHitTokens, &item.TotalCacheMissTokens,
			&item.TotalOutputTokens, &item.TotalTokens); err != nil {
			return nil, fmt.Errorf("scan daily item: %w", err)
		}
		item.Date = dateStr
		item.CostYuan = domain.CalculateCost(item.Model, item.TotalCacheHitTokens, item.TotalCacheMissTokens, item.TotalOutputTokens)
		items = append(items, item)
	}

	return &domain.PaginatedResult{
		Items:                items,
		TotalCount:           totalCount,
		Page:                 page,
		PageSize:             pageSize,
		TotalTokens:          totalTokens,
		TotalInputTokens:     totalInput,
		TotalCacheHitTokens:  totalCacheHit,
		TotalCacheMissTokens: totalCacheMiss,
		TotalOutputTokens:    totalOutput,
		TotalCost:            totalCost,
	}, rows2.Err()
}

// ── Bills ──

// GetBills returns paginated monthly bills.
func (r *BillingRepo) GetBills(userID int64, startDate, endDate string,
	page, pageSize int) (*domain.PaginatedResult, error) {

	where := "user_id = ?"
	args := []interface{}{userID}
	if startDate != "" {
		where += " AND bill_month >= ?"
		args = append(args, startDate[:7])
	}
	if endDate != "" {
		where += " AND bill_month <= ?"
		args = append(args, endDate[:7])
	}

	// Count.
	var totalCount int
	countQuery := fmt.Sprintf("SELECT COUNT(*) FROM bills WHERE %s", where)
	if err := r.db.QueryRow(countQuery, args...).Scan(&totalCount); err != nil {
		return nil, fmt.Errorf("count bills: %w", err)
	}

	// Aggregates.
	var totalInput, totalCacheHit, totalCacheMiss, totalOutput int
	var totalCostStr string
	aggQuery := fmt.Sprintf(
		`SELECT COALESCE(SUM(total_input_tokens), 0), COALESCE(SUM(total_cache_hit_tokens), 0),
			COALESCE(SUM(total_cache_miss_tokens), 0), COALESCE(SUM(total_output_tokens), 0),
			COALESCE(SUM(cost_yuan), 0) FROM bills WHERE %s`, where)
	if err := r.db.QueryRow(aggQuery, args...).Scan(&totalInput, &totalCacheHit, &totalCacheMiss, &totalOutput, &totalCostStr); err != nil {
		return nil, fmt.Errorf("agg bills: %w", err)
	}
	totalCost, _ := decimal.NewFromString(totalCostStr)

	// Paginated data.
	offset := (page - 1) * pageSize
	dataQuery := fmt.Sprintf(
		`SELECT model, bill_month, total_input_tokens, total_cache_hit_tokens,
			total_cache_miss_tokens, total_output_tokens, cost_yuan
		 FROM bills WHERE %s ORDER BY bill_month DESC, model LIMIT ? OFFSET ?`, where)
	args = append(args, pageSize, offset)

	rows, err := r.db.Query(dataQuery, args...)
	if err != nil {
		return nil, fmt.Errorf("query bills: %w", err)
	}
	defer rows.Close()

	var items []domain.BillItem
	for rows.Next() {
		var item domain.BillItem
		var costStr string
		if err := rows.Scan(&item.Model, &item.BillMonth, &item.TotalInputTokens,
			&item.TotalCacheHitTokens, &item.TotalCacheMissTokens,
			&item.TotalOutputTokens, &costStr); err != nil {
			return nil, fmt.Errorf("scan bill: %w", err)
		}
		item.CostYuan, _ = decimal.NewFromString(costStr)
		items = append(items, item)
	}

	return &domain.PaginatedResult{
		Items:                items,
		TotalCount:           totalCount,
		Page:                 page,
		PageSize:             pageSize,
		TotalInputTokens:     totalInput,
		TotalCacheHitTokens:  totalCacheHit,
		TotalCacheMissTokens: totalCacheMiss,
		TotalOutputTokens:    totalOutput,
		TotalCost:            totalCost,
	}, rows.Err()
}

// CheckBalance returns the current balance for a user (without full breakdown).
func (r *BillingRepo) CheckBalance(userID int64) (decimal.Decimal, error) {
	result, err := r.GetBalance(userID, "", "")
	if err != nil {
		return decimal.Zero, err
	}
	return result.Balance, nil
}
