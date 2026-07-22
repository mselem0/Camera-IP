#!/bin/bash
# cleanup.sh - Monitors SMB share usage and enforces maximum storage capacity (FIFO deletion)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/config.sh"

echo "[cleanup.sh] Starting storage cleanup monitor loop..."

while true; do
    MAX_BYTES=$(( MAX_STORAGE_GB * 1024 * 1024 * 1024 ))

    # Fetch file listings from SMB share
    dir_output=$(smbclient "//${SMB_IP}/${SMB_SHARE}" "$SMB_PASS" -U "$SMB_USER" -c "ls rec_*.mp4" 2>/dev/null)

    if [ $? -eq 0 ] && [ -n "$dir_output" ]; then
        total_size=0
        declare -a file_names
        declare -a file_sizes

        while IFS= read -r line; do
            # Parse smbclient ls lines, format: "  filename.mp4     A     104857600  Wed Jul 22 10:00:00 2026"
            if [[ "$line" =~ (rec_[0-9_]+\.mp4)[[:space:]]+[A-Z]*[[:space:]]+([0-9]+) ]]; then
                fname="${BASH_REMATCH[1]}"
                fsize="${BASH_REMATCH[2]}"
                file_names+=("$fname")
                file_sizes+=("$fsize")
                total_size=$(( total_size + fsize ))
            fi
        done <<< "$dir_output"

        # Check if total storage exceeds limit
        if [ "$total_size" -gt "$MAX_BYTES" ]; then
            echo "[cleanup.sh] Total SMB storage usage (${total_size} bytes) exceeds limit (${MAX_BYTES} bytes)."

            # Sort filenames in ascending order (oldest first due to rec_YYYYMMDD_HHMMSS naming)
            IFS=$'\n' sorted_names=($(sort <<<"${file_names[*]}"))
            unset IFS

            for fname in "${sorted_names[@]}"; do
                if [ "$total_size" -le "$MAX_BYTES" ]; then
                    break
                fi

                # Find size of file to subtract
                for i in "${!file_names[@]}"; do
                    if [[ "${file_names[$i]}" == "$fname" ]]; then
                        del_size="${file_sizes[$i]}"
                        break
                    fi
                done

                echo "[cleanup.sh] Deleting oldest segment from SMB: $fname (${del_size} bytes)"
                smbclient "//${SMB_IP}/${SMB_SHARE}" "$SMB_PASS" -U "$SMB_USER" -c "rm \"$fname\"" >/dev/null 2>&1
                if [ $? -eq 0 ]; then
                    total_size=$(( total_size - del_size ))
                fi
            done
        fi
    fi

    # Run cleanup check every 10 minutes
    sleep 600
done
