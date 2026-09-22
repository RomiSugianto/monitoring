package internal

import (
	"fmt"
	"net/http"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/romi/mocktail/internal/config"
	"github.com/romi/mocktail/internal/loki"
	"github.com/romi/mocktail/internal/metrics"
	"github.com/romi/mocktail/internal/models"
)

type Handler struct {
	LokiClient *loki.LokiClient
	Config     *config.Config
}

func NewHandler(lokiClient *loki.LokiClient, cfg *config.Config) *Handler {
	return &Handler{
		LokiClient: lokiClient,
		Config:     cfg,
	}
}

// ServeUI renders the main HTML page
func (h *Handler) ServeUI(c *gin.Context) {
	snapshot := models.State.GetState()
	c.HTML(http.StatusOK, "index.html", gin.H{
		"State":  snapshot,
		"Config": h.Config,
	})
}

// GenerateLog handles POST requests to generate and process log entries
func (h *Handler) GenerateLog(c *gin.Context) {
	var req struct {
		Status     string `json:"status"`
		Level      string `json:"level"`
		Message    string `json:"message"`
		StatusCode int    `json:"status_code"`
	}

	if err := c.ShouldBindJSON(&req); err != nil {
		status := c.PostForm("status")
		level := c.PostForm("level")
		message := c.PostForm("message")

		if status == "" {
			status = "success"
		}
		if level == "" {
			level = "info"
		}
		if message == "" {
			message = "Request processed"
		}

		req.Status = status
		req.Level = level
		req.Message = message

		codeStr := c.PostForm("status_code")
		if codeStr != "" {
			fmt.Sscanf(codeStr, "%d", &req.StatusCode)
		}
	}

	if req.Status == "" {
		req.Status = "success"
	}
	if req.Level == "" {
		req.Level = "info"
	}
	if req.Message == "" {
		req.Message = "Request processed"
	}
	if req.StatusCode == 0 {
		if req.Status == "success" {
			req.StatusCode = http.StatusOK
		} else {
			req.StatusCode = http.StatusInternalServerError
		}
	}

	entry := models.LogEntry{
		Timestamp:  time.Now().UTC(),
		Level:      req.Level,
		Message:    req.Message,
		Status:     req.Status,
		StatusCode: req.StatusCode,
		Service:    h.Config.ServiceName,
	}

	broadcast := false
	lokiSent := false

	if models.State.PrometheusBroadcastEnabled {
		metrics.RecordLog(req.Level, req.Status, h.Config.ServiceName)
		broadcast = true
	}

	if models.State.LokiSendEnabled {
		if err := h.LokiClient.PushLog(entry); err == nil {
			lokiSent = true
		}
	}

	models.State.AddLog(entry)

	c.JSON(http.StatusOK, gin.H{
		"message":   "log generated",
		"broadcast": broadcast,
		"loki":      lokiSent,
		"entry":     entry,
	})
}

// SetToggle handles POST requests to update toggle settings
func (h *Handler) SetToggle(c *gin.Context) {
	var req struct {
		Name  string `json:"name"`
		Value bool   `json:"value"`
	}

	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid request"})
		return
	}

	models.State.SetToggle(req.Name, req.Value)

	c.JSON(http.StatusOK, gin.H{
		"message": fmt.Sprintf("toggle %s set to %v", req.Name, req.Value),
		"toggle":  req.Name,
		"value":   req.Value,
	})
}

// AddCustomMetric handles POST requests to add or update custom metrics
func (h *Handler) AddCustomMetric(c *gin.Context) {
	var req struct {
		Name        string            `json:"name"`
		Labels      map[string]string `json:"labels"`
		Value       float64           `json:"value"`
		ValueType   string            `json:"type"`
		MinValue    float64           `json:"min_value,omitempty"`
		MaxValue    float64           `json:"max_value,omitempty"`
		Increment   float64           `json:"increment,omitempty"`
		IntervalSec int               `json:"interval_sec,omitempty"`
		Active      bool              `json:"active,omitempty"`
	}

	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid request"})
		return
	}

	if req.ValueType == "" {
		req.ValueType = "gauge"
	}

	// Set default label values
	if req.Labels == nil {
		req.Labels = map[string]string{}
	}
	if _, ok := req.Labels["instance"]; !ok {
		req.Labels["instance"] = h.Config.Instance
	}
	if _, ok := req.Labels["ip_address"]; !ok {
		req.Labels["ip_address"] = h.Config.IPAddress
	}
	if _, ok := req.Labels["on_part_of"]; !ok {
		req.Labels["on_part_of"] = h.Config.ServiceName
	}

	// Set defaults for counter metrics
	if req.ValueType == "counter" {
		if req.Increment == 0 {
			req.Increment = 1
		}
		if req.IntervalSec == 0 {
			req.IntervalSec = 10
		}
	}

	// Set defaults for gauge metrics
	if req.ValueType == "gauge" {
		if req.MinValue == 0 && req.MaxValue == 0 {
			req.MaxValue = 100
		}
	}

	metric := models.CustomMetric{
		Name:        req.Name,
		Labels:      req.Labels,
		Value:       req.Value,
		ValueType:   req.ValueType,
		MinValue:    req.MinValue,
		MaxValue:    req.MaxValue,
		Increment:   req.Increment,
		IntervalSec: req.IntervalSec,
		Active:      req.Active,
	}

	models.State.AddOrUpdateCustomMetric(metric)

	// Convert labels map to sorted slice for registration
	labelNames := make([]string, 0, len(req.Labels))
	for k := range req.Labels {
		labelNames = append(labelNames, k)
	}

	// Register the metric in Prometheus
	if err := metrics.RegisterCustomMetric(req.Name, req.ValueType, labelNames); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": fmt.Sprintf("failed to register metric: %v", err)})
		return
	}

	// Set the initial value
	if err := metrics.SetCustomMetric(req.Name, req.ValueType, req.Labels, req.Value); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": fmt.Sprintf("failed to set metric: %v", err)})
		return
	}

	// Start background updater if metric is active or has interval set
	if req.Active || (req.ValueType == "gauge" && req.MinValue != req.MaxValue) || (req.ValueType == "counter" && req.Increment > 0) {
		metrics.StartBackgroundUpdater(
			req.Name,
			req.ValueType,
			req.Labels,
			req.MinValue,
			req.MaxValue,
			req.Increment,
			req.IntervalSec,
		)
	}

	c.JSON(http.StatusOK, gin.H{
		"message": "metric added/updated",
		"metric":  metric,
	})
}

// GetStateHandler returns the current service state as JSON
func (h *Handler) GetStateHandler(c *gin.Context) {
	c.JSON(http.StatusOK, models.State.GetState())
}

// GetMetricsHandler returns custom metrics as JSON
func (h *Handler) GetMetricsHandler(c *gin.Context) {
	c.JSON(http.StatusOK, gin.H{
		"metrics": models.State.GetMetrics(),
	})
}

// HealthCheck provides a simple health endpoint
func (h *Handler) HealthCheck(c *gin.Context) {
	c.JSON(http.StatusOK, gin.H{"status": "ok"})
}
