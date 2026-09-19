#!/bin/sh
set -eu

apk add --no-cache coreutils >/dev/null 2>&1 || true
mkdir -p /tmp /var/log/logwriter

# Simple random milliseconds using POSIX sh (no complex arithmetic)
get_duration() {
  # Use seconds and PID for simple "random" value
  sec=$(date +%S 2>/dev/null || echo "0")
  # Remove leading zeros to avoid octal interpretation
  sec=$(echo "$sec" | sed 's/^0*//')
  sec=${sec:-0}
  
  # Simple calculation: (seconds + PID) % 500 + 1
  duration=$(( (sec + $$) % 500 + 1 ))
  echo "$duration"
}

# Weighted random status: 70% success, 20% error, 10% pending
get_weighted_status() {
  sec=$(date +%S 2>/dev/null || echo "0")
  sec=$(echo "$sec" | sed 's/^0*//')
  sec=${sec:-0}
  r=$((sec % 10))
  
  if [ "$r" -lt 7 ]; then
    echo "success"
  elif [ "$r" -lt 9 ]; then
    echo "error"
  else
    echo "pending"
  fi
}

# Get status code based on status
get_status_code() {
  case "$1" in
    success)
      echo "200"
      ;;
    error)
      echo "500"
      ;;
    pending)
      echo "202"
      ;;
    *)
      echo "500"
      ;;
  esac
}

while true; do
  ts="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
  duration=$(get_duration)
  status=$(get_weighted_status)
  
  # Get message based on status and service
  case "$status" in
    success)
      msg_worker="task_processed"
      msg_backend="request_handled"
      msg_frontend="page_loaded"
      ;;
    error)
      msg_worker="task_processing_timeout"
      msg_backend="database_connection_lost"
      msg_frontend="api_response_error"
      ;;
    pending)
      msg_worker="task_queued_waiting"
      msg_backend="request_processing"
      msg_frontend="page_loading"
      ;;
  esac
  
  # Get status codes
  status_code_worker=$(get_status_code "$status")
  status_code_backend=$(get_status_code "$status")
  status_code_frontend=$(get_status_code "$status")
  
  # Worker
  line="{\"timestamp\":\"$ts\",\"service\":\"worker\", \"message\":\"$msg_worker\", \"status\":\"$status\", \"duration\": $((duration + 50)), \"status_code\": $status_code_worker}"
  echo "$line" >> /var/log/logwriter/worker.log
  
  # Backend
  line="{\"timestamp\":\"$ts\",\"service\":\"backend\", \"message\":\"$msg_backend\", \"status\":\"$status\", \"duration\": $((duration + 100)), \"status_code\": $status_code_backend}"
  echo "$line" >> /var/log/logwriter/backend.log
  
  # Frontend
  line="{\"timestamp\":\"$ts\",\"service\":\"frontend\", \"message\":\"$msg_frontend\", \"status\":\"$status\", \"duration\": $((duration + 25)), \"status_code\": $status_code_frontend}"
  echo "$line" >> /var/log/logwriter/frontend.log
  
  sleep 2
done