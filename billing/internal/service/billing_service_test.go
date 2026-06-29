package service

import (
	"errors"
	"testing"
)

func TestRecordUsageEventRejectsInvalidPayload(t *testing.T) {
	svc := NewBillingService(nil)
	cases := []struct {
		name         string
		userID       int64
		model        string
		subsystem    string
		inputTokens  int
		outputTokens int
	}{
		{name: "missing user", userID: 0, model: "deepseek", subsystem: "novel"},
		{name: "missing model", userID: 1, model: "", subsystem: "novel"},
		{name: "missing subsystem", userID: 1, model: "deepseek", subsystem: ""},
		{name: "negative input", userID: 1, model: "deepseek", subsystem: "novel", inputTokens: -1},
		{name: "negative output", userID: 1, model: "deepseek", subsystem: "novel", outputTokens: -1},
	}

	for _, item := range cases {
		t.Run(item.name, func(t *testing.T) {
			_, err := svc.RecordUsageEvent(
				"event",
				item.userID,
				item.model,
				item.subsystem,
				item.inputTokens,
				0,
				0,
				item.outputTokens,
			)
			if !errors.Is(err, ErrInvalidBillingRequest) {
				t.Fatalf("expected invalid billing request, got %v", err)
			}
		})
	}
}

func TestInitBalanceRejectsInvalidUserID(t *testing.T) {
	svc := NewBillingService(nil)
	_, err := svc.InitBalance(0)
	if !errors.Is(err, ErrInvalidBillingRequest) {
		t.Fatalf("expected invalid billing request, got %v", err)
	}
}
