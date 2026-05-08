import csv
import json
import os
import queue
import subprocess
import threading
import time
import tkinter as tk
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from tkinter import scrolledtext, ttk
from urllib import error, request


SCRIPT_PATH = Path(__file__).resolve()
PI_DIR = SCRIPT_PATH.parent
PROJECT_ROOT = PI_DIR.parents[1]
BACKEND_DIR = PI_DIR / "HAR-backend"
LOG_DIR = BACKEND_DIR / "logs"

RESOURCE_LOG_PATH = os.getenv(
    "HAR_RESOURCE_LOG_PATH",
    str(LOG_DIR / "resource_diagnostics.jsonl"),
)
RESOURCE_CSV_PATH = os.getenv(
    "HAR_RESOURCE_CSV_PATH",
    str(LOG_DIR / "resource_diagnostics.csv"),
)
PROCESS_CSV_PATH = os.getenv(
    "HAR_PROCESS_RESOURCE_CSV_PATH",
    str(LOG_DIR / "resource_process_samples.csv"),
)
BACKEND_BASE_URL = os.getenv("HAR_BACKEND_URL", "http://127.0.0.1:3000")
FEATURE_KEYS = ("ax", "ay", "az", "gx", "gy", "gz", "mx", "my", "mz")
WINDOW_SIZE = 200

HZ = os.sysconf(os.sysconf_names.get("SC_CLK_TCK", "SC_CLK_TCK"))
PAGE_SIZE = os.sysconf("SC_PAGE_SIZE")


@dataclass
class ProcessSnapshot:
    pid: int
    ppid: int
    name: str
    role: str
    cmdline: str
    cwd: str
    total_jiffies: int
    rss_kb: int
    vms_kb: int
    threads: int
    fds: int
    read_bytes: int
    write_bytes: int


def read_text(path, default=""):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as file:
            return file.read()
    except Exception:
        return default


def run_command(command, timeout=3):
    try:
        proc = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except Exception as exc:
        return -1, repr(exc)


