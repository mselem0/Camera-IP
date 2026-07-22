#!/bin/bash
# start.sh - Supervisor script to launch record.sh, upload.sh, and cleanup.sh in the background

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/config.sh"

# Make scripts executable
chmod +x "$SCRIPT_DIR/record.sh" "$SCRIPT_DIR/upload.sh" "$SCRIPT_DIR/cleanup.sh"

# Helper function to start a process with nohup if not already running
start_process() {
    local script_name="$1"
    local script_path="$SCRIPT_DIR/$script_name"

    if pgrep -f "$script_name" >/dev/null 2>&1; then
        echo "[start.sh] $script_name is already running."
    else
        echo "[start.sh] Starting $script_name in background..."
        nohup "$script_path" > "$SCRIPT_DIR/${script_name%.sh}.log" 2>&1 &
    fi
}

start_process "record.sh"
start_process "upload.sh"
start_process "cleanup.sh"

echo "[start.sh] All processes started successfully."
echo "[start.sh] Logs available in $SCRIPT_DIR/*.log"
