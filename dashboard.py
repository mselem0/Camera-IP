from flask import Flask, jsonify, render_template_string, request, Response, send_from_directory
import subprocess
import os
import re
import signal
import time
import socket
import concurrent.futures

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PID_FILE = os.path.join(BASE_DIR, "nvr.pid")
CONFIG_FILE = os.path.join(BASE_DIR, "config.sh")
SCRIPTS = ["record.sh", "upload.sh", "cleanup.sh"]

def parse_config():
    config = {}
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    config[key.strip()] = val.strip().strip('"').strip("'")
    return config

def save_config_file(config_data):
    lines = [
        "#!/bin/bash",
        "# config.sh - Configuration settings for RTSP Termux recorder & SMB offloader",
        "",
        "# RTSP Camera Configuration",
        f'CAMERA_IP="{config_data.get("CAMERA_IP", "")}"',
        f'RTSP_USER="{config_data.get("RTSP_USER", "")}"',
        f'RTSP_PASS="{config_data.get("RTSP_PASS", "")}"',
        f'RTSP_PORT="{config_data.get("RTSP_PORT", "554")}"',
        f'RTSP_PATH="{config_data.get("RTSP_PATH", "stream1")}"',
        "",
        "# Network SMB Share Configuration",
        f'SMB_IP="{config_data.get("SMB_IP", "")}"',
        f'SMB_SHARE="{config_data.get("SMB_SHARE", "")}"',
        f'SMB_USER="{config_data.get("SMB_USER", "")}"',
        f'SMB_PASS="{config_data.get("SMB_PASS", "")}"',
        "",
        "# Local Storage & Segment Settings",
        f'LOCAL_TEMP_DIR="{config_data.get("LOCAL_TEMP_DIR", "$HOME/storage/recordings")}"',
        f'SEGMENT_DURATION={config_data.get("SEGMENT_DURATION", "600")}',
        f'MAX_STORAGE_GB={config_data.get("MAX_STORAGE_GB", "100")}',
        ""
    ]
    with open(CONFIG_FILE, "w") as f:
        f.write("\n".join(lines))

def resolve_temp_dir():
    config = parse_config()
    raw_path = config.get("LOCAL_TEMP_DIR", "$HOME/storage/recordings")
    expanded = os.path.expanduser(os.path.expandvars(raw_path))
    return os.path.abspath(expanded)

def is_process_running(pid):
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ValueError):
        return False

def get_running_pids():
    pids = {}
    if os.path.exists(PID_FILE):
        with open(PID_FILE, "r") as f:
            for line in f:
                line = line.strip()
                if ":" in line:
                    name, pid_str = line.split(":", 1)
                    try:
                        pid = int(pid_str)
                        if is_process_running(pid):
                            pids[name] = pid
                    except ValueError:
                        pass
    return pids

def save_pids(pids):
    with open(PID_FILE, "w") as f:
        for name, pid in pids.items():
            f.write(f"{name}:{pid}\n")

def start_nvr():
    current_pids = get_running_pids()
    new_pids = {}
    for script in SCRIPTS:
        script_path = os.path.join(BASE_DIR, script)
        log_path = os.path.join(BASE_DIR, f"{os.path.splitext(script)[0]}.log")
        if script in current_pids and is_process_running(current_pids[script]):
            new_pids[script] = current_pids[script]
        else:
            with open(log_path, "a") as log_file:
                proc = subprocess.Popen(
                    ["/bin/bash", script_path],
                    cwd=BASE_DIR,
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    preexec_fn=os.setsid
                )
                new_pids[script] = proc.pid
    save_pids(new_pids)
    return True

def stop_nvr():
    current_pids = get_running_pids()
    for script, pid in current_pids.items():
        try:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        except OSError:
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
    if os.path.exists(PID_FILE):
        try:
            os.remove(PID_FILE)
        except OSError:
            pass
    try:
        subprocess.run(["pkill", "-f", "record.sh|upload.sh|cleanup.sh"], stderr=subprocess.DEVNULL)
    except Exception:
        pass
    return True

