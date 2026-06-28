package service

import (
	"context"
	"encoding/json"
	"log"
	"time"

	"github.com/redis/go-redis/v9"

	"second-brain/billing/internal/domain"
)

const (
	streamKey        = "llm:usage:events"
	consumerGroup    = "billing-consumers"
	consumerName     = "billing-service-1"
	redisReadTimeout = 5 * time.Second
)

// UsageConsumer listens to Redis Streams for LLM usage events and records them.
type UsageConsumer struct {
	redisClient *redis.Client
	billingSvc  *BillingService
}

// NewUsageConsumer creates a new UsageConsumer.
func NewUsageConsumer(redisClient *redis.Client, billingSvc *BillingService) *UsageConsumer {
	return &UsageConsumer{
		redisClient: redisClient,
		billingSvc:  billingSvc,
	}
}

// Start begins consuming from the Redis stream in a background goroutine.
// It creates the consumer group if it doesn't exist.
func (c *UsageConsumer) Start(ctx context.Context) {
	// Create consumer group (idempotent — ignore error if it already exists).
	err := c.redisClient.XGroupCreateMkStream(ctx, streamKey, consumerGroup, "0").Err()
	if err != nil && !isConsumerGroupExistsErr(err) {
		log.Printf("WARNING: Failed to create Redis consumer group: %v", err)
	}

	go c.consumeLoop(ctx)
	log.Printf("Redis usage consumer started on stream=%s group=%s", streamKey, consumerGroup)
}

func (c *UsageConsumer) consumeLoop(ctx context.Context) {
	for {
		select {
		case <-ctx.Done():
			log.Println("Usage consumer shutting down")
			return
		default:
			c.readAndProcess(ctx)
			time.Sleep(100 * time.Millisecond)
		}
	}
}

func (c *UsageConsumer) readAndProcess(ctx context.Context) {
	entries, err := c.redisClient.XReadGroup(ctx, &redis.XReadGroupArgs{
		Group:    consumerGroup,
		Consumer: consumerName,
		Streams:  []string{streamKey, ">"},
		Count:    10,
		Block:    redisReadTimeout,
	}).Result()

	if err != nil {
		if err == redis.Nil {
			return // No messages.
		}
		log.Printf("WARNING: Redis XReadGroup error: %v", err)
		return
	}

	for _, stream := range entries {
		for _, msg := range stream.Messages {
			if err := c.processMessage(ctx, msg); err != nil {
				log.Printf("WARNING: Failed to process usage event: %v", err)
			}
			// Ack the message regardless of processing result (don't retry forever).
			c.redisClient.XAck(ctx, streamKey, consumerGroup, msg.ID)
		}
	}
}

func (c *UsageConsumer) processMessage(ctx context.Context, msg redis.XMessage) error {
	// The Python backend stores events as: XADD stream {"data": "<json-string>"}
	// So msg.Values["data"] is a JSON string, not another map.
	data, ok := msg.Values["data"]
	if ok {
		// data is already the JSON string — use it directly.
		if dataStr, ok := data.(string); ok {
			return c.recordFromJSON([]byte(dataStr))
		}
		// Fallback: marshal the value if it's not a plain string.
		jsonBytes, err := json.Marshal(data)
		if err != nil {
			return nil
		}
		return c.recordFromJSON(jsonBytes)
	}

	// No "data" key — try parsing the entire message body as JSON.
	jsonBytes, err := json.Marshal(msg.Values)
	if err != nil {
		return nil
	}
	return c.recordFromJSON(jsonBytes)
}

func (c *UsageConsumer) recordFromJSON(data []byte) error {
	var event domain.LLMUsageEvent
	if err := json.Unmarshal(data, &event); err != nil {
		// Try alternate format: flat JSON with all token fields at top level.
		var flat struct {
			UserID          int64  `json:"user_id"`
			Model           string `json:"model"`
			Subsystem       string `json:"subsystem"`
			InputTokens     int    `json:"input_tokens"`
			CacheHitTokens  int    `json:"cache_hit_tokens"`
			CacheMissTokens int    `json:"cache_miss_tokens"`
			OutputTokens    int    `json:"output_tokens"`
			TotalTokens     int    `json:"total_tokens"`
		}
		if err := json.Unmarshal(data, &flat); err != nil {
			log.Printf("WARNING: Failed to parse usage event JSON: %v (data=%s)", err, string(data))
			return nil
		}
		event = domain.LLMUsageEvent{
			UserID:          flat.UserID,
			Model:           flat.Model,
			Subsystem:       flat.Subsystem,
			InputTokens:     flat.InputTokens,
			CacheHitTokens:  flat.CacheHitTokens,
			CacheMissTokens: flat.CacheMissTokens,
			OutputTokens:    flat.OutputTokens,
			TotalTokens:     flat.TotalTokens,
		}
	}

	if event.UserID == 0 {
		return nil // Invalid event, skip.
	}

	_, err := c.billingSvc.RecordUsage(
		event.UserID, event.Model, event.Subsystem,
		event.InputTokens, event.CacheHitTokens, event.CacheMissTokens, event.OutputTokens,
	)
	return err
}

// isConsumerGroupExistsErr checks if the Redis error is "BUSYGROUP Consumer Group name already exists".
func isConsumerGroupExistsErr(err error) bool {
	if err == nil {
		return false
	}
	return contains(err.Error(), "BUSYGROUP")
}

func contains(s, substr string) bool {
	for i := 0; i <= len(s)-len(substr); i++ {
		if s[i:i+len(substr)] == substr {
			return true
		}
	}
	return false
}
