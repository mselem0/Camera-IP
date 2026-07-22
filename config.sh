#!/bin/bash
# config.sh - Configuration settings for RTSP Termux recorder & SMB offloader

# RTSP Camera Configuration
CAMERA_IP="192.168.1.100"
RTSP_USER="admin"
RTSP_PASS="password123"
RTSP_PORT="554"
RTSP_PATH="stream1"

# Network SMB Share Configuration
SMB_IP="192.168.1.1"
SMB_SHARE="Recordings"
SMB_USER="smbuser"
SMB_PASS="smbpass"

# Local Storage & Segment Settings
LOCAL_TEMP_DIR="$HOME/storage/recordings"
SEGMENT_DURATION=600  # Segment duration in seconds (10 minutes)
MAX_STORAGE_GB=100    # Maximum storage limit on SMB share in GB
