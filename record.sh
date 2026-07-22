#!/bin/bash
# record.sh - Records RTSP stream into 10-minute .mp4 segments using ffmpeg stream copy

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/config.sh"

EVALUATED_TEMP_DIR=$(eval echo "$LOCAL_TEMP_DIR")
mkdir -p "$EVALUATED_TEMP_DIR"

# Acquire Termux wake lock to prevent CPU sleep
if command -v termux-wake-lock >/dev/null 2>&1; then
    termux-wake-lock
fi

trap "if command -v termux-wake-unlock >/dev/null 2>&1; then termux-wake-unlock; fi; exit" EXIT INT TERM

# Helper function to URL-encode special characters in credentials (e.g., @, #, $, %, etc.)
urlencode() {
    local string="${1}"
    local strlen=${#string}
    local encoded=""
    local pos char

    for (( pos=0; pos<strlen; pos++ )); do
        char=${string:$pos:1}
        case "$char" in
            [a-zA-Z0-9.~_-]) encoded+="$char" ;;
            *) printf -v hex '%%%02X' "'$char"
               encoded+="$hex" ;;
        esac
    done
    echo "$encoded"
}

if [ -n "$RTSP_USER" ] && [ -n "$RTSP_PASS" ]; then
    ENC_USER=$(urlencode "$RTSP_USER")
    ENC_PASS=$(urlencode "$RTSP_PASS")
    RTSP_URL="rtsp://${ENC_USER}:${ENC_PASS}@${CAMERA_IP}:${RTSP_PORT}/${RTSP_PATH}"
elif [ -n "$RTSP_USER" ]; then
    ENC_USER=$(urlencode "$RTSP_USER")
    RTSP_URL="rtsp://${ENC_USER}@${CAMERA_IP}:${RTSP_PORT}/${RTSP_PATH}"
else
    RTSP_URL="rtsp://${CAMERA_IP}:${RTSP_PORT}/${RTSP_PATH}"
fi

echo "[record.sh] Starting RTSP recording loop..."

while true; do
    echo "[record.sh] Launching ffmpeg..."
    ffmpeg -loglevel info \
        -rtsp_transport tcp \
        -stimeout 10000000 \
        -i "$RTSP_URL" \
        -c copy \
        -movflags +faststart \
        -f segment \
        -segment_time "$SEGMENT_DURATION" \
        -segment_format mp4 \
        -reset_timestamps 1 \
        -strftime 1 \
        "$EVALUATED_TEMP_DIR/rec_%Y%m%d_%H%M%S.mp4"

    echo "[record.sh] ffmpeg exited with status $?. Reconnecting in 5 seconds..."
    sleep 5
done
