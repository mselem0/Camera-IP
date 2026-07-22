#!/bin/bash
# status.sh - Termux:Widget shortcut to display current status via termux-notification

STATUS_JSON=$(curl -s http://localhost:8080/api/status 2>/dev/null)

if [ -n "$STATUS_JSON" ]; then
    STATE=$(echo "$STATUS_JSON" | grep -o '"status":"[^"]*"' | cut -d'"' -f4)
    FREE=$(echo "$STATUS_JSON" | grep -o '"free_space":"[^"]*"' | cut -d'"' -f4)
    LAST=$(echo "$STATUS_JSON" | grep -o '"last_upload":"[^"]*"' | cut -d'"' -f4)
else
    # Fallback if dashboard api is unreachable
    if pgrep -f "record.sh" >/dev/null 2>&1; then
        STATE="RUNNING"
    else
        STATE="STOPPED"
    fi
    FREE="Unknown"
    LAST="Unknown"
fi

TITLE="NVR Status: $STATE"
CONTENT="SSD Free: $FREE | Last Upload: $LAST"

if command -v termux-notification >/dev/null 2>&1; then
    termux-notification --title "$TITLE" --content "$CONTENT" --id "nvr_status"
else
    echo "$TITLE"
    echo "$CONTENT"
fi