def get_last_upload_time():
    upload_log = os.path.join(BASE_DIR, "upload.log")
    if not os.path.exists(upload_log):
        return "No uploads yet"
    last_time = "No uploads yet"
    try:
        with open(upload_log, "r") as f:
            for line in f:
                if "Successfully uploaded" in line:
                    match = re.search(r"rec_(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})", line)
                    if match:
                        g = match.groups()
                        last_time = f"{g[0]}-{g[1]}-{g[2]} {g[3]}:{g[4]}:{g[5]}"
                    else:
                        last_time = line.strip()
    except Exception:
        pass
    return last_time

def get_free_space():
    config = parse_config()
    smb_ip = config.get("SMB_IP", "")
    smb_share = config.get("SMB_SHARE", "")
    smb_user = config.get("SMB_USER", "")
    smb_pass = config.get("SMB_PASS", "")

    if not smb_ip or not smb_share:
        return "Config missing"

    try:
        cmd = ["smbclient", f"//{smb_ip}/{smb_share}", smb_pass, "-U", smb_user, "-c", "df"]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        if res.returncode == 0:
            match = re.search(r"(\d+)\s+blocks available", res.stdout, re.IGNORECASE)
            if match:
                avail_kb = int(match.group(1))
                avail_gb = avail_kb / (1024 * 1024)
                return f"{avail_gb:.2f} GB"
            lines = res.stdout.strip().split("\n")
            return lines[-1] if lines else "Available"
        return "Unavailable (SMB offline)"
    except Exception:
        return "Unavailable"

def get_recent_logs(lines_count=10):
    all_logs = []
    for script in SCRIPTS:
        log_file = os.path.join(BASE_DIR, f"{os.path.splitext(script)[0]}.log")
        if os.path.exists(log_file):
            try:
                with open(log_file, "r") as f:
                    lines = f.readlines()
                    all_logs.extend(lines[-lines_count:])
            except Exception:
                pass
    if not all_logs:
        return "No log output available."
    return "".join(all_logs[-lines_count:])

def get_recordings_list():
    recordings = []
    config = parse_config()
    local_dir = resolve_temp_dir()
    
    if os.path.exists(local_dir):
        for f in os.listdir(local_dir):
            if f.startswith("rec_") and f.endswith(".mp4"):
                fp = os.path.join(local_dir, f)
                try:
                    stat = os.stat(fp)
                    recordings.append({
                        "filename": f,
                        "size_mb": round(stat.st_size / (1024 * 1024), 2),
                        "location": "Local",
                        "mtime": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime))
                    })
                except OSError:
                    pass

    smb_ip = config.get("SMB_IP", "")
    smb_share = config.get("SMB_SHARE", "")
    smb_user = config.get("SMB_USER", "")
    smb_pass = config.get("SMB_PASS", "")

    if smb_ip and smb_share:
        try:
            cmd = ["smbclient", f"//{smb_ip}/{smb_share}", smb_pass, "-U", smb_user, "-c", "ls rec_*.mp4"]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            if res.returncode == 0:
                for line in res.stdout.splitlines():
                    match = re.search(r"(rec_[0-9_]+\.mp4)\s+[A-Z]*\s+([0-9]+)", line)
                    if match:
                        fname = match.group(1)
                        fsize = int(match.group(2))
                        if not any(r["filename"] == fname for r in recordings):
                            recordings.append({
                                "filename": fname,
                                "size_mb": round(fsize / (1024 * 1024), 2),
                                "location": "SMB Share",
                                "mtime": "Stored"
                            })
        except Exception:
            pass

    recordings.sort(key=lambda x: x["filename"], reverse=True)
    return recordings

# --- CAMERA SCANNING FUNCTIONS ---

def get_local_subnet():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        parts = ip.split(".")
        return f"{parts[0]}.{parts[1]}.{parts[2]}"
    except Exception:
        config = parse_config()
        cam_ip = config.get("CAMERA_IP", "192.168.1.100")
        parts = cam_ip.split(".")
        if len(parts) == 4:
            return f"{parts[0]}.{parts[1]}.{parts[2]}"
        return "192.168.1"

