#!/bin/bash
# stop-recording.sh - Termux:Widget shortcut to stop NVR services

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$HOME/Camera-IP-App"

curl -s -X POST http://localhost:8080/api/stop >/dev/null 2>&1

# Fallback direct process termination
pkill -f "record.sh|upload.sh|cleanup.sh" >/dev/null 2>&1

if command -v termux-notification >/dev/null 2>&1; then
    termux-notification --title "Termux NVR" --content "Stopped NVR recording" --id "nvr_status"
fi
