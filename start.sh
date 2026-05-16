#!/bin/bash
# Open Brain — start all services locally
# Usage: ./start.sh
# Logs:  tail -f /tmp/ob-api.log /tmp/ob-worker.log

set -e
cd "$(dirname "$0")"

# ── Kill any leftover processes ───────────────────────────────────────────────
echo "Stopping any previous processes..."
pkill -f "uvicorn src.api.main" 2>/dev/null || true
pkill -f "src.pipeline.worker"  2>/dev/null || true
sleep 1

# Force unbuffered output so log files get written immediately
export PYTHONUNBUFFERED=1

# ── Start API ─────────────────────────────────────────────────────────────────
echo "Starting API..."
.venv/bin/python -m uvicorn src.api.main:app --host localhost --port 8000 \
    > /tmp/ob-api.log 2>&1 &
API_PID=$!

# Wait for API to be ready
for i in {1..10}; do
    sleep 1
    if curl -sf http://localhost:8000/health > /dev/null 2>&1; then
        echo "  ✓ API ready (PID $API_PID)"
        break
    fi
    if [ $i -eq 10 ]; then
        echo "  ✗ API failed to start. Check: tail /tmp/ob-api.log"
        exit 1
    fi
done

# ── Start Worker ──────────────────────────────────────────────────────────────
echo "Starting Worker..."
.venv/bin/python -m src.pipeline.worker > /tmp/ob-worker.log 2>&1 &
WORKER_PID=$!
sleep 1
echo "  ✓ Worker ready (PID $WORKER_PID)"

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo "Open Brain is running."
echo ""
echo "  Logs:   tail -f /tmp/ob-api.log /tmp/ob-worker.log"
echo "  Stop:   ./stop.sh"
echo ""
