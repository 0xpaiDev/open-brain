#!/bin/bash
# Open Brain — start all services locally
# Usage: ./start.sh
# Logs:  tail -f /tmp/ob-api.log /tmp/ob-worker.log /tmp/ob-bot.log

set -e
cd "$(dirname "$0")"

# ── Kill any leftover processes ───────────────────────────────────────────────
echo "Stopping any previous processes..."
pkill -f "uvicorn src.api.main" 2>/dev/null || true
pkill -f "src.pipeline.worker"  2>/dev/null || true
pkill -f "src.integrations.discord_bot" 2>/dev/null || true
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

# ── Start Discord Bot ─────────────────────────────────────────────────────────
echo "Starting Discord bot..."
.venv/bin/python -m src.integrations.discord_bot > /tmp/ob-bot.log 2>&1 &
BOT_PID=$!

# Wait for bot to connect (Discord gateway can take up to 15s)
for i in {1..15}; do
    sleep 1
    if grep -q "discord_bot_ready" /tmp/ob-bot.log 2>/dev/null; then
        BOT_NAME=$(grep "discord_bot_ready" /tmp/ob-bot.log | grep -o '"username": "[^"]*"' | cut -d'"' -f4)
        echo "  ✓ Bot online as $BOT_NAME (PID $BOT_PID)"
        break
    fi
    if [ $i -eq 15 ]; then
        echo "  ✗ Bot failed to connect. Check: tail /tmp/ob-bot.log"
        exit 1
    fi
done

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo "Open Brain is running."
echo ""
echo "  Logs:   tail -f /tmp/ob-api.log /tmp/ob-worker.log /tmp/ob-bot.log"
echo "  Stop:   ./stop.sh"
echo ""
