#!/bin/bash
# QQ Bot - Linux launcher (keep-alive mode)
# Usage: ./start.sh          foreground with auto-restart
#        ./start.sh -d        daemon mode (background)
#        ./start.sh stop      stop daemon

set -e
cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"
PID_FILE="bot.pid"
LOG_FILE="bot.log"

stop_bot() {
    if [ -f "$PID_FILE" ]; then
        pid=$(cat "$PID_FILE")
        if kill -0 "$pid" 2>/dev/null; then
            echo "Stopping bot (PID $pid)..."
            kill "$pid"
            sleep 2
            kill -0 "$pid" 2>/dev/null && kill -9 "$pid" 2>/dev/null || true
        fi
        rm -f "$PID_FILE"
        echo "Bot stopped."
    else
        echo "Bot is not running (no PID file)."
        # Fallback: kill by name
        pkill -f "python.*bot.py" 2>/dev/null && echo "Killed lingering bot processes." || echo "No bot process found."
    fi
}

case "${1:-}" in
    stop|--stop|-s)
        stop_bot
        exit 0
        ;;
    status|--status)
        if [ -f "$PID_FILE" ]; then
            pid=$(cat "$PID_FILE")
            if kill -0 "$pid" 2>/dev/null; then
                echo "Bot is running (PID $pid)."
                exit 0
            fi
        fi
        echo "Bot is not running."
        exit 1
        ;;
esac

# Install deps
echo "Installing dependencies..."
$PYTHON -m pip install -r requirements.txt -q

if [ "${1:-}" = "-d" ] || [ "${1:-}" = "--daemon" ]; then
    # Daemon mode: launch in background with nohup
    stop_bot 2>/dev/null || true
    nohup bash "$0" run >> "$LOG_FILE" 2>&1 &
    echo $! > "$PID_FILE"
    echo "Bot started in background (PID $(cat $PID_FILE)). Logs: $LOG_FILE"
    echo "Stop with: ./start.sh stop"
    exit 0
fi

# Foreground keep-alive loop
restart_count=0
while true; do
    restart_count=$((restart_count + 1))
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Bot start #$restart_count"

    $PYTHON bot.py
    exit_code=$?

    if [ "$exit_code" = "0" ]; then
        echo "[$(date)] Bot stopped normally (exit 0)."
        break
    fi

    if [ "$exit_code" = "2" ]; then
        echo "[$(date)] Reload requested - restarting immediately..."
        continue
    fi

    echo "[$(date)] Bot exited with code $exit_code - restarting in 5s..."
    sleep 5
done
