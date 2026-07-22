#!/bin/bash
# upload.sh - Transfers completed video segments to SMB share and cleans up local copies

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/config.sh"

mkdir -p "$LOCAL_TEMP_DIR"

echo "[upload.sh] Starting SMB upload loop..."

while true; do
    # Find files in local temp dir matching rec_*.mp4
    shopt -s nullglob
    files=("$LOCAL_TEMP_DIR"/rec_*.mp4)
    shopt -u nullglob

    if [ ${#files[@]} -gt 0 ]; then
        # Sort files chronologically so the newest file (currently being written) is last
        IFS=$'\n' sorted_files=($(sort <<<"${files[*]}"))
        unset IFS

        # process all completed segments except the current active one (last file)
        for (( i=0; i<${#sorted_files[@]}-1; i++ )); do
            file="${sorted_files[i]}"
            filename="$(basename "$file")"

            # Double check file is not locked or open by another process (e.g. ffmpeg)
            if command -v lsof >/dev/null 2>&1; then
                if lsof "$file" >/dev/null 2>&1; then
                    continue
                fi
            fi

            echo "[upload.sh] Offloading $filename to SMB share..."

            # Upload using smbclient
            smbclient "//${SMB_IP}/${SMB_SHARE}" "$SMB_PASS" -U "$SMB_USER" -c "put \"$file\" \"$filename\"" >/dev/null 2>&1
            status=$?

            if [ $status -eq 0 ]; then
                echo "[upload.sh] Successfully uploaded $filename. Removing local copy."
                rm -f "$file"
            else
                echo "[upload.sh] Upload failed for $filename (error code $status). Retrying next cycle."
            fi
        done
    fi

    sleep 15
done
