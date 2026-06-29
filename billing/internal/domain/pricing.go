package domain

import "github.com/shopspring/decimal"

// Subsystem constants (matching Python Subsystem enum).
const (
	SubsystemSQLCopilot      = "sql_copilot"
	SubsystemKnowledgeBase   = "knowledge_base"
	SubsystemSmartTranslator = "smart_translator"
	SubsystemSmartGalgame    = "smart_galgame"
	SubsystemNovelHarness    = "novel_harness"
)

// ModelPricing holds per-million-token pricing for a model.
type ModelPricing struct {
	Model                         string
	InputCacheHitPricePerMillion  decimal.Decimal // ¥ per million tokens
	InputCacheMissPricePerMillion decimal.Decimal
	OutputPricePerMillion         decimal.Decimal
}

// PricingTable maps model names to their pricing.
// Prices match Python's PRICING_TABLE exactly.
var PricingTable = map[string]ModelPricing{
	"deepseek-v4-flash": {
		Model:                         "deepseek-v4-flash",
		InputCacheHitPricePerMillion:  decimal.NewFromFloat(0.2),
		InputCacheMissPricePerMillion: decimal.NewFromFloat(10.0),
		OutputPricePerMillion:         decimal.NewFromFloat(20.0),
	},
	"deepseek-chat": {
		Model:                         "deepseek-chat",
		InputCacheHitPricePerMillion:  decimal.NewFromFloat(0.2),
		InputCacheMissPricePerMillion: decimal.NewFromFloat(10.0),
		OutputPricePerMillion:         decimal.NewFromFloat(20.0),
	},
	"deepseek-reasoner": {
		Model:                         "deepseek-reasoner",
		InputCacheHitPricePerMillion:  decimal.NewFromFloat(0.2),
		InputCacheMissPricePerMillion: decimal.NewFromFloat(10.0),
		OutputPricePerMillion:         decimal.NewFromFloat(20.0),
	},
	"deepseek-v4-pro": {
		Model:                         "deepseek-v4-pro",
		InputCacheHitPricePerMillion:  decimal.NewFromFloat(0.25),
		InputCacheMissPricePerMillion: decimal.NewFromFloat(30.0),
		OutputPricePerMillion:         decimal.NewFromFloat(60.0),
	},
}

// CalculateCost computes the cost in yuan from token counts.
func CalculateCost(model string, cacheHit, cacheMiss, output int) decimal.Decimal {
	pricing, ok := PricingTable[model]
	if !ok {
		return decimal.Zero
	}

	oneMillion := decimal.NewFromInt(1_000_000)
	cacheHitDec := decimal.NewFromInt(int64(cacheHit))
	cacheMissDec := decimal.NewFromInt(int64(cacheMiss))
	outputDec := decimal.NewFromInt(int64(output))

	cost := decimal.Zero
	cost = cost.Add(cacheHitDec.Div(oneMillion).Mul(pricing.InputCacheHitPricePerMillion))
	cost = cost.Add(cacheMissDec.Div(oneMillion).Mul(pricing.InputCacheMissPricePerMillion))
	cost = cost.Add(outputDec.Div(oneMillion).Mul(pricing.OutputPricePerMillion))

	return cost
}
