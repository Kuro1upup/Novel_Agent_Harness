package service

import (
	"context"
	"errors"
	"testing"

	"github.com/redis/go-redis/v9"
)

type recordedUsage struct {
	eventID      string
	userID       int64
	model        string
	subsystem    string
	inputTokens  int
	outputTokens int
}

type fakeUsageRecorder struct {
	records []recordedUsage
	err     error
}

func (f *fakeUsageRecorder) RecordUsageEvent(
	eventID string,
	userID int64,
	model string,
	subsystem string,
	inputTokens int,
	cacheHitTokens int,
	cacheMissTokens int,
	outputTokens int,
) (int64, error) {
	if f.err != nil {
		return 0, f.err
	}
	f.records = append(f.records, recordedUsage{
		eventID:      eventID,
		userID:       userID,
		model:        model,
		subsystem:    subsystem,
		inputTokens:  inputTokens,
		outputTokens: outputTokens,
	})
	return int64(len(f.records)), nil
}

func TestUsageConsumerRecordsStreamIDAndAcknowledgesSuccess(t *testing.T) {
	recorder := &fakeUsageRecorder{}
	consumer := NewUsageConsumer(nil, recorder)
	acknowledged := []string{}
	consumer.processMessages(
		context.Background(),
		[]redis.XMessage{{
			ID: "1710000000000-0",
			Values: map[string]interface{}{
				"data": `{"user_id":42,"model":"deepseek","subsystem":"novel_harness","input_tokens":12,"output_tokens":8}`,
			},
		}},
		func(messageID string) error {
			acknowledged = append(acknowledged, messageID)
			return nil
		},
	)

	if len(recorder.records) != 1 {
		t.Fatalf("recorded %d events, expected 1", len(recorder.records))
	}
	record := recorder.records[0]
	if record.eventID != streamKey+":1710000000000-0" {
		t.Fatalf("unexpected event ID: %s", record.eventID)
	}
	if record.userID != 42 || record.inputTokens != 12 || record.outputTokens != 8 {
		t.Fatalf("unexpected usage record: %#v", record)
	}
	if len(acknowledged) != 1 || acknowledged[0] != "1710000000000-0" {
		t.Fatalf("unexpected acknowledgements: %#v", acknowledged)
	}
}

func TestUsageConsumerLeavesFailedMessagePending(t *testing.T) {
	recorder := &fakeUsageRecorder{err: errors.New("database unavailable")}
	consumer := NewUsageConsumer(nil, recorder)
	acknowledged := 0
	consumer.processMessages(
		context.Background(),
		[]redis.XMessage{{
			ID: "1710000000000-1",
			Values: map[string]interface{}{
				"data": `{"user_id":42,"model":"deepseek","subsystem":"novel_harness","input_tokens":12,"output_tokens":8}`,
			},
		}},
		func(string) error {
			acknowledged++
			return nil
		},
	)

	if acknowledged != 0 {
		t.Fatalf("failed event was acknowledged %d times", acknowledged)
	}
}

func TestUsageConsumerRejectsMalformedEvent(t *testing.T) {
	consumer := NewUsageConsumer(nil, &fakeUsageRecorder{})
	err := consumer.processMessage(context.Background(), redis.XMessage{
		ID:     "1710000000000-2",
		Values: map[string]interface{}{"data": `{"user_id":0}`},
	})
	if err == nil {
		t.Fatal("expected malformed event to fail")
	}
}
