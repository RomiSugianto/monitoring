package models

import (
	"sync"
	"time"
)

type LogEntry struct {
	Timestamp  time.Time `json:"timestamp"`
	Level      string    `json:"level"`   // info, error, warning
	Message    string    `json:"message"`
	Status     string    `json:"status"`   // success, failed, pending
	StatusCode int       `json:"status_code"`
	Service    string    `json:"service"`
}

type CustomMetric struct {
	Name        string            `json:"name"`
	Labels      map[string]string `json:"labels"`
	Value       float64           `json:"value"`
	ValueType   string            `json:"type"` // counter, gauge
	MinValue    float64           `json:"min_value,omitempty"`
	MaxValue    float64           `json:"max_value,omitempty"`
	Increment   float64           `json:"increment,omitempty"`   // For counters: amount to increment per interval
	IntervalSec int               `json:"interval_sec,omitempty"` // For counters: how often to increment (seconds)
	Active      bool              `json:"active"`                // Whether this metric is actively updating
}

type ServiceState struct {
	Mu                       sync.RWMutex
	PrometheusBroadcastEnabled bool      `json:"prometheus_broadcast"`
	LokiSendEnabled           bool      `json:"loki_send"`
	LastLogEntry              LogEntry  `json:"last_log_entry"`
	LogHistory                []LogEntry `json:"log_history"`
	CustomMetrics             []CustomMetric `json:"custom_metrics"`
}

var State = &ServiceState{
	PrometheusBroadcastEnabled: true,
	LokiSendEnabled:           true,
	LogHistory:                make([]LogEntry, 0, 100),
	CustomMetrics:             make([]CustomMetric, 0),
}

func (s *ServiceState) AddLog(entry LogEntry) {
	s.Mu.Lock()
	defer s.Mu.Unlock()

	s.LastLogEntry = entry
	s.LogHistory = append([]LogEntry{entry}, s.LogHistory...)
	if len(s.LogHistory) > 100 {
		s.LogHistory = s.LogHistory[:100]
	}
}

func (s *ServiceState) AddOrUpdateCustomMetric(metric CustomMetric) {
	s.Mu.Lock()
	defer s.Mu.Unlock()

	for i, m := range s.CustomMetrics {
		if m.Name == metric.Name {
			s.CustomMetrics[i] = metric
			return
		}
	}
	s.CustomMetrics = append(s.CustomMetrics, metric)
}

func (s *ServiceState) GetLogs() []LogEntry {
	s.Mu.RLock()
	defer s.Mu.RUnlock()

	logs := make([]LogEntry, len(s.LogHistory))
	copy(logs, s.LogHistory)
	return logs
}

func (s *ServiceState) GetMetrics() []CustomMetric {
	s.Mu.RLock()
	defer s.Mu.RUnlock()

	metrics := make([]CustomMetric, len(s.CustomMetrics))
	copy(metrics, s.CustomMetrics)
	return metrics
}

func (s *ServiceState) GetToggles() map[string]bool {
	s.Mu.RLock()
	defer s.Mu.RUnlock()

	return map[string]bool{
		"prometheus_broadcast": s.PrometheusBroadcastEnabled,
		"loki_send":            s.LokiSendEnabled,
	}
}

func (s *ServiceState) SetToggle(name string, value bool) {
	s.Mu.Lock()
	defer s.Mu.Unlock()

	switch name {
	case "prometheus_broadcast":
		s.PrometheusBroadcastEnabled = value
	case "loki_send":
		s.LokiSendEnabled = value
	}
}

type StateSnapshot struct {
	PrometheusBroadcastEnabled bool           `json:"prometheus_broadcast"`
	LokiSendEnabled           bool           `json:"loki_send"`
	LastLogEntry              LogEntry       `json:"last_log_entry"`
	LogHistory                []LogEntry     `json:"log_history"`
	CustomMetrics             []CustomMetric `json:"custom_metrics"`
	Toggles                   map[string]bool `json:"toggles"`
}

func (s *ServiceState) GetState() StateSnapshot {
	s.Mu.RLock()
	defer s.Mu.RUnlock()

	logs := make([]LogEntry, len(s.LogHistory))
	copy(logs, s.LogHistory)

	metricsList := make([]CustomMetric, len(s.CustomMetrics))
	copy(metricsList, s.CustomMetrics)

	return StateSnapshot{
		PrometheusBroadcastEnabled: s.PrometheusBroadcastEnabled,
		LokiSendEnabled:           s.LokiSendEnabled,
		LastLogEntry:              s.LastLogEntry,
		LogHistory:                logs,
		CustomMetrics:             metricsList,
		Toggles: map[string]bool{
			"prometheus_broadcast": s.PrometheusBroadcastEnabled,
			"loki_send":            s.LokiSendEnabled,
		},
	}
}
