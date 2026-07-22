# Termux RTSP NVR & SMB Offloader

A lightweight, automated Network Video Recorder (NVR) solution designed to run directly on Android via Termux. It captures RTSP streams from IP cameras in 10-minute segments, automatically offloads them to a network SMB share (e.g., router-attached SSD), manages FIFO storage limits, and provides a web dashboard + home screen widgets for hands-free control.

---

## 🚀 Features

- **Continuous RTSP Recording:** Uses `ffmpeg` to segment streams with zero recoding CPU overhead.
- **Automated SMB Offloading:** Safely transfers completed segments to a local network share via `smbclient`.
- **FIFO Capacity Management:** Monitors storage space on the SMB share and auto-deletes the oldest recordings when capacity is exceeded.
- **Web Dashboard:** Mobile-friendly Flask interface on `http://localhost:8080` showing live status, SSD free space, last upload timestamp, and live logs.
- **Termux:Widget Shortcuts:** Android home screen buttons for **Start**, **Stop**, and **Status Notification**.
- **Autostart Support:** Boot integration via `Termux:Boot`.

---

## 🛠️ Setup & Installation

### 1. Prerequisites (in Termux)
```bash
pkg update && pkg upgrade -y
pkg install ffmpeg samba python termux-api -y
pip install flask
```

### 2. Configure Settings
Edit `config.sh` to match your RTSP Camera & Router SMB Share details:
```bash
nano config.sh
```

---

## 📱 Web Dashboard (`dashboard.py`)

The dashboard provides a simple control panel at `http://localhost:8080`.

### Accessing the Dashboard
- Open Chrome or any browser on the Android phone and navigate to:
  `http://localhost:8080`

> 🔒 **Security Note:** Flask is configured to bind strictly to `127.0.0.1` (localhost). It is **not** exposed to the external local network, preventing unauthorized access from other network devices.

### Auto-start Dashboard on Boot
To make the dashboard automatically run in the background whenever Termux boots, add the following to `~/.termux/boot/start-nvr-dashboard.sh`:

```bash
mkdir -p ~/.termux/boot
cat << 'EOF' > ~/.termux/boot/start-nvr-dashboard.sh
#!/bin/bash
termux-wake-lock
cd ~/Camera-IP-App
nohup python3 dashboard.py > dashboard.log 2>&1 &
EOF
chmod +x ~/.termux/boot/start-nvr-dashboard.sh
```

---

## 🔘 Termux:Widget Shortcuts

You can control the NVR without opening the terminal using widget shortcuts on your Android home screen.

### 1. Installing Termux:Widget & Termux:API
1. Install **Termux:Widget** and **Termux:API** from **F-Droid** (must match the signature of your main Termux app).
2. Install `termux-api` inside Termux:
   ```bash
   pkg install termux-api
   ```

### 2. Installing Shortcut Scripts
Copy the shortcut scripts into `~/.shortcuts/`:
```bash
mkdir -p ~/.shortcuts
cp shortcuts/*.sh ~/.shortcuts/
chmod +x ~/.shortcuts/*.sh
```

### 3. Adding Shortcuts to Home Screen
1. Long-press on your Android home screen and select **Widgets**.
2. Find **Termux:Widget** and select either **Termux Short-cut** or the **Termux Widget** folder.
3. Drag the widget to your home screen.
4. You will see:
   - `start-recording.sh`: Starts `record.sh`, `upload.sh`, and `cleanup.sh`.
   - `stop-recording.sh`: Safely terminates all NVR processes.
   - `status.sh`: Triggers a native Termux notification showing current state, free space, and last upload time.