def safe_float(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


def safe_int(value, default=0):
    try:
        return int(value)
    except Exception:
        return default


def path_is_under(path, parent):
    try:
        Path(path).resolve().relative_to(parent.resolve())
        return True
    except Exception:
        return False


def parse_key_value_lines(text):
    values = {}

    for raw_line in text.splitlines():
        line = raw_line.strip()

        if not line or ":" not in line:
            continue

        key, value = line.split(":", 1)
        values[key.strip()] = value.strip()

    return values


def read_meminfo():
    info = {}

    for line in read_text("/proc/meminfo").splitlines():
        parts = line.replace(":", "").split()

        if len(parts) >= 2:
            info[parts[0]] = safe_int(parts[1])

    total = info.get("MemTotal", 0)
    available = info.get("MemAvailable", 0)
    used = max(0, total - available)
    swap_total = info.get("SwapTotal", 0)
    swap_free = info.get("SwapFree", 0)

    return {
        "total_kb": total,
        "available_kb": available,
        "used_kb": used,
        "used_percent": round((used / total) * 100.0, 2) if total else 0.0,
        "swap_total_kb": swap_total,
        "swap_used_kb": max(0, swap_total - swap_free),
        "raw": info,
    }


def read_proc_stat():
    first = read_text("/proc/stat").splitlines()[0].split()
    values = [safe_int(value) for value in first[1:]]
    total = sum(values)
    idle = values[3] + values[4] if len(values) > 4 else values[3]
    return total, idle


def cpu_percent(prev_total, prev_idle, total, idle):
    delta_total = total - prev_total
    delta_idle = idle - prev_idle

    if delta_total <= 0:
        return 0.0

    return round(((delta_total - delta_idle) / delta_total) * 100.0, 2)


def read_loadavg():
    parts = read_text("/proc/loadavg").split()

    return {
        "1m": safe_float(parts[0]) if len(parts) > 0 else 0.0,
        "5m": safe_float(parts[1]) if len(parts) > 1 else 0.0,
        "15m": safe_float(parts[2]) if len(parts) > 2 else 0.0,
    }


def read_temperature_sensors():
    sensors = {}

    for zone in sorted(Path("/sys/class/thermal").glob("thermal_zone*")):
        sensor_type = read_text(zone / "type", zone.name).strip() or zone.name
        raw_temp = read_text(zone / "temp").strip()

        if raw_temp:
            sensors[sensor_type] = round(safe_float(raw_temp) / 1000.0, 2)

    return sensors


def read_vcgencmd():
    commands = {
        "temperature": ["vcgencmd", "measure_temp"],
        "throttled": ["vcgencmd", "get_throttled"],
        "core_voltage": ["vcgencmd", "measure_volts", "core"],
        "arm_clock": ["vcgencmd", "measure_clock", "arm"],
        "core_clock": ["vcgencmd", "measure_clock", "core"],
        "v3d_clock": ["vcgencmd", "measure_clock", "v3d"],
        "arm_mem": ["vcgencmd", "get_mem", "arm"],
        "gpu_mem": ["vcgencmd", "get_mem", "gpu"],
    }
    result = {}

    code, _ = run_command(["bash", "-lc", "command -v vcgencmd >/dev/null 2>&1"], timeout=2)

    if code != 0:
        return {"available": False}

    result["available"] = True

    for key, command in commands.items():
        _, output = run_command(command, timeout=2)
        result[key] = output.strip()

    result["throttle_flags"] = decode_throttled(result.get("throttled", ""))
    return result


def decode_throttled(value):
    if "=" not in value:
        return {}

    raw = value.split("=", 1)[1].strip()

    try:
        flags = int(raw, 16)
    except Exception:
        return {}

    names = {
        0: "undervoltage_now",
        1: "frequency_capped_now",
        2: "throttled_now",
        3: "soft_temp_limit_now",
        16: "undervoltage_occurred",
        17: "frequency_capped_occurred",
        18: "throttled_occurred",
        19: "soft_temp_limit_occurred",
    }

    return {
        name: bool(flags & (1 << bit))
        for bit, name in names.items()
    }


def read_power_supply():
    supplies = {}

    for supply in sorted(Path("/sys/class/power_supply").glob("*")):
        if not supply.is_dir():
            continue

        values = {}

        for item in supply.glob("*"):
            if item.is_file():
                text = read_text(item).strip()

                if text:
                    values[item.name] = text

        supplies[supply.name] = values

    return supplies


def read_hwmon_power():
    sensors = {}

    for hwmon in sorted(Path("/sys/class/hwmon").glob("hwmon*")):
        name = read_text(hwmon / "name", hwmon.name).strip() or hwmon.name
        values = {}

        for pattern in ("power*_input", "curr*_input", "in*_input", "temp*_input"):
            for item in sorted(hwmon.glob(pattern)):
                raw = read_text(item).strip()

                if not raw:
                    continue

                label = read_text(hwmon / item.name.replace("_input", "_label")).strip()
                key = f"{item.name}:{label}" if label else item.name
                values[key] = raw

        if values:
            sensors[name] = values

    return sensors


def read_network_totals():
    interfaces = {}

    for line in read_text("/proc/net/dev").splitlines()[2:]:
        if ":" not in line:
            continue

        name, rest = line.split(":", 1)
        parts = rest.split()

        if len(parts) >= 16:
            interfaces[name.strip()] = {
                "rx_bytes": safe_int(parts[0]),
                "tx_bytes": safe_int(parts[8]),
            }

    return interfaces


def read_disk_totals():
    totals = {
        "read_sectors": 0,
        "write_sectors": 0,
    }

    for line in read_text("/proc/diskstats").splitlines():
        parts = line.split()

        if len(parts) < 14:
            continue

        device = parts[2]

        if device.startswith(("loop", "ram")):
            continue

        totals["read_sectors"] += safe_int(parts[5])
        totals["write_sectors"] += safe_int(parts[9])

    totals["read_mb"] = round(totals["read_sectors"] * 512 / (1024 * 1024), 2)
    totals["write_mb"] = round(totals["write_sectors"] * 512 / (1024 * 1024), 2)
    return totals


def read_cmdline(pid):
    raw = read_text(f"/proc/{pid}/cmdline")
    cmdline = raw.replace("\x00", " ").strip()

    if cmdline:
        return cmdline

    return read_text(f"/proc/{pid}/comm").strip()


def read_cwd(pid):
    try:
        return os.readlink(f"/proc/{pid}/cwd")
    except Exception:
        return ""


def detect_role(cmdline, cwd):
    lower_cmd = cmdline.lower()
    cwd_under_backend = bool(cwd) and path_is_under(cwd, BACKEND_DIR)
    cwd_under_project = bool(cwd) and path_is_under(cwd, PROJECT_ROOT)

    if "resource_diagnostics_gui.py" in lower_cmd:
        return "monitor"
    if "tdma_hub_gui.py" in lower_cmd:
        return "tdma_gui"
    if "tdma_hub.py" in lower_cmd:
        return "tdma_hub"
    if "tdma_formatted" in lower_cmd:
        return "tdma_formatter"
    if (
        "har-backend/app.py" in lower_cmd
        or "har-backend\\app.py" in lower_cmd
        or (cwd_under_backend and "app.py" in lower_cmd and "python" in lower_cmd)
    ):
        return "har_backend"
    if (
        ("flask" in lower_cmd or "gunicorn" in lower_cmd or "uvicorn" in lower_cmd)
        and (cwd_under_backend or cwd_under_project or "har-backend" in lower_cmd)
    ):
        return "backend_server"

    return "project_process"


def is_target_process(pid, cmdline, cwd):
    if pid == os.getpid():
        return False

    role = detect_role(cmdline, cwd)

    if role == "monitor":
        return False

    lower_cmd = cmdline.lower()
    cwd_under_project = bool(cwd) and path_is_under(cwd, PROJECT_ROOT)
    cwd_under_backend = bool(cwd) and path_is_under(cwd, BACKEND_DIR)
    is_python = "python" in lower_cmd

    if role in ("tdma_gui", "tdma_hub", "tdma_formatter", "har_backend", "backend_server"):
        return True

    if is_python and cwd_under_backend and ("app.py" in lower_cmd or "flask" in lower_cmd):
        return True

    if is_python and cwd_under_project and ("tdma" in lower_cmd or "har" in lower_cmd):
        return True

    return False


def read_proc_snapshot(pid):
    cmdline = read_cmdline(pid)
    cwd = read_cwd(pid)

    if not is_target_process(pid, cmdline, cwd):
        return None

    stat = read_text(f"/proc/{pid}/stat")

    if ") " not in stat:
        return None

    before, after = stat.rsplit(") ", 1)
    name = before.split("(", 1)[-1]
    fields = after.split()

    if len(fields) < 18:
        return None

    ppid = safe_int(fields[1])
    utime = safe_int(fields[11])
    stime = safe_int(fields[12])
    status = parse_key_value_lines(read_text(f"/proc/{pid}/status"))
    rss_kb = safe_int(status.get("VmRSS", "0 kB").split()[0])
    vms_kb = safe_int(status.get("VmSize", "0 kB").split()[0])
    threads = safe_int(status.get("Threads", "0"))

    try:
        fds = len(os.listdir(f"/proc/{pid}/fd"))
    except Exception:
        fds = 0

    io_values = {}

    for line in read_text(f"/proc/{pid}/io").splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            io_values[key.strip()] = safe_int(value.strip())

    return ProcessSnapshot(
        pid=pid,
        ppid=ppid,
        name=name,
        role=detect_role(cmdline, cwd),
        cmdline=cmdline,
        cwd=cwd,
        total_jiffies=utime + stime,
        rss_kb=rss_kb,
        vms_kb=vms_kb,
        threads=threads,
        fds=fds,
        read_bytes=io_values.get("read_bytes", 0),
        write_bytes=io_values.get("write_bytes", 0),
    )


def discover_processes():
    snapshots = []

    for entry in sorted(Path("/proc").iterdir(), key=lambda item: item.name):
        if not entry.name.isdigit():
            continue

        snapshot = read_proc_snapshot(safe_int(entry.name))

        if snapshot is not None:
            snapshots.append(snapshot)

    return snapshots


def flatten_for_csv(value, prefix="", output=None):
    if output is None:
        output = {}

    if isinstance(value, dict):
        for key, item in value.items():
            next_prefix = f"{prefix}.{key}" if prefix else str(key)
            flatten_for_csv(item, next_prefix, output)
    elif isinstance(value, list):
        output[prefix] = json.dumps(value, ensure_ascii=False, default=str)
    else:
        output[prefix] = value

    return output


def build_synthetic_predict_payload():
    windows_by_node = {}

    for node_id in (1, 2, 3):
        rows = []

        for index in range(WINDOW_SIZE):
            rows.append({
                "ax": 0.01 * node_id,
                "ay": 0.02 * node_id,
                "az": 9.80 + (index % 5) * 0.001,
                "gx": 0.001 * (index % 7),
                "gy": 0.001 * (index % 11),
                "gz": 0.001 * (index % 13),
                "mx": 10.0 + node_id,
                "my": -5.0 + node_id,
                "mz": 3.0,
            })

        windows_by_node[str(node_id)] = rows

    return {"windows_by_node": windows_by_node}


def post_json(url, payload, timeout=15.0):
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with request.urlopen(req, timeout=timeout) as response:
        raw = response.read().decode("utf-8", errors="ignore")
        return response.status, json.loads(raw) if raw else {}


def get_json(url, timeout=5.0):
    with request.urlopen(url, timeout=timeout) as response:
        raw = response.read().decode("utf-8", errors="ignore")
        return response.status, json.loads(raw) if raw else {}


class ResourceDiagnosticsGui:
    def __init__(self, root):
        self.root = root
        self.root.title("HAR Resource & Power Diagnostics")
        self.root.geometry("1240x780")

        self.events = queue.Queue()
        self.stop_event = threading.Event()
        self.worker_thread = None
        self.latest_sample = None
        self.session_active = False

        self.scenario_var = tk.StringVar(value="idle")
        self.duration_var = tk.StringVar(value="60")
        self.interval_var = tk.StringVar(value="1.0")
        self.backend_requests_var = tk.StringVar(value="5")
        self.status_var = tk.StringVar(value="Ready")
        self.system_var = tk.StringVar(value="System: -")
        self.target_var = tk.StringVar(value="Targets: -")
        self.power_var = tk.StringVar(value="Power: -")

        self.build_ui()
        self.root.after(100, self.drain_events)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def build_ui(self):
        main = ttk.Frame(self.root, padding=10)
        main.pack(fill=tk.BOTH, expand=True)

        controls = ttk.Frame(main)
        controls.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(controls, text="Scenario").pack(side=tk.LEFT)
        scenario_box = ttk.Combobox(
            controls,
            values=("idle", "single_sensor", "three_sensors", "custom"),
            textvariable=self.scenario_var,
            state="readonly",
            width=16,
        )
        scenario_box.pack(side=tk.LEFT, padx=(4, 12))

        ttk.Label(controls, text="Duration s").pack(side=tk.LEFT)
        ttk.Spinbox(
            controls,
            from_=5,
            to=3600,
            increment=5,
            width=7,
            textvariable=self.duration_var,
        ).pack(side=tk.LEFT, padx=(4, 12))

        ttk.Label(controls, text="Interval s").pack(side=tk.LEFT)
        ttk.Spinbox(
            controls,
            from_=0.2,
            to=30.0,
            increment=0.2,
            width=7,
            textvariable=self.interval_var,
        ).pack(side=tk.LEFT, padx=(4, 12))

        ttk.Label(controls, text="Predict reqs").pack(side=tk.LEFT)
        ttk.Spinbox(
            controls,
            from_=1,
            to=200,
            increment=1,
            width=6,
            textvariable=self.backend_requests_var,
        ).pack(side=tk.LEFT, padx=(4, 12))

        ttk.Button(controls, text="Start Test", command=self.start_selected).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(controls, text="Idle", command=lambda: self.start_named("idle")).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(controls, text="Single Sensor", command=lambda: self.start_named("single_sensor")).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(controls, text="Three Sensors", command=lambda: self.start_named("three_sensors")).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(controls, text="Stop", command=self.stop_test).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(controls, text="Refresh", command=lambda: self.async_call(self.collect_once)).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(controls, text="Health Ping", command=lambda: self.async_call(self.backend_health_ping)).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(controls, text="Predict Benchmark", command=lambda: self.async_call(self.backend_predict_benchmark)).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(controls, text="Export CSV", command=lambda: self.async_call(self.export_csv)).pack(side=tk.LEFT)

        ttk.Label(main, textvariable=self.status_var, font=("TkDefaultFont", 11, "bold")).pack(anchor=tk.W)
        ttk.Label(main, textvariable=self.system_var).pack(anchor=tk.W)
        ttk.Label(main, textvariable=self.target_var).pack(anchor=tk.W)
        ttk.Label(main, textvariable=self.power_var).pack(anchor=tk.W, pady=(0, 8))

        content = ttk.PanedWindow(main, orient=tk.HORIZONTAL)
        content.pack(fill=tk.BOTH, expand=True)

        table_frame = ttk.Frame(content)
        terminal_frame = ttk.Frame(content)
        content.add(table_frame, weight=3)
        content.add(terminal_frame, weight=2)

        columns = (
            "pid",
            "role",
            "cpu",
            "rss",
            "vms",
            "threads",
            "fds",
            "read",
            "write",
            "cmd",
        )
        self.process_table = ttk.Treeview(table_frame, columns=columns, show="headings", height=22)
        headings = {
            "pid": "PID",
            "role": "Role",
            "cpu": "CPU %",
            "rss": "RSS MB",
            "vms": "VMS MB",
            "threads": "Threads",
            "fds": "FDs",
            "read": "Read KB/s",
            "write": "Write KB/s",
            "cmd": "Command",
        }

        for column in columns:
            self.process_table.heading(column, text=headings[column])

        self.process_table.column("pid", width=70, anchor=tk.E)
        self.process_table.column("role", width=120)
        self.process_table.column("cpu", width=80, anchor=tk.E)
        self.process_table.column("rss", width=85, anchor=tk.E)
        self.process_table.column("vms", width=85, anchor=tk.E)
        self.process_table.column("threads", width=80, anchor=tk.E)
        self.process_table.column("fds", width=60, anchor=tk.E)
        self.process_table.column("read", width=90, anchor=tk.E)
        self.process_table.column("write", width=90, anchor=tk.E)
        self.process_table.column("cmd", width=360)

        table_scroll = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.process_table.yview)
        self.process_table.configure(yscrollcommand=table_scroll.set)
        self.process_table.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        table_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        ttk.Label(terminal_frame, text="Resource Terminal", font=("TkDefaultFont", 12, "bold")).pack(anchor=tk.W)
        self.terminal = scrolledtext.ScrolledText(
            terminal_frame,
            wrap=tk.WORD,
            height=30,
            state=tk.DISABLED,
            font=("DejaVu Sans Mono", 10),
        )
        self.terminal.pack(fill=tk.BOTH, expand=True, pady=(6, 0))

        self.log("Resource diagnostics ready.")
        self.log(f"JSONL: {RESOURCE_LOG_PATH}")
        self.log(f"CSV: {RESOURCE_CSV_PATH}")
        self.log("CPU is measured between samples, so the first sample is expected to show 0%.")
        self.log("Power note: true watt/current needs hardware support; this tool records Pi throttle, voltage, clocks, temperature and any sysfs power sensors.")

    def async_call(self, fn, *args):
        thread = threading.Thread(target=fn, args=args, daemon=True)
        thread.start()

    def log_from_thread(self, message):
        self.events.put(("log", message))

    def status_from_thread(self, message):
        self.events.put(("status", message))

    def sample_from_thread(self, sample):
        self.events.put(("sample", sample))

    def log(self, message):
        timestamp = time.strftime("%H:%M:%S")
        self.terminal.configure(state=tk.NORMAL)
        self.terminal.insert(tk.END, f"[{timestamp}] {message}\n")
        self.terminal.see(tk.END)
        self.terminal.configure(state=tk.DISABLED)

        line_count = int(self.terminal.index("end-1c").split(".")[0])

        if line_count > 1600:
            self.terminal.configure(state=tk.NORMAL)
            self.terminal.delete("1.0", "200.0")
            self.terminal.configure(state=tk.DISABLED)

    def read_float_var(self, var, default, lower, upper):
        value = safe_float(str(var.get()).strip(), default)
        return max(lower, min(upper, value))

    def read_int_var(self, var, default, lower, upper):
        value = safe_int(str(var.get()).strip(), default)
        return max(lower, min(upper, value))

    def start_named(self, scenario):
        self.scenario_var.set(scenario)
        self.start_selected()

    def start_selected(self):
        if self.session_active:
            self.log("A resource test is already running.")
            return

        scenario = self.scenario_var.get()
        duration_s = self.read_int_var(self.duration_var, 60, 1, 86400)
        interval_s = self.read_float_var(self.interval_var, 1.0, 0.2, 60.0)
        self.stop_event.clear()
        self.session_active = True
        self.worker_thread = threading.Thread(
            target=self.run_session,
            args=(scenario, duration_s, interval_s),
            daemon=True,
        )
        self.worker_thread.start()

    def stop_test(self):
        if not self.session_active:
            self.log("No active resource test.")
            return

        self.stop_event.set()
        self.log("Stopping resource test...")

    def collect_once(self):
        sample = self.collect_sample("manual_refresh", 0, 0, 0.0, None, None)
        self.sample_from_thread(sample)
        self.write_resource_log("resource_sample", sample)
        self.log_from_thread("Manual resource sample collected.")

    def backend_health_ping(self):
        url = f"{BACKEND_BASE_URL.rstrip('/')}/health"
        started = time.perf_counter()

        try:
            status, payload = get_json(url, timeout=5.0)
            latency_ms = round((time.perf_counter() - started) * 1000.0, 2)
            self.log_from_thread(f"Backend health {status} in {latency_ms} ms: {payload.get('status')}")
            self.write_resource_log("backend_health_ping", {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "url": url,
                "status_code": status,
                "latency_ms": latency_ms,
                "response": payload,
            })
        except Exception as exc:
            latency_ms = round((time.perf_counter() - started) * 1000.0, 2)
            self.log_from_thread(f"Backend health failed after {latency_ms} ms: {exc}")
            self.write_resource_log("backend_health_error", {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "url": url,
                "latency_ms": latency_ms,
                "error": repr(exc),
            })

    def backend_predict_benchmark(self):
        if self.session_active:
            self.log_from_thread("Stop the active resource test before running backend benchmark.")
            return

        request_count = self.read_int_var(self.backend_requests_var, 5, 1, 500)
        url = f"{BACKEND_BASE_URL.rstrip('/')}/predict"
        payload = build_synthetic_predict_payload()
        self.session_active = True
        self.status_from_thread("Running: backend_predict_benchmark")
        self.log_from_thread(
            f"Backend predict benchmark started: {request_count} requests to {url}."
        )

        try:
            baseline = self.collect_sample(
                "backend_predict_benchmark",
                0,
                request_count,
                0.0,
                None,
                None,
            )
            self.write_resource_log("resource_sample", baseline)
            time.sleep(0.25)

            latencies = []
            errors = 0
            labels = []
            started_at = time.perf_counter()

            for index in range(1, request_count + 1):
                request_started = time.perf_counter()

                try:
                    status, response_payload = post_json(url, payload, timeout=30.0)
                    latency_ms = round((time.perf_counter() - request_started) * 1000.0, 2)
                    latencies.append(latency_ms)
                    labels.append(response_payload.get("activity"))
                    self.log_from_thread(
                        f"Predict {index}/{request_count}: {status} {latency_ms} ms "
                        f"{response_payload.get('activity')}"
                    )
                    self.write_resource_log("backend_predict_request", {
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "request_index": index,
                        "status_code": status,
                        "latency_ms": latency_ms,
                        "response": response_payload,
                    })
                except error.HTTPError as exc:
                    errors += 1
                    raw = exc.read().decode("utf-8", errors="ignore")
                    latency_ms = round((time.perf_counter() - request_started) * 1000.0, 2)
                    self.log_from_thread(f"Predict {index}/{request_count}: HTTP {exc.code} {latency_ms} ms {raw[:160]}")
                    self.write_resource_log("backend_predict_error", {
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "request_index": index,
                        "status_code": exc.code,
                        "latency_ms": latency_ms,
                        "error": raw,
                    })
                except Exception as exc:
                    errors += 1
                    latency_ms = round((time.perf_counter() - request_started) * 1000.0, 2)
                    self.log_from_thread(f"Predict {index}/{request_count}: failed {latency_ms} ms {exc}")
                    self.write_resource_log("backend_predict_error", {
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "request_index": index,
                        "latency_ms": latency_ms,
                        "error": repr(exc),
                    })

            elapsed_s = time.perf_counter() - started_at
            after = self.collect_sample(
                "backend_predict_benchmark",
                request_count,
                request_count,
                elapsed_s,
                baseline["_raw"],
                elapsed_s,
            )
            self.sample_from_thread(after)
            self.write_resource_log("resource_sample", after)

            summary = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "scenario": "backend_predict_benchmark",
                "requests": request_count,
                "successes": len(latencies),
                "errors": errors,
                "duration_s": round(elapsed_s, 3),
                "avg_latency_ms": self.avg_value(latencies),
                "max_latency_ms": self.max_value(latencies),
                "target_cpu_percent_over_benchmark": after["target_totals"]["cpu_percent"],
                "target_rss_mb": after["target_totals"]["rss_mb"],
                "labels": labels,
            }
            self.write_resource_log("backend_predict_summary", summary)
            self.log_from_thread(
                f"Backend benchmark done: avg={summary['avg_latency_ms']} ms, "
                f"max={summary['max_latency_ms']} ms, backend CPU window={summary['target_cpu_percent_over_benchmark']}%."
            )
        finally:
            self.status_from_thread("Ready")
            self.session_active = False

    def run_session(self, scenario, duration_s, interval_s):
        self.log_from_thread(
            f"Started {scenario} resource test for {duration_s}s at {interval_s}s interval."
        )
        self.status_from_thread(f"Running: {scenario}")

        previous = None
        rows = []
        started_at = time.monotonic()
        sample_index = 0

        while not self.stop_event.is_set():
            elapsed_s = time.monotonic() - started_at

            if elapsed_s > duration_s:
                break

            sample_index += 1
            sample = self.collect_sample(
                scenario,
                sample_index,
                duration_s,
                elapsed_s,
                previous,
                interval_s,
            )
            previous = sample["_raw"]
            rows.append(sample)
            self.sample_from_thread(sample)
            self.write_resource_log("resource_sample", sample)

            sleep_until = time.monotonic() + interval_s

            while time.monotonic() < sleep_until:
                if self.stop_event.is_set():
                    break

                time.sleep(0.05)

        summary = self.build_summary(scenario, rows)
        self.write_resource_log("resource_summary", summary)
        self.log_from_thread(
            f"Finished {scenario}: avg target CPU={summary['target_cpu_avg_percent']}%, "
            f"max RSS={summary['target_rss_max_mb']} MB, max temp={summary['max_temp_c']} C."
        )
        self.status_from_thread("Ready")
        self.session_active = False

    def collect_sample(self, scenario, sample_index, duration_s, elapsed_s, previous, interval_s):
        timestamp = datetime.now(timezone.utc).isoformat()
        now = time.monotonic()
        system_total, system_idle = read_proc_stat()
        processes = discover_processes()
        previous = previous or {}
        previous_time = previous.get("monotonic")
        previous_processes = previous.get("processes", {})
        previous_system = previous.get("system_cpu")
        wall_delta = max(0.001, now - previous_time) if previous_time else None

        if previous_system:
            system_cpu = cpu_percent(
                previous_system["total"],
                previous_system["idle"],
                system_total,
                system_idle,
            )
        else:
            system_cpu = 0.0

        process_rows = []

        for proc in processes:
            prev_proc = previous_processes.get(proc.pid)

            if prev_proc and wall_delta:
                cpu = round(((proc.total_jiffies - prev_proc["jiffies"]) / HZ) / wall_delta * 100.0, 2)
                read_rate = round(max(0, proc.read_bytes - prev_proc["read_bytes"]) / 1024.0 / wall_delta, 2)
                write_rate = round(max(0, proc.write_bytes - prev_proc["write_bytes"]) / 1024.0 / wall_delta, 2)
            else:
                cpu = 0.0
                read_rate = 0.0
                write_rate = 0.0

            process_rows.append({
                "pid": proc.pid,
                "ppid": proc.ppid,
                "name": proc.name,
                "role": proc.role,
                "cpu_percent": cpu,
                "rss_kb": proc.rss_kb,
                "rss_mb": round(proc.rss_kb / 1024.0, 2),
                "vms_kb": proc.vms_kb,
                "vms_mb": round(proc.vms_kb / 1024.0, 2),
                "threads": proc.threads,
                "fds": proc.fds,
                "read_kb_s": read_rate,
                "write_kb_s": write_rate,
                "cmdline": proc.cmdline,
                "cwd": proc.cwd,
            })

        target_totals = {
            "process_count": len(process_rows),
            "cpu_percent": round(sum(row["cpu_percent"] for row in process_rows), 2),
            "rss_mb": round(sum(row["rss_kb"] for row in process_rows) / 1024.0, 2),
            "vms_mb": round(sum(row["vms_kb"] for row in process_rows) / 1024.0, 2),
            "threads": sum(row["threads"] for row in process_rows),
            "fds": sum(row["fds"] for row in process_rows),
            "read_kb_s": round(sum(row["read_kb_s"] for row in process_rows), 2),
            "write_kb_s": round(sum(row["write_kb_s"] for row in process_rows), 2),
        }

        mem = read_meminfo()
        temps = read_temperature_sensors()
        vcgen = read_vcgencmd()
        power_supply = read_power_supply()
        hwmon_power = read_hwmon_power()

        raw_processes = {
            proc.pid: {
                "jiffies": proc.total_jiffies,
                "read_bytes": proc.read_bytes,
                "write_bytes": proc.write_bytes,
            }
            for proc in processes
        }

        sample = {
            "timestamp": timestamp,
            "scenario": scenario,
            "sample_index": sample_index,
            "duration_s": duration_s,
            "elapsed_s": round(elapsed_s, 3),
            "interval_s": interval_s,
            "system": {
                "cpu_percent": system_cpu,
                "loadavg": read_loadavg(),
                "memory": mem,
                "temperatures_c": temps,
                "vcgencmd": vcgen,
                "power_supply": power_supply,
                "hwmon_power": hwmon_power,
                "network": read_network_totals(),
                "disk": read_disk_totals(),
            },
            "target_totals": target_totals,
            "processes": sorted(process_rows, key=lambda row: row["cpu_percent"], reverse=True),
            "_raw": {
                "monotonic": now,
                "system_cpu": {
                    "total": system_total,
                    "idle": system_idle,
                },
                "processes": raw_processes,
            },
        }

        return sample

    def numeric_values(self, rows, getter):
        values = []

        for row in rows:
            value = getter(row)

            if isinstance(value, (int, float)):
                values.append(float(value))

        return values

    def avg_value(self, values):
        return round(sum(values) / len(values), 2) if values else 0.0

    def max_value(self, values):
        return round(max(values), 2) if values else 0.0

    def build_summary(self, scenario, rows):
        cpu_values = self.numeric_values(rows, lambda row: row["target_totals"]["cpu_percent"])
        rss_values = self.numeric_values(rows, lambda row: row["target_totals"]["rss_mb"])
        system_cpu_values = self.numeric_values(rows, lambda row: row["system"]["cpu_percent"])
        mem_values = self.numeric_values(rows, lambda row: row["system"]["memory"]["used_percent"])
        temp_values = []

        for row in rows:
            temp_values.extend([
                value for value in row["system"]["temperatures_c"].values()
                if isinstance(value, (int, float))
            ])

        role_cpu = {}
        role_rss = {}

        for row in rows:
            for proc in row["processes"]:
                role_cpu.setdefault(proc["role"], []).append(proc["cpu_percent"])
                role_rss.setdefault(proc["role"], []).append(proc["rss_mb"])

        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "scenario": scenario,
            "samples": len(rows),
            "target_cpu_avg_percent": self.avg_value(cpu_values),
            "target_cpu_max_percent": self.max_value(cpu_values),
            "target_rss_avg_mb": self.avg_value(rss_values),
            "target_rss_max_mb": self.max_value(rss_values),
            "system_cpu_avg_percent": self.avg_value(system_cpu_values),
            "system_cpu_max_percent": self.max_value(system_cpu_values),
            "system_mem_avg_percent": self.avg_value(mem_values),
            "system_mem_max_percent": self.max_value(mem_values),
            "max_temp_c": self.max_value(temp_values),
            "role_cpu_avg_percent": {
                role: self.avg_value(values)
                for role, values in role_cpu.items()
            },
            "role_rss_max_mb": {
                role: self.max_value(values)
                for role, values in role_rss.items()
            },
        }

    def write_resource_log(self, status, payload):
        try:
            path = Path(RESOURCE_LOG_PATH)
            path.parent.mkdir(parents=True, exist_ok=True)
            serializable = dict(payload)
            serializable.pop("_raw", None)
            entry = {
                "status": status,
                **serializable,
            }

            with open(path, "a", encoding="utf-8") as file:
                file.write(json.dumps(entry, ensure_ascii=False, default=str))
                file.write("\n")
        except Exception as exc:
            self.log_from_thread(f"Resource log write failed: {exc}")

    def export_csv(self):
        log_path = Path(RESOURCE_LOG_PATH)

        if not log_path.exists():
            self.log_from_thread(f"No resource log yet: {log_path}")
            return

        rows = []
        process_rows = []

        try:
            with open(log_path, "r", encoding="utf-8") as file:
                for line in file:
                    line = line.strip()

                    if not line:
                        continue

                    item = json.loads(line)
                    rows.append(flatten_for_csv(item))

                    if item.get("status") == "resource_sample":
                        base = {
                            "timestamp": item.get("timestamp"),
                            "scenario": item.get("scenario"),
                            "sample_index": item.get("sample_index"),
                            "elapsed_s": item.get("elapsed_s"),
                        }

                        for proc in item.get("processes", []):
                            process_rows.append({
                                **base,
                                **proc,
                            })

            self.write_csv(Path(RESOURCE_CSV_PATH), rows)
            self.write_csv(Path(PROCESS_CSV_PATH), process_rows)
            self.log_from_thread(f"CSV exported: {RESOURCE_CSV_PATH}")
            self.log_from_thread(f"Process CSV exported: {PROCESS_CSV_PATH}")
        except Exception as exc:
            self.log_from_thread(f"CSV export failed: {exc}")

    def write_csv(self, path, rows):
        if not rows:
            return

        path.parent.mkdir(parents=True, exist_ok=True)
        fieldnames = sorted({key for row in rows for key in row})

        with open(path, "w", encoding="utf-8", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    def render_sample(self, sample):
        self.latest_sample = sample
        system = sample["system"]
        totals = sample["target_totals"]
        mem = system["memory"]
        temps = system["temperatures_c"]
        max_temp = max(temps.values()) if temps else None
        throttle = system["vcgencmd"].get("throttle_flags", {})
        throttle_now = [
            name for name, active in throttle.items()
            if active and name.endswith("_now")
        ]

        self.system_var.set(
            f"System: CPU {system['cpu_percent']}% | "
            f"Mem {mem['used_percent']}% | "
            f"Load {system['loadavg']['1m']}/{system['loadavg']['5m']}/{system['loadavg']['15m']} | "
            f"Temp {max_temp if max_temp is not None else '-'} C"
        )
        self.target_var.set(
            f"Targets: {totals['process_count']} procs | CPU {totals['cpu_percent']}% | "
            f"RSS {totals['rss_mb']} MB | Threads {totals['threads']} | FDs {totals['fds']}"
        )
        self.power_var.set(
            f"Power/thermal: throttle_now={throttle_now or '-'} | "
            f"vcgencmd={'yes' if system['vcgencmd'].get('available') else 'no'} | "
            f"power_sensors={len(system['power_supply']) + len(system['hwmon_power'])}"
        )

        for item in self.process_table.get_children():
            self.process_table.delete(item)

        for proc in sample["processes"]:
            self.process_table.insert(
                "",
                tk.END,
                values=(
                    proc["pid"],
                    proc["role"],
                    proc["cpu_percent"],
                    proc["rss_mb"],
                    proc["vms_mb"],
                    proc["threads"],
                    proc["fds"],
                    proc["read_kb_s"],
                    proc["write_kb_s"],
                    proc["cmdline"][:120],
                ),
            )

    def drain_events(self):
        try:
            while True:
                event = self.events.get_nowait()
                kind = event[0]

                if kind == "log":
                    self.log(event[1])
                elif kind == "status":
                    self.status_var.set(event[1])
                elif kind == "sample":
                    self.render_sample(event[1])
        except queue.Empty:
            pass

        self.root.after(100, self.drain_events)

    def on_close(self):
        self.stop_event.set()
        self.root.destroy()


def main():
    root = tk.Tk()
    ResourceDiagnosticsGui(root)
    root.mainloop()


if __name__ == "__main__":
    main()
