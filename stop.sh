#!/bin/bash
# Open Brain — stop all services
cd "$(dirname "$0")"

pkill -f "uvicorn src.api.main"     2>/dev/null && echo "✓ API stopped"     || echo "  API was not running"
pkill -f "src.pipeline.worker"      2>/dev/null && echo "✓ Worker stopped"  || echo "  Worker was not running"
pkill -f "src.integrations.discord_bot" 2>/dev/null && echo "✓ Bot stopped" || echo "  Bot was not running"
