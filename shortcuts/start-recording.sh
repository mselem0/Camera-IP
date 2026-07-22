#!/bin/bash
# start-recording.sh - Termux:Widget shortcut to start NVR services

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$HOME/Camera-IP-App" # fallback if executed in shortcuts

if [ -f "$SCRIPT_DIR/start.sh" ]; then
    bash "$SCRIPT_DIR/start.sh"
elif [ -f "$PROJECT_DIR/start.sh" ]; then
    bash "$PROJECT_DIR/start.sh"
else
    curl -s -X POST http://localhost:8080/api/start >/dev/null 2>&1
fi

if command -v termux-notification >/dev/null 2>&1; then
    termux-notification --title "Termux NVR" --content "Started NVR recording & offloader" --id "nvr_status"
fi