def check_ip_port(ip, port=554, timeout=0.6):
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((ip, int(port)))
        sock.close()
        if result == 0:
            return ip
    except Exception:
        pass
    return None

def test_rtsp_stream(ip, user="admin", password="password123", port="554", path="stream1"):
    rtsp_url = f"rtsp://{user}:{password}@{ip}:{port}/{path}"
    cmd = [
        "ffmpeg", "-loglevel", "quiet",
        "-rtsp_transport", "tcp",
        "-i", rtsp_url,
        "-vframes", "1",
        "-f", "image2",
        "pipe:1"
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, timeout=3)
        if res.returncode == 0 and len(res.stdout) > 0:
            return True
    except Exception:
        pass
    return False

def scan_network_for_cameras(user="admin", password="password123", port="554", path="stream1"):
    subnet = get_local_subnet()
    found_ips = []
    
    # Fast multi-threaded TCP scan for RTSP port (e.g. 554 or 8554)
    with concurrent.futures.ThreadPoolExecutor(max_workers=50) as executor:
        futures = [executor.submit(check_ip_port, f"{subnet}.{i}", port) for i in range(1, 255)]
        for future in concurrent.futures.as_completed(futures):
            res_ip = future.result()
            if res_ip:
                found_ips.append(res_ip)

    cameras = []
    for ip in found_ips:
        rtsp_ok = test_rtsp_stream(ip, user, password, port, path)
        cameras.append({
            "ip": ip,
            "port": port,
            "rtsp_open": True,
            "rtsp_verified": rtsp_ok
        })
    return cameras

# --- FLASK ROUTES ---

@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route("/api/status")
def api_status():
    pids = get_running_pids()
    is_running = len(pids) > 0
    return jsonify({
        "status": "RUNNING" if is_running else "STOPPED",
        "running": is_running,
        "free_space": get_free_space(),
        "last_upload": get_last_upload_time(),
        "logs": get_recent_logs(10)
    })

@app.route("/api/scan_cameras", methods=["POST"])
def api_scan_cameras():
    config = parse_config()
    user = request.json.get("user") if request.json else config.get("RTSP_USER", "admin")
    password = request.json.get("password") if request.json else config.get("RTSP_PASS", "password123")
    port = request.json.get("port") if request.json else config.get("RTSP_PORT", "554")
    path = request.json.get("path") if request.json else config.get("RTSP_PATH", "stream1")

    cameras = scan_network_for_cameras(user, password, port, path)
    return jsonify({"cameras": cameras, "subnet": get_local_subnet()})

@app.route("/api/snapshot")
def api_snapshot():
    config = parse_config()
    rtsp_url = f"rtsp://{config.get('RTSP_USER')}:{config.get('RTSP_PASS')}@{config.get('CAMERA_IP')}:{config.get('RTSP_PORT','554')}/{config.get('RTSP_PATH','stream1')}"
    
    cmd = [
        "ffmpeg", "-loglevel", "quiet",
        "-rtsp_transport", "tcp",
        "-i", rtsp_url,
        "-vframes", "1",
        "-f", "image2",
        "-q:v", "3",
        "pipe:1"
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=8)
        if proc.returncode == 0 and len(proc.stdout) > 0:
            return Response(proc.stdout, mimetype="image/jpeg")
    except Exception:
        pass
    
    fallback_svg = '<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360" viewBox="0 0 640 360"><rect width="100%" height="100%" fill="#1e293b"/><text x="50%" y="50%" fill="#94a3b8" dominant-baseline="middle" text-anchor="middle" font-family="sans-serif" font-size="18">Camera Offline or Unreachable</text></svg>'
    return Response(fallback_svg, mimetype="image/svg+xml")

@app.route("/api/recordings")
def api_recordings():
    return jsonify(get_recordings_list())

