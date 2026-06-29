package service

import (
	"context"
	"encoding/json"
	"fmt"
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
	billingSvc  usageRecorder
}

type usageRecorder interface {
	RecordUsageEvent(
		eventID string,
		userID int64,
		model string,
		subsystem string,
		inputTokens int,
		cacheHitTokens int,
		cacheMissTokens int,
		outputTokens int,
	) (int64, error)
}

// NewUsageConsumer creates a new UsageConsumer.
func NewUsageConsumer(redisClient *redis.Client, billingSvc usageRecorder) *UsageConsumer {
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
	// Retry messages already delivered to this stable local consumer before reading new ones.
	c.readMessages(ctx, "0", -1)
	c.readMessages(ctx, ">", redisReadTimeout)
}

func (c *UsageConsumer) readMessages(ctx context.Context, start string, block time.Duration) {
	entries, err := c.redisClient.XReadGroup(ctx, &redis.XReadGroupArgs{
		Group:    consumerGroup,
		Consumer: consumerName,
		Streams:  []string{streamKey, start},
		Count:    10,
		Block:    block,
	}).Result()

	if err != nil {
		if err == redis.Nil {
			return // No messages.
		}
		log.Printf("WARNING: Redis XReadGroup error: %v", err)
		return
	}

	for _, stream := range entries {
		c.processMessages(ctx, stream.Messages, func(messageID string) error {
			return c.redisClient.XAck(ctx, streamKey, consumerGroup, messageID).Err()
		})
	}
}

func (c *UsageConsumer) processMessages(
	ctx context.Context,
	messages []redis.XMessage,
	acknowledge func(string) error,
) {
	for _, msg := range messages {
		if err := c.processMessage(ctx, msg); err != nil {
			log.Printf(
				"WARNING: Failed to process usage event id=%s; left pending for retry: %v",
				msg.ID,
				err,
			)
			continue
		}
		if err := acknowledge(msg.ID); err != nil {
			log.Printf("WARNING: Failed to ACK usage event id=%s: %v", msg.ID, err)
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
			return c.recordFromJSON(msg.ID, []byte(dataStr))
		}
		if dataBytes, ok := data.([]byte); ok {
			return c.recordFromJSON(msg.ID, dataBytes)
		}
		return fmt.Errorf("usage event data has unsupported type %T", data)
	}

	// No "data" key — try parsing the entire message body as JSON.
	jsonBytes, err := json.Marshal(msg.Values)
	if err != nil {
		return fmt.Errorf("marshal usage event: %w", err)
	}
	return c.recordFromJSON(msg.ID, jsonBytes)
}

func (c *UsageConsumer) recordFromJSON(messageID string, data []byte) error {
	var event domain.LLMUsageEvent
	if err := json.Unmarshal(data, &event); err != nil {
		return fmt.Errorf("parse usage event JSON: %w", err)
	}

	if event.UserID <= 0 {
		return fmt.Errorf("usage event has invalid user_id")
	}
	if event.Model == "" || event.Subsystem == "" {
		return fmt.Errorf("usage event model and subsystem are required")
	}
	if event.InputTokens < 0 || event.CacheHitTokens < 0 || event.CacheMissTokens < 0 ||
		event.OutputTokens < 0 {
		return fmt.Errorf("usage event token counts must not be negative")
	}

	_, err := c.billingSvc.RecordUsageEvent(
		streamKey+":"+messageID,
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
