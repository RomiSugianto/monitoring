package main

import (
	"fmt"
	"log"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/prometheus/client_golang/prometheus/promhttp"
	"github.com/romi/mocktail/internal"
	"github.com/romi/mocktail/internal/config"
	"github.com/romi/mocktail/internal/loki"
	"github.com/romi/mocktail/internal/metrics"
)

func main() {
	// Load configuration
	cfg := config.Load()
	log.Printf("Starting mocktail service on port %s", cfg.HTTPPort)
	log.Printf("Loki URL: %s", cfg.LokiURL)
	log.Printf("Service Name: %s", cfg.ServiceName)

	// Initialize metrics
	metrics.RegisterMetrics()

	// Create Loki client
	lokiClient := loki.NewClient(cfg.LokiURL)

	// Initialize handler
	h := internal.NewHandler(lokiClient, cfg)

	// Set up Gin router
	router := gin.Default()

	// Serve static files
	router.Static("/static", "./web/static")

	// Load templates
	router.LoadHTMLFiles("web/templates/index.html")

	// Middleware to record request duration
	router.Use(func(c *gin.Context) {
		start := time.Now()
		c.Next()
		duration := time.Since(start).Seconds()
		metrics.RecordRequest(c.Request.Method, c.FullPath(), duration)
	})

	// Routes
	router.GET("/", h.ServeUI)
	router.POST("/api/log", h.GenerateLog)
	router.POST("/api/toggle", h.SetToggle)
	router.POST("/api/metrics/custom", h.AddCustomMetric)
	router.GET("/api/state", h.GetStateHandler)
	router.GET("/api/metrics", h.GetMetricsHandler)
	router.GET("/healthz", h.HealthCheck)
	router.GET("/metrics", gin.WrapH(promhttp.Handler()))

	// Start server
	addr := fmt.Sprintf(":%s", cfg.HTTPPort)
	log.Printf("Listening on %s", addr)
	if err := router.Run(addr); err != nil {
		log.Fatalf("Failed to start server: %v", err)
	}
}
