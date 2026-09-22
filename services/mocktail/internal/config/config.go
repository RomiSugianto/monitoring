package config

import (
	"os"
	"strconv"
)

type Config struct {
	HTTPPort   string
	LokiURL    string
	ServiceName string
	Instance   string
	IPAddress  string
}

func Load() *Config {
	return &Config{
		HTTPPort:    getEnv("HTTP_PORT", "9095"),
		LokiURL:     getEnv("LOKI_URL", "http://localhost:3100"),
		ServiceName: getEnv("SERVICE_NAME", "mocktail"),
		Instance:    getEnv("INSTANCE", "localhost"),
		IPAddress:   getEnv("IP_ADDRESS", "127.0.0.1"),
	}
}

func getEnv(key, defaultValue string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return defaultValue
}

func getEnvBool(key string, defaultValue bool) bool {
	if value := os.Getenv(key); value != "" {
		if b, err := strconv.ParseBool(value); err == nil {
			return b
		}
	}
	return defaultValue
}
