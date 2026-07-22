# Termux RTSP NVR & SMB Offloader

A lightweight, automated Network Video Recorder (NVR) solution designed to run directly on Android via Termux. It captures RTSP streams from IP cameras in 10-minute segments, automatically offloads them to a network SMB share (e.g., router-attached SSD), manages FIFO storage limits, and provides a full-featured web controller + home screen widgets for hands-free setup and operation.

---

## 🚀 Features

- **Universal Auto-Discovery Scanner:** Scans your local network (`192.168.x.1-254`), testing multiple common RTSP stream paths (`stream1`, `live/ch0`, `h264`, `Streaming/Channels/101`, `cam/realmonitor`, `live`) and standard default credential sets automatically.
- **Unauthenticated Stream Support:** Works seamlessly with open/anonymous cameras that do not require a username or password.
- **Live Camera View:** View real-time snapshot preview directly from the RTSP camera on the UI (auto-refreshed every 3 seconds).
- **Recordings Playback:** Browse and play recorded `.mp4` video segments (both local temp buffer and SMB share offloads) right inside the web browser.
- **Full UI Management:** Control recording state, view real-time logs, monitor SSD storage, AND manage all camera/SMB configurations directly from the web interface without touching `config.sh` or the terminal.
- **Continuous RTSP Recording:** Uses `ffmpeg` to segment streams with zero recoding CPU overhead.
- **Automated SMB Offloading:** Safely transfers completed segments to a local network share via `smbclient`.
- **FIFO Capacity Management:** Monitors storage space on the SMB share and auto-deletes the oldest recordings when capacity is exceeded.
- **Web Dashboard:** Mobile-friendly Flask interface on `http://localhost:8080` with Dashboard, Live View, Recordings Browser/Player, and Settings tabs.
- **Termux:Widget Shortcuts:** Android home screen buttons for **Start**, **Stop**, and **Status Notification**.
- **Autostart Support:** Boot integration via `Termux:Boot`.

---

## 🛠️ Setup & Quickstart

### 1. Initial Prerequisites (Run once in Termux)
```bash
pkg update && pkg upgrade -y
pkg install ffmpeg samba python termux-api -y
pip install flask
```

### 2. Launch Controller
Run the Flask controller server:
```bash
python3 dashboard.py
```

### 3. Open UI in Mobile Browser
Open Chrome or any mobile browser on the device and navigate to:
```
http://localhost:8080
```
- **Dashboard:** Start/stop recording, check SSD free space, and view live system logs.
- **Live View:** Preview live camera frames.
- **Recordings:** Watch saved `.mp4` video segments stored on local storage or the SMB share.
- **Settings:** Click **Scan Network & Auto-Detect Streams** to automatically discover RTSP camera IPs, working stream paths, and credentials, then click **Select** to apply them instantly.

> 🔒 **Security Note:** Flask is configured to bind strictly to `127.0.0.1` (localhost). It is **not** exposed to the external local network, preventing unauthorized access from other network devices.

---

## 📱 Auto-start Dashboard on Boot

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
4. Available shortcuts:
   - `start-recording.sh`: Starts `record.sh`, `upload.sh`, and `cleanup.sh`.
   - `stop-recording.sh`: Safely terminates all NVR processes.
   - `status.sh`: Triggers a native Termux notification showing current state, free space, and last upload time.
