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
    # Also kill any leftover ffmpeg or script processes
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
            # Look for line with available blocks
            # e.g., 1024000 blocks of size 1024. 512000 blocks available
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
        }
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
        body { background: var(--bg-color); color: var(--text-color); padding: 20px; max-width: 600px; margin: 0 auto; }
        h1 { font-size: 1.5rem; margin-bottom: 20px; text-align: center; color: var(--text-color); }
        .card { background: var(--card-bg); border-radius: 12px; padding: 16px; margin-bottom: 16px; border: 1px solid var(--border-color); }
        .status-badge { display: inline-block; padding: 6px 12px; border-radius: 20px; font-weight: bold; font-size: 0.9rem; text-transform: uppercase; }
        .status-running { background: rgba(34, 197, 94, 0.2); color: var(--accent-green); border: 1px solid var(--accent-green); }
        .status-stopped { background: rgba(239, 68, 68, 0.2); color: var(--accent-red); border: 1px solid var(--accent-red); }
        .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 12px; }
        .stat-item { background: rgba(0,0,0,0.2); padding: 12px; border-radius: 8px; }
        .stat-label { font-size: 0.75rem; color: var(--text-muted); text-transform: uppercase; margin-bottom: 4px; }
        .stat-value { font-size: 1rem; font-weight: 600; word-break: break-word; }
        .btn-group { display: flex; gap: 12px; margin-top: 16px; }
        button { flex: 1; padding: 14px; border: none; border-radius: 8px; font-size: 1rem; font-weight: bold; cursor: pointer; transition: opacity 0.2s; }
        button:disabled { opacity: 0.5; cursor: not-allowed; }
        .btn-start { background: var(--accent-green); color: white; }
        .btn-stop { background: var(--accent-red); color: white; }
        pre.logs { background: #090d16; color: #a7f3d0; padding: 12px; border-radius: 8px; font-family: monospace; font-size: 0.8rem; overflow-x: auto; white-space: pre-wrap; max-height: 200px; border: 1px solid var(--border-color); }
    </style>
</head>
<body>
    <h1>📷 Termux NVR Dashboard</h1>
    
    <div class="card">
        <div style="display: flex; justify-content: space-between; align-items: center;">
            <span style="font-weight: 600;">Status</span>
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
            <button id="btnStart" class="btn-start" onclick="control('start')">Start NVR</button>
            <button id="btnStop" class="btn-stop" onclick="control('stop')">Stop NVR</button>
        </div>
    </div>

    <div class="card">
        <div class="stat-label" style="margin-bottom: 8px;">Recent System Logs (Last 10 Lines)</div>
        <pre id="logOutput" class="logs">Loading logs...</pre>
    </div>

    <script>
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