@app.route("/api/video/<filename>")
def api_stream_video(filename):
    filename = os.path.basename(filename)
    local_dir = resolve_temp_dir()
    local_path = os.path.join(local_dir, filename)

    if os.path.exists(local_path):
        return send_from_directory(local_dir, filename)

    config = parse_config()
    smb_ip = config.get("SMB_IP", "")
    smb_share = config.get("SMB_SHARE", "")
    smb_user = config.get("SMB_USER", "")
    smb_pass = config.get("SMB_PASS", "")

    cmd = ["smbclient", f"//{smb_ip}/{smb_share}", smb_pass, "-U", smb_user, "-c", f"get \"{filename}\" -"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    
    def generate():
        while True:
            chunk = proc.stdout.read(64 * 1024)
            if not chunk:
                break
            yield chunk

    return Response(generate(), mimetype="video/mp4")

@app.route("/api/config", methods=["GET"])
def api_get_config():
    return jsonify(parse_config())

@app.route("/api/config", methods=["POST"])
def api_save_config():
    data = request.json or {}
    save_config_file(data)
    
    pids = get_running_pids()
    was_running = len(pids) > 0
    if was_running:
        stop_nvr()
        time.sleep(1)
        start_nvr()
        
    return jsonify({"success": True, "message": "Configuration saved successfully!" + (" Services restarted." if was_running else "")})

@app.route("/api/start", methods=["POST"])
def api_start():
    start_nvr()
    return jsonify({"success": True, "message": "NVR services started."})

@app.route("/api/stop", methods=["POST"])
def api_stop():
    stop_nvr()
    return jsonify({"success": True, "message": "NVR services stopped."})

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Termux NVR Dashboard</title>
    <style>
        :root {
            --bg-color: #0f172a;
            --card-bg: #1e293b;
            --text-color: #f8fafc;
            --text-muted: #94a3b8;
            --accent-green: #22c55e;
            --accent-red: #ef4444;
            --accent-blue: #3b82f6;
            --border-color: #334155;
            --input-bg: #0f172a;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
        body { background: var(--bg-color); color: var(--text-color); padding: 16px; max-width: 650px; margin: 0 auto; }
        h1 { font-size: 1.4rem; margin-bottom: 16px; text-align: center; color: var(--text-color); }
        .tabs { display: flex; border-bottom: 1px solid var(--border-color); margin-bottom: 16px; }
        .tab-btn { flex: 1; padding: 12px; background: none; border: none; color: var(--text-muted); font-size: 0.95rem; font-weight: 600; cursor: pointer; border-bottom: 2px solid transparent; }
        .tab-btn.active { color: var(--accent-blue); border-bottom-color: var(--accent-blue); }
        .tab-content { display: none; }
        .tab-content.active { display: block; }
        .card { background: var(--card-bg); border-radius: 12px; padding: 16px; margin-bottom: 16px; border: 1px solid var(--border-color); }
        .status-badge { display: inline-block; padding: 6px 12px; border-radius: 20px; font-weight: bold; font-size: 0.85rem; text-transform: uppercase; }
        .status-running { background: rgba(34, 197, 94, 0.2); color: var(--accent-green); border: 1px solid var(--accent-green); }
        .status-stopped { background: rgba(239, 68, 68, 0.2); color: var(--accent-red); border: 1px solid var(--accent-red); }
        .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 12px; }
        .stat-item { background: rgba(0,0,0,0.2); padding: 12px; border-radius: 8px; }
        .stat-label { font-size: 0.75rem; color: var(--text-muted); text-transform: uppercase; margin-bottom: 4px; }
        .stat-value { font-size: 0.95rem; font-weight: 600; word-break: break-word; }
        .btn-group { display: flex; gap: 12px; margin-top: 16px; }
        button.action-btn { flex: 1; padding: 14px; border: none; border-radius: 8px; font-size: 1rem; font-weight: bold; cursor: pointer; transition: opacity 0.2s; }
        button.action-btn:disabled { opacity: 0.5; cursor: not-allowed; }
        .btn-start { background: var(--accent-green); color: white; }
        .btn-stop { background: var(--accent-red); color: white; }
        .btn-save { background: var(--accent-blue); color: white; width: 100%; padding: 14px; border: none; border-radius: 8px; font-size: 1rem; font-weight: bold; cursor: pointer; margin-top: 12px; }
        .btn-scan { background: #8b5cf6; color: white; border: none; padding: 10px 16px; border-radius: 6px; font-weight: 600; font-size: 0.85rem; cursor: pointer; width: 100%; margin-bottom: 12px; }
        pre.logs { background: #090d16; color: #a7f3d0; padding: 12px; border-radius: 8px; font-family: monospace; font-size: 0.75rem; overflow-x: auto; white-space: pre-wrap; max-height: 180px; border: 1px solid var(--border-color); }
        .form-group { margin-bottom: 12px; }
        .form-group label { display: block; font-size: 0.8rem; color: var(--text-muted); margin-bottom: 4px; }
        .form-group input { width: 100%; padding: 10px; border-radius: 6px; border: 1px solid var(--border-color); background: var(--input-bg); color: var(--text-color); font-size: 0.9rem; }
        .section-title { font-size: 0.9rem; color: var(--accent-blue); font-weight: 600; margin: 12px 0 8px 0; border-bottom: 1px solid var(--border-color); padding-bottom: 4px; }
        .toast { position: fixed; bottom: 20px; left: 50%; transform: translateX(-50%); background: var(--accent-green); color: white; padding: 10px 20px; border-radius: 20px; font-weight: 600; display: none; z-index: 1000; box-shadow: 0 4px 12px rgba(0,0,0,0.3); }

        .live-container { position: relative; width: 100%; border-radius: 8px; overflow: hidden; background: #000; aspect-ratio: 16/9; display: flex; align-items: center; justify-content: center; }
        .live-container img { width: 100%; height: 100%; object-fit: contain; }
        .live-overlay { position: absolute; top: 10px; right: 10px; background: rgba(0,0,0,0.6); padding: 4px 8px; border-radius: 4px; font-size: 0.75rem; color: var(--accent-green); display: flex; align-items: center; gap: 6px; }
        .live-dot { width: 8px; height: 8px; background: var(--accent-green); border-radius: 50%; animation: blink 1.5s infinite; }
        @keyframes blink { 0%, 100% { opacity: 1; } 50% { opacity: 0.3; } }
        
        .rec-item { display: flex; justify-content: space-between; align-items: center; padding: 12px; background: rgba(0,0,0,0.2); border-radius: 8px; margin-bottom: 8px; border: 1px solid var(--border-color); }
        .rec-info { font-size: 0.85rem; }
        .rec-name { font-weight: 600; margin-bottom: 2px; }
        .rec-meta { color: var(--text-muted); font-size: 0.75rem; }
        .rec-badge { font-size: 0.7rem; padding: 2px 6px; border-radius: 4px; background: #334155; margin-left: 6px; }
        .btn-play { background: var(--accent-blue); color: white; border: none; padding: 8px 14px; border-radius: 6px; font-size: 0.85rem; font-weight: 600; cursor: pointer; }
        video.player { width: 100%; border-radius: 8px; margin-bottom: 12px; background: #000; }
        
        .cam-scan-card { background: rgba(0,0,0,0.3); border: 1px solid var(--border-color); border-radius: 8px; padding: 10px; margin-bottom: 8px; display: flex; justify-content: space-between; align-items: center; }
        .cam-scan-ip { font-weight: bold; font-size: 0.95rem; }
        .cam-scan-status { font-size: 0.75rem; color: var(--accent-green); margin-top: 2px; }
        .btn-select-cam { background: var(--accent-green); color: white; border: none; padding: 6px 12px; border-radius: 6px; font-size: 0.8rem; font-weight: 600; cursor: pointer; }
    </style>
</head>
<body>
    <h1>📷 Termux NVR Controller</h1>

    <div class="tabs">
        <button class="tab-btn active" onclick="switchTab('dashboard')">Dashboard</button>
        <button class="tab-btn" onclick="switchTab('live')">Live View</button>
        <button class="tab-btn" onclick="switchTab('recordings')">Recordings</button>
        <button class="tab-btn" onclick="switchTab('settings')">Settings</button>
    </div>
    
    <!-- DASHBOARD TAB -->
    <div id="tab-dashboard" class="tab-content active">
        <div class="card">
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <span style="font-weight: 600;">System Status</span>
                <span id="statusBadge" class="status-badge status-stopped">STOPPED</span>
            </div>

            <div class="grid">
                <div class="stat-item">
                    <div class="stat-label">Router SSD Free Space</div>
                    <div id="freeSpace" class="stat-value">--</div>
                </div>
                <div class="stat-item">
                    <div class="stat-label">Last Upload</div>
                    <div id="lastUpload" class="stat-value">--</div>
                </div>
            </div>

            <div class="btn-group">
                <button id="btnStart" class="action-btn btn-start" onclick="control('start')">Start NVR</button>
                <button id="btnStop" class="action-btn btn-stop" onclick="control('stop')">Stop NVR</button>
            </div>
        </div>

        <div class="card">
            <div class="stat-label" style="margin-bottom: 8px;">Recent System Logs (Last 10 Lines)</div>
            <pre id="logOutput" class="logs">Loading logs...</pre>
        </div>
    </div>

    <!-- LIVE VIEW TAB -->
    <div id="tab-live" class="tab-content">
        <div class="card">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
                <span style="font-weight: 600;">Live Camera Snapshot</span>
                <span style="font-size: 0.75rem; color: var(--text-muted);">Auto-refreshes 3s</span>
            </div>
            <div class="live-container">
                <div class="live-overlay"><div class="live-dot"></div> LIVE</div>
                <img id="liveSnapshot" src="/api/snapshot" alt="Live Camera Preview" onclick="refreshSnapshot()">
            </div>
        </div>
    </div>

    <!-- RECORDINGS TAB -->
    <div id="tab-recordings" class="tab-content">
        <div class="card">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
                <span style="font-weight: 600;">Saved Video Segments</span>
                <button onclick="loadRecordings()" style="background: none; border: none; color: var(--accent-blue); font-size: 0.85rem; font-weight: 600; cursor: pointer;">🔄 Refresh</button>
            </div>

            <div id="videoPlayerContainer" style="display: none;">
                <video id="videoPlayer" class="player" controls autoplay></video>
            </div>

            <div id="recordingsList">
                <div style="text-align: center; color: var(--text-muted); padding: 20px;">Loading recordings...</div>
            </div>
        </div>
    </div>

    <!-- SETTINGS TAB -->
    <div id="tab-settings" class="tab-content">
        <div class="card">
            <div class="section-title">🔍 Automatic Network Camera Discovery</div>
            <button id="btnScan" class="btn-scan" onclick="scanNetworkCameras()">Scan Local Network for Cameras</button>
            <div id="scanResults" style="display: none;"></div>
        </div>

        <form id="configForm" onsubmit="saveConfig(event)">
            <div class="card">
                <div class="section-title">📹 RTSP Camera Settings</div>
                <div class="form-group">
                    <label>Camera IP Address</label>
                    <input type="text" id="CAMERA_IP" required placeholder="e.g. 192.168.1.100">
                </div>
                <div class="grid" style="grid-template-columns: 1fr 1fr;">
                    <div class="form-group">
                        <label>RTSP Username</label>
                        <input type="text" id="RTSP_USER" required placeholder="admin">
                    </div>
                    <div class="form-group">
                        <label>RTSP Password</label>
                        <input type="password" id="RTSP_PASS" required>
                    </div>
                </div>
                <div class="grid" style="grid-template-columns: 1fr 1fr;">
                    <div class="form-group">
                        <label>RTSP Port</label>
                        <input type="text" id="RTSP_PORT" required placeholder="554">
                    </div>
                    <div class="form-group">
                        <label>Stream Path</label>
                        <input type="text" id="RTSP_PATH" required placeholder="stream1">
                    </div>
                </div>

                <div class="section-title">📁 Router SMB Share Settings</div>
                <div class="form-group">
                    <label>SMB Server / Router IP</label>
                    <input type="text" id="SMB_IP" required placeholder="192.168.1.1">
                </div>
                <div class="form-group">
                    <label>SMB Share Name</label>
                    <input type="text" id="SMB_SHARE" required placeholder="Recordings">
                </div>
                <div class="grid" style="grid-template-columns: 1fr 1fr;">
                    <div class="form-group">
                        <label>SMB Username</label>
                        <input type="text" id="SMB_USER" required placeholder="smbuser">
                    </div>
                    <div class="form-group">
                        <label>SMB Password</label>
                        <input type="password" id="SMB_PASS" required>
                    </div>
                </div>

                <div class="section-title">⚙️ Recording & Storage Rules</div>
                <div class="form-group">
                    <label>Local Temp Directory</label>
                    <input type="text" id="LOCAL_TEMP_DIR" required placeholder="$HOME/storage/recordings">
                </div>
                <div class="grid" style="grid-template-columns: 1fr 1fr;">
                    <div class="form-group">
                        <label>Segment Duration (sec)</label>
                        <input type="number" id="SEGMENT_DURATION" required placeholder="600">
                    </div>
                    <div class="form-group">
                        <label>Max Storage Limit (GB)</label>
                        <input type="number" id="MAX_STORAGE_GB" required placeholder="100">
                    </div>
                </div>

                <button type="submit" class="btn-save">💾 Save Configuration</button>
            </div>
        </form>
    </div>

    <div id="toast" class="toast">Configuration Saved!</div>

    <script>
        let snapshotInterval = null;

        function switchTab(tabName) {
            document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(content => content.classList.remove('active'));
            
            event.target.classList.add('active');
            document.getElementById('tab-' + tabName).classList.add('active');

            if (snapshotInterval) {
                clearInterval(snapshotInterval);
                snapshotInterval = null;
            }

            if (tabName === 'live') {
                refreshSnapshot();
                snapshotInterval = setInterval(refreshSnapshot, 3000);
            } else if (tabName === 'recordings') {
                loadRecordings();
            } else if (tabName === 'settings') {
                loadConfig();
            }
        }

        function refreshSnapshot() {
            const img = document.getElementById('liveSnapshot');
            if (img) {
                img.src = '/api/snapshot?t=' + new Date().getTime();
            }
        }

        function showToast(msg) {
            const toast = document.getElementById('toast');
            toast.textContent = msg;
            toast.style.display = 'block';
            setTimeout(() => { toast.style.display = 'none'; }, 3000);
        }

        async function fetchStatus() {
            try {
                const res = await fetch('/api/status');
                const data = await res.json();
                
                const badge = document.getElementById('statusBadge');
                if (data.running) {
                    badge.textContent = 'RUNNING';
                    badge.className = 'status-badge status-running';
                    document.getElementById('btnStart').disabled = true;
                    document.getElementById('btnStop').disabled = false;
                } else {
                    badge.textContent = 'STOPPED';
                    badge.className = 'status-badge status-stopped';
                    document.getElementById('btnStart').disabled = false;
                    document.getElementById('btnStop').disabled = true;
                }

                document.getElementById('freeSpace').textContent = data.free_space;
                document.getElementById('lastUpload').textContent = data.last_upload;
                document.getElementById('logOutput').textContent = data.logs;
            } catch (err) {
                console.error('Failed to fetch status:', err);
            }
        }

        async function scanNetworkCameras() {
            const btn = document.getElementById('btnScan');
            const resDiv = document.getElementById('scanResults');
            btn.disabled = true;
            btn.textContent = 'Scanning Subnet (1-254)... Please wait';
            resDiv.style.display = 'block';
            resDiv.innerHTML = '<div style="font-size:0.8rem; color:var(--text-muted); text-align:center; padding:10px;">Probing RTSP ports across subnet...</div>';

            try {
                const res = await fetch('/api/scan_cameras', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        user: document.getElementById('RTSP_USER').value,
                        password: document.getElementById('RTSP_PASS').value,
                        port: document.getElementById('RTSP_PORT').value,
                        path: document.getElementById('RTSP_PATH').value
                    })
                });
                const data = await res.json();
                btn.disabled = false;
                btn.textContent = 'Scan Local Network for Cameras';

                if (!data.cameras || data.cameras.length === 0) {
                    resDiv.innerHTML = `<div style="font-size:0.85rem; color:var(--text-muted); text-align:center; padding:10px;">No cameras detected on subnet ${data.subnet}.x (RTSP Port ${document.getElementById('RTSP_PORT').value}).</div>`;
                    return;
                }

                resDiv.innerHTML = data.cameras.map(cam => `
                    <div class="cam-scan-card">
                        <div>
                            <div class="cam-scan-ip">📹 ${cam.ip}:${cam.port}</div>
                            <div class="cam-scan-status">
                                ${cam.rtsp_verified ? '✅ Stream Verified' : '⚠️ Port 554 Open (RTSP Ready)'}
                            </div>
                        </div>
                        <button type="button" class="btn-select-cam" onclick="selectCamera('${cam.ip}')">Select</button>
                    </div>
                `).join('');
            } catch (err) {
                btn.disabled = false;
                btn.textContent = 'Scan Local Network for Cameras';
                resDiv.innerHTML = '<div style="font-size:0.85rem; color:var(--accent-red); text-align:center; padding:10px;">Scan failed. Check local network connection.</div>';
            }
        }

        function selectCamera(ip) {
            document.getElementById('CAMERA_IP').value = ip;
            showToast('Selected Camera IP: ' + ip);
        }

        async function loadRecordings() {
            const list = document.getElementById('recordingsList');
            try {
                const res = await fetch('/api/recordings');
                const files = await res.json();
                if (files.length === 0) {
                    list.innerHTML = '<div style="text-align: center; color: var(--text-muted); padding: 20px;">No video segments found.</div>';
                    return;
                }
                list.innerHTML = files.map(f => `
                    <div class="rec-item">
                        <div class="rec-info">
                            <div class="rec-name">${f.filename}</div>
                            <div class="rec-meta">
                                ${f.size_mb} MB
                                <span class="rec-badge">${f.location}</span>
                            </div>
                        </div>
                        <button class="btn-play" onclick="playVideo('${f.filename}')">▶ Play</button>
                    </div>
                `).join('');
            } catch (err) {
                list.innerHTML = '<div style="text-align: center; color: var(--accent-red); padding: 20px;">Failed to load recordings.</div>';
            }
        }

        function playVideo(filename) {
            const playerContainer = document.getElementById('videoPlayerContainer');
            const player = document.getElementById('videoPlayer');
            playerContainer.style.display = 'block';
            player.src = '/api/video/' + encodeURIComponent(filename);
            playerContainer.scrollIntoView({ behavior: 'smooth' });
        }

        async function loadConfig() {
            try {
                const res = await fetch('/api/config');
                const config = await res.json();
                for (const key in config) {
                    const input = document.getElementById(key);
                    if (input) {
                        input.value = config[key];
                    }
                }
            } catch (err) {
                alert('Failed to load configuration: ' + err);
            }
        }

        async function saveConfig(e) {
            e.preventDefault();
            const keys = ['CAMERA_IP', 'RTSP_USER', 'RTSP_PASS', 'RTSP_PORT', 'RTSP_PATH',
                          'SMB_IP', 'SMB_SHARE', 'SMB_USER', 'SMB_PASS',
                          'LOCAL_TEMP_DIR', 'SEGMENT_DURATION', 'MAX_STORAGE_GB'];
            const config = {};
            keys.forEach(k => {
                const el = document.getElementById(k);
                if (el) config[k] = el.value;
            });

            try {
                const res = await fetch('/api/config', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(config)
                });
                const data = await res.json();
                if (data.success) {
                    showToast(data.message);
                    fetchStatus();
                }
            } catch (err) {
                alert('Failed to save config: ' + err);
            }
        }

        async function control(action) {
            document.getElementById('btnStart').disabled = true;
            document.getElementById('btnStop').disabled = true;
            try {
                await fetch('/api/' + action, { method: 'POST' });
                await fetchStatus();
            } catch (err) {
                alert('Action failed: ' + err);
            }
        }

        fetchStatus();
        setInterval(fetchStatus, 5000);
    </script>
</body>
</html>
"""

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8080, debug=False)
