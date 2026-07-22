from flask import Flask, jsonify, render_template_string, request
import subprocess
import os
import re
import signal
import time

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PID_FILE = os.path.join(BASE_DIR, "nvr.pid")
CONFIG_FILE = os.path.join(BASE_DIR, "config.sh")
SCRIPTS = ["record.sh", "upload.sh", "cleanup.sh"]

DEFAULT_CONFIG_KEYS = [
    "CAMERA_IP", "RTSP_USER", "RTSP_PASS", "RTSP_PORT", "RTSP_PATH",
    "SMB_IP", "SMB_SHARE", "SMB_USER", "SMB_PASS",
    "LOCAL_TEMP_DIR", "SEGMENT_DURATION", "MAX_STORAGE_GB"
]

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

@app.route("/api/config", methods=["GET"])
def api_get_config():
    return jsonify(parse_config())

@app.route("/api/config", methods=["POST"])
def api_save_config():
    data = request.json or {}
    save_config_file(data)
    
    # If running, restart services to apply new configuration
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
        body { background: var(--bg-color); color: var(--text-color); padding: 16px; max-width: 600px; margin: 0 auto; }
        h1 { font-size: 1.4rem; margin-bottom: 16px; text-align: center; color: var(--text-color); }
        .tabs { display: flex; border-bottom: 1px solid var(--border-color); margin-bottom: 16px; }
        .tab-btn { flex: 1; padding: 12px; background: none; border: none; color: var(--text-muted); font-size: 1rem; font-weight: 600; cursor: pointer; border-bottom: 2px solid transparent; }
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
        pre.logs { background: #090d16; color: #a7f3d0; padding: 12px; border-radius: 8px; font-family: monospace; font-size: 0.75rem; overflow-x: auto; white-space: pre-wrap; max-height: 200px; border: 1px solid var(--border-color); }
        .form-group { margin-bottom: 12px; }
        .form-group label { display: block; font-size: 0.8rem; color: var(--text-muted); margin-bottom: 4px; }
        .form-group input { width: 100%; padding: 10px; border-radius: 6px; border: 1px solid var(--border-color); background: var(--input-bg); color: var(--text-color); font-size: 0.9rem; }
        .section-title { font-size: 0.9rem; color: var(--accent-blue); font-weight: 600; margin: 12px 0 8px 0; border-bottom: 1px solid var(--border-color); padding-bottom: 4px; }
        .toast { position: fixed; bottom: 20px; left: 50%; transform: translateX(-50%); background: var(--accent-green); color: white; padding: 10px 20px; border-radius: 20px; font-weight: 600; display: none; z-index: 1000; box-shadow: 0 4px 12px rgba(0,0,0,0.3); }
    </style>
</head>
<body>
    <h1>📷 Termux NVR Controller</h1>

    <div class="tabs">
        <button class="tab-btn active" onclick="switchTab('dashboard')">Dashboard</button>
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

    <!-- SETTINGS TAB -->
    <div id="tab-settings" class="tab-content">
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
        function switchTab(tabName) {
            document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(content => content.classList.remove('active'));
            
            event.target.classList.add('active');
            document.getElementById('tab-' + tabName).classList.add('active');

            if (tabName === 'settings') {
                loadConfig();
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
