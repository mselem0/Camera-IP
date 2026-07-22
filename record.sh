#!/bin/bash
# record.sh - Records RTSP stream into 10-minute .mp4 segments using ffmpeg stream copy

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/config.sh"

mkdir -p "$LOCAL_TEMP_DIR"

# Acquire Termux wake lock to prevent CPU sleep
if command -v termux-wake-lock >/dev/null 2>&1; then
    termux-wake-lock
fi

trap "if command -v termux-wake-unlock >/dev/null 2>&1; then termux-wake-unlock; fi; exit" EXIT INT TERM

if [ -n "$RTSP_USER" ] || [ -n "$RTSP_PASS" ]; then
    RTSP_URL="rtsp://${RTSP_USER}:${RTSP_PASS}@${CAMERA_IP}:${RTSP_PORT}/${RTSP_PATH}"
else
    RTSP_URL="rtsp://${CAMERA_IP}:${RTSP_PORT}/${RTSP_PATH}"
fi

echo "[record.sh] Starting RTSP recording loop..."

while true; do
    echo "[record.sh] Launching ffmpeg..."
    ffmpeg -loglevel warning \
        -rtsp_transport tcp \
        -i "$RTSP_URL" \
        -c copy \
        -f segment \
        -segment_time "$SEGMENT_DURATION" \
        -segment_format mp4 \
        -reset_timestamps 1 \
        -strftime 1 \
        "$LOCAL_TEMP_DIR/rec_%Y%m%d_%H%M%S.mp4"

    echo "[record.sh] ffmpeg exited with status $?. Reconnecting in 5 seconds..."
    sleep 5
done
