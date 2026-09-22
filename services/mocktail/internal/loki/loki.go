package loki

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"time"

	"github.com/romi/mocktail/internal/models"
)

type LokiClient struct {
	baseURL    string
	httpClient *http.Client
}

func NewClient(baseURL string) *LokiClient {
	return &LokiClient{
		baseURL: baseURL,
		httpClient: &http.Client{
			Timeout: 10 * time.Second,
		},
	}
}

type lokiStream struct {
	Stream map[string]string `json:"stream"`
	Values [][2]string       `json:"values"`
}

type lokiPushRequest struct {
	Streams []lokiStream `json:"streams"`
}

func (c *LokiClient) PushLog(entry models.LogEntry) error {
	return c.PushLogs([]models.LogEntry{entry})
}

func (c *LokiClient) PushLogs(entries []models.LogEntry) error {
	if len(entries) == 0 {
		return nil
	}

	streams := make([]lokiStream, 0, len(entries))
	for _, entry := range entries {
		logJSON, err := json.Marshal(entry)
		if err != nil {
			return fmt.Errorf("failed to marshal log entry: %w", err)
		}

		stream := lokiStream{
			Stream: map[string]string{
				"level":   entry.Level,
				"status":  entry.Status,
				"service": entry.Service,
			},
			Values: [][2]string{
				{
					fmt.Sprintf("%d", entry.Timestamp.UnixNano()),
					string(logJSON),
				},
			},
		}
		streams = append(streams, stream)
	}

	reqBody := lokiPushRequest{
		Streams: streams,
	}

	body, err := json.Marshal(reqBody)
	if err != nil {
		return fmt.Errorf("failed to marshal request: %w", err)
	}

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	req, err := http.NewRequestWithContext(ctx, "POST", c.baseURL+"/loki/api/v1/push", bytes.NewReader(body))
	if err != nil {
		return fmt.Errorf("failed to create request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return fmt.Errorf("failed to send request to Loki: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode >= 300 {
		respBody, _ := io.ReadAll(resp.Body)
		return fmt.Errorf("loki returned status %d: %s", resp.StatusCode, string(respBody))
	}

	return nil
}
