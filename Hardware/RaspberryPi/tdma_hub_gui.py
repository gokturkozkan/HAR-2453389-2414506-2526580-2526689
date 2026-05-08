import csv
import json
import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from tkinter import scrolledtext, ttk
from urllib import error, request

import serial

import tdma_hub as hub


NODE_MACS = {
    1: "08:A6:F7:47:4C:CE",
    2: "94:54:C5:E7:E4:1A",
    3: "94:54:C5:E7:E7:16",
}

DIAGNOSTIC_LOG_PATH = os.getenv(
    "BT_DIAGNOSTIC_LOG_PATH",
    os.path.join(os.path.dirname(__file__), "HAR-backend", "logs", "bluetooth_diagnostics.jsonl"),
)
DIAGNOSTIC_CSV_PATH = os.getenv(
    "BT_DIAGNOSTIC_CSV_PATH",
    os.path.join(os.path.dirname(__file__), "HAR-backend", "logs", "bluetooth_diagnostics.csv"),
)


@dataclass
class NodeState:
    node_id: int
    port: str
    name: str
    mac: str
    ser: object = None
    status: str = "Closed"
    errors: int = 0
    latest_line: str = ""
    latest_sample: dict = field(default_factory=dict)


class TdmaHubGui:
    def __init__(self, root):
        self.root = root
        self.root.title("HAR TDMA Bluetooth Hub")
        self.root.geometry("1180x720")

        self.nodes = {
            node_id: NodeState(
                node_id,
                hub.NODE_PORTS[node_id],
                hub.NODE_NAMES[node_id],
                NODE_MACS[node_id],
            )
            for node_id in (1, 2, 3)
        }

        self.lock = threading.RLock()
        self.events = queue.Queue()
        self.receiving = False
        self.receiver_thread = None
        self.node_windows = {
            node_id: deque(maxlen=hub.WINDOW_SIZE)
            for node_id in self.nodes
        }
        self.rows_since_prediction = 0
        self.last_prediction = "WAITING"
        self.last_notice_at = {}

        self.status_vars = {}
        self.detail_vars = {}
        self.sample_vars = {}
        self.diagnostics_window = None
        self.diag_terminal = None
        self.diag_vars = {}
        self.diag_sample_count_var = tk.StringVar(value="30")
        self.diag_interval_var = tk.StringVar(value="100")
        self.diag_test_lock = threading.Lock()

        self.build_ui()
        self.root.after(80, self.drain_events)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def build_ui(self):
        root_frame = ttk.Frame(self.root, padding=10)
        root_frame.pack(fill=tk.BOTH, expand=True)

        left = ttk.Frame(root_frame)
        left.pack(side=tk.LEFT, fill=tk.Y)

        controls = ttk.Frame(left)
        controls.pack(fill=tk.X, pady=(0, 10))

        ttk.Button(controls, text="Rebind rfcomm", command=self.rebind_rfcomm).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        ttk.Button(controls, text="Diagnostics", command=self.open_diagnostics_window).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        ttk.Button(controls, text="Resource Monitor", command=self.launch_resource_monitor).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        ttk.Button(controls, text="Start Receiving Data", command=self.start_receiving).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        ttk.Button(controls, text="Stop", command=self.stop_receiving).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        ttk.Button(controls, text="Clear Terminal", command=self.clear_terminal).pack(
            side=tk.LEFT
        )

        self.prediction_var = tk.StringVar(value="Prediction: WAITING")
        self.window_var = tk.StringVar(value=f"Window: 0/{hub.WINDOW_SIZE}")
        ttk.Label(left, textvariable=self.prediction_var, font=("TkDefaultFont", 12, "bold")).pack(
            anchor=tk.W, pady=(0, 4)
        )
        ttk.Label(left, textvariable=self.window_var).pack(anchor=tk.W, pady=(0, 10))

        for node_id in (1, 2, 3):
            self.build_node_card(left, node_id)

        right = ttk.Frame(root_frame)
        right.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(12, 0))

        ttk.Label(right, text="Terminal", font=("TkDefaultFont", 12, "bold")).pack(anchor=tk.W)
        self.terminal = scrolledtext.ScrolledText(
            right,
            wrap=tk.WORD,
            height=30,
            state=tk.DISABLED,
            font=("DejaVu Sans Mono", 10),
        )
        self.terminal.pack(fill=tk.BOTH, expand=True, pady=(6, 0))

        self.log("GUI ready. Connect nodes one by one; data polling starts only after Start Receiving Data.")

    def build_node_card(self, parent, node_id):
        node = self.nodes[node_id]

        frame = ttk.LabelFrame(parent, text=f"Node {node_id} - {node.name}", padding=10)
        frame.pack(fill=tk.X, pady=(0, 10))

        self.status_vars[node_id] = tk.StringVar(value="Closed")
        self.detail_vars[node_id] = tk.StringVar(value=f"Port: {node.port} | MAC: {node.mac}")
        self.sample_vars[node_id] = tk.StringVar(value="Latest: -")

        ttk.Label(frame, textvariable=self.status_vars[node_id], font=("TkDefaultFont", 11, "bold")).pack(
            anchor=tk.W
        )
        ttk.Label(frame, textvariable=self.detail_vars[node_id]).pack(anchor=tk.W)
        ttk.Label(frame, textvariable=self.sample_vars[node_id], wraplength=430).pack(
            anchor=tk.W, pady=(4, 8)
        )

        buttons = ttk.Frame(frame)
        buttons.pack(fill=tk.X)

        ttk.Button(buttons, text="Connect", command=lambda nid=node_id: self.async_call(self.connect_node, nid)).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        ttk.Button(buttons, text="Disconnect", command=lambda nid=node_id: self.disconnect_node(nid)).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        ttk.Button(buttons, text="Reconnect", command=lambda nid=node_id: self.async_call(self.reconnect_node, nid)).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        ttk.Button(buttons, text="Probe", command=lambda nid=node_id: self.async_call(self.probe_node, nid)).pack(
            side=tk.LEFT
        )

    def open_diagnostics_window(self):
        if self.diagnostics_window is not None and self.diagnostics_window.winfo_exists():
            self.diagnostics_window.lift()
            return

        window = tk.Toplevel(self.root)
        window.title("Bluetooth Diagnostics")
        window.geometry("1120x760")
        window.protocol("WM_DELETE_WINDOW", self.close_diagnostics_window)
        self.diagnostics_window = window
        self.diag_vars = {}

        root_frame = ttk.Frame(window, padding=10)
        root_frame.pack(fill=tk.BOTH, expand=True)

        controls = ttk.Frame(root_frame)
        controls.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(controls, text="Samples").pack(side=tk.LEFT)
        ttk.Spinbox(
            controls,
            from_=5,
            to=500,
            increment=5,
            width=6,
            textvariable=self.diag_sample_count_var,
        ).pack(side=tk.LEFT, padx=(4, 12))

        ttk.Label(controls, text="Interval ms").pack(side=tk.LEFT)
        ttk.Spinbox(
            controls,
            from_=0,
            to=2000,
            increment=25,
            width=6,
            textvariable=self.diag_interval_var,
        ).pack(side=tk.LEFT, padx=(4, 12))

        ttk.Button(controls, text="Run All Latency Tests", command=lambda: self.async_call(self.run_all_diagnostics)).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        ttk.Button(controls, text="Pi Power Status", command=lambda: self.async_call(self.run_power_diagnostics)).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        ttk.Button(controls, text="Export CSV", command=lambda: self.async_call(self.export_diagnostics_csv)).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        ttk.Button(controls, text="Clear", command=self.clear_diag_terminal).pack(side=tk.LEFT)

        log_label = ttk.Label(root_frame, text=f"Log: {DIAGNOSTIC_LOG_PATH}")
        log_label.pack(anchor=tk.W, pady=(0, 8))
        csv_label = ttk.Label(root_frame, text=f"CSV: {DIAGNOSTIC_CSV_PATH}")
        csv_label.pack(anchor=tk.W, pady=(0, 8))

        content = ttk.Frame(root_frame)
        content.pack(fill=tk.BOTH, expand=True)

        left = ttk.Frame(content)
        left.pack(side=tk.LEFT, fill=tk.Y)

        for node_id in (1, 2, 3):
            self.build_diag_node_card(left, node_id)

        right = ttk.Frame(content)
        right.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(12, 0))

        ttk.Label(right, text="Diagnostics Terminal", font=("TkDefaultFont", 12, "bold")).pack(anchor=tk.W)
        self.diag_terminal = scrolledtext.ScrolledText(
            right,
            wrap=tk.WORD,
            height=30,
            state=tk.DISABLED,
            font=("DejaVu Sans Mono", 10),
        )
        self.diag_terminal.pack(fill=tk.BOTH, expand=True, pady=(6, 0))

        self.diag_log("Diagnostics ready. Run latency tests after connecting nodes.")
        self.diag_log("Power note: software can show Pi undervoltage/throttle hints, but true ESP current draw needs an inline USB/power sensor.")

    def build_diag_node_card(self, parent, node_id):
        node = self.nodes[node_id]
        frame = ttk.LabelFrame(parent, text=f"Node {node_id} - {node.name}", padding=10)
        frame.pack(fill=tk.X, pady=(0, 10))

        vars_by_name = {
            "bt": tk.StringVar(value="Bluetooth: -"),
            "rfcomm": tk.StringVar(value=f"rfcomm: {node.port}"),
            "latency": tk.StringVar(value="Latency: -"),
            "success": tk.StringVar(value="Success: -"),
            "rssi": tk.StringVar(value="RSSI: -"),
            "last": tk.StringVar(value="Last: -"),
        }
        self.diag_vars[node_id] = vars_by_name

        for key in ("bt", "rfcomm", "latency", "success", "rssi", "last"):
            ttk.Label(frame, textvariable=vars_by_name[key], wraplength=430).pack(anchor=tk.W)

        buttons = ttk.Frame(frame)
        buttons.pack(fill=tk.X, pady=(8, 0))

        ttk.Button(buttons, text="Run Test", command=lambda nid=node_id: self.async_call(self.run_node_diagnostics, nid)).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        ttk.Button(buttons, text="BT Status", command=lambda nid=node_id: self.async_call(self.run_node_bt_status, nid)).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        ttk.Button(buttons, text="RSSI", command=lambda nid=node_id: self.async_call(self.run_node_rssi, nid)).pack(
            side=tk.LEFT
        )

    def close_diagnostics_window(self):
        self.diagnostics_window.destroy()
        self.diagnostics_window = None
        self.diag_terminal = None
        self.diag_vars = {}

    def launch_resource_monitor(self):
        script = os.path.join(os.path.dirname(__file__), "resource_diagnostics_gui.py")

        try:
            subprocess.Popen(
                [sys.executable, script],
                cwd=os.path.dirname(__file__),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self.log("Resource monitor opened.")
        except Exception as exc:
            self.log(f"Resource monitor failed to open: {exc}")

    def async_call(self, fn, *args):
        thread = threading.Thread(target=fn, args=args, daemon=True)
        thread.start()

    def set_node_status(self, node_id, status, detail=None):
        self.events.put(("node_status", node_id, status, detail))

    def log_from_thread(self, message):
        self.events.put(("log", message))

    def diag_log_from_thread(self, message):
        self.events.put(("diag_log", message))

    def diag_metric_from_thread(self, node_id, values):
        self.events.put(("diag_metric", node_id, values))

    def log_notice_from_thread(self, key, message, interval=2.5):
        now = time.monotonic()
        last = self.last_notice_at.get(key, 0.0)

        if now - last < interval:
            return

        self.last_notice_at[key] = now
        self.log_from_thread(message)

    def log(self, message):
        timestamp = time.strftime("%H:%M:%S")
        self.terminal.configure(state=tk.NORMAL)
        self.terminal.insert(tk.END, f"[{timestamp}] {message}\n")
        self.terminal.see(tk.END)
        self.terminal.configure(state=tk.DISABLED)

        line_count = int(self.terminal.index("end-1c").split(".")[0])
        if line_count > 1200:
            self.terminal.configure(state=tk.NORMAL)
            self.terminal.delete("1.0", "200.0")
            self.terminal.configure(state=tk.DISABLED)

    def clear_terminal(self):
        self.terminal.configure(state=tk.NORMAL)
        self.terminal.delete("1.0", tk.END)
        self.terminal.configure(state=tk.DISABLED)

    def diag_log(self, message):
        if self.diag_terminal is None:
            return

        timestamp = time.strftime("%H:%M:%S")
        self.diag_terminal.configure(state=tk.NORMAL)
        self.diag_terminal.insert(tk.END, f"[{timestamp}] {message}\n")
        self.diag_terminal.see(tk.END)
        self.diag_terminal.configure(state=tk.DISABLED)

        line_count = int(self.diag_terminal.index("end-1c").split(".")[0])
        if line_count > 1600:
            self.diag_terminal.configure(state=tk.NORMAL)
            self.diag_terminal.delete("1.0", "200.0")
            self.diag_terminal.configure(state=tk.DISABLED)

    def clear_diag_terminal(self):
        if self.diag_terminal is None:
            return

        self.diag_terminal.configure(state=tk.NORMAL)
        self.diag_terminal.delete("1.0", tk.END)
        self.diag_terminal.configure(state=tk.DISABLED)

    def write_diag_log(self, status, **metadata):
        try:
            log_path = os.path.abspath(DIAGNOSTIC_LOG_PATH)
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
            entry = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "status": status,
                **metadata,
            }

            with open(log_path, "a", encoding="utf-8") as log_file:
                log_file.write(json.dumps(entry, ensure_ascii=False, default=str))
                log_file.write("\n")
        except Exception as exc:
            self.diag_log_from_thread(f"Diagnostic log write failed: {exc}")

    def flatten_for_csv(self, value, prefix="", output=None):
        if output is None:
            output = {}

        if isinstance(value, dict):
            for key, item in value.items():
                next_prefix = f"{prefix}.{key}" if prefix else str(key)
                self.flatten_for_csv(item, next_prefix, output)
        elif isinstance(value, list):
            output[prefix] = json.dumps(value, ensure_ascii=False, default=str)
        else:
            output[prefix] = value

        return output

    def export_diagnostics_csv(self):
        log_path = os.path.abspath(DIAGNOSTIC_LOG_PATH)
        csv_path = os.path.abspath(DIAGNOSTIC_CSV_PATH)

        if not os.path.exists(log_path):
            self.diag_log_from_thread(f"No diagnostics log yet: {log_path}")
            return

        rows = []

        try:
            with open(log_path, "r", encoding="utf-8") as log_file:
                for line in log_file:
                    line = line.strip()

                    if not line:
                        continue

                    rows.append(self.flatten_for_csv(json.loads(line)))

            if not rows:
                self.diag_log_from_thread("Diagnostics log is empty; CSV not written.")
                return

            preferred = [
                "timestamp",
                "status",
                "node_id",
                "port",
                "mac",
                "sample_index",
                "latency_ms",
                "samples_requested",
                "samples_received",
                "success_rate",
                "min_ms",
                "avg_ms",
                "p95_ms",
                "max_ms",
                "throughput_hz",
                "parse_errors",
                "empty_count",
                "read_errors",
            ]
            all_fields = sorted({key for row in rows for key in row})
            fieldnames = preferred + [key for key in all_fields if key not in preferred]

            os.makedirs(os.path.dirname(csv_path), exist_ok=True)

            with open(csv_path, "w", encoding="utf-8", newline="") as csv_file:
                writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)

            self.diag_log_from_thread(f"Diagnostics CSV exported: {csv_path}")
        except Exception as exc:
            self.diag_log_from_thread(f"CSV export failed: {exc}")

    def run_command(self, command, timeout=15):
        proc = subprocess.run(
            command,
            cwd=os.path.dirname(__file__),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")

    def log_command_output(self, output):
        for line in output.splitlines():
            line = line.strip()
            if line:
                self.log_from_thread(line)

    def bluetooth_connect_node(self, node_id):
        node = self.nodes[node_id]
        self.log_from_thread(f"Node {node_id}: bluetoothctl connect {node.mac}...")

        try:
            code, output = self.run_command(
                ["timeout", "12s", "bluetoothctl", "connect", node.mac],
                timeout=15,
            )
        except Exception as exc:
            self.log_from_thread(f"Node {node_id}: bluetooth connect command failed: {exc}")
            self.set_node_status(node_id, "BT connect failed", str(exc))
            return False

        self.log_command_output(output)

        if "Connection successful" in output or "Connected: yes" in output:
            self.set_node_status(node_id, "BT connected", node.mac)
            return True

        if "Failed to connect" in output or code != 0:
            self.set_node_status(node_id, "BT connect failed", output.splitlines()[-1] if output.splitlines() else "")
            return False

        self.set_node_status(node_id, "BT connect attempted", node.mac)
        return True

    def bluetooth_disconnect_node(self, node_id):
        node = self.nodes[node_id]
        self.log_from_thread(f"Node {node_id}: bluetoothctl disconnect {node.mac}...")

        try:
            _, output = self.run_command(
                ["timeout", "8s", "bluetoothctl", "disconnect", node.mac],
                timeout=10,
            )
            self.log_command_output(output)
        except Exception as exc:
            self.log_from_thread(f"Node {node_id}: bluetooth disconnect command failed: {exc}")

        self.set_node_status(node_id, "BT disconnected", node.mac)

    def bluetooth_scan(self):
        self.log_from_thread("Bluetooth scan started for 10 seconds...")
        script = "{ echo 'scan on'; sleep 10; echo 'devices'; echo 'scan off'; echo 'quit'; } | bluetoothctl"

        try:
            code, output = self.run_command(["bash", "-lc", script], timeout=15)
            self.log_command_output(output)
            self.log_from_thread(f"Bluetooth scan finished with code {code}.")
        except Exception as exc:
            self.log_from_thread(f"Bluetooth scan failed: {exc}")

    def bluetooth_status(self):
        commands = []

        for node in self.nodes.values():
            commands.append(f"info {node.mac}")

        script = "printf '" + "\\n".join(commands + ["quit"]) + "\\n' | bluetoothctl"

        try:
            code, output = self.run_command(["bash", "-lc", script], timeout=10)
            self.log_command_output(output)
            self.log_from_thread(f"Bluetooth status finished with code {code}.")
        except Exception as exc:
            self.log_from_thread(f"Bluetooth status failed: {exc}")

        try:
            code, output = self.run_command(["bash", "-lc", "rfcomm 2>/dev/null || true"], timeout=5)
            self.log_command_output(output)
        except Exception as exc:
            self.log_from_thread(f"rfcomm status failed: {exc}")

    def parse_bluetooth_info(self, output):
        info = {}

        for raw_line in output.splitlines():
            line = raw_line.strip()

            if ":" not in line:
                continue

            key, value = line.split(":", 1)
            info[key.strip()] = value.strip()

        return info

    def get_bluetooth_info(self, node_id):
        node = self.nodes[node_id]
        script = f"printf 'info {node.mac}\\nquit\\n' | bluetoothctl"
        code, output = self.run_command(["bash", "-lc", script], timeout=10)
        info = self.parse_bluetooth_info(output)
        connected = info.get("Connected", "-")
        paired = info.get("Paired", "-")
        trusted = info.get("Trusted", "-")
        rssi = info.get("RSSI")
        text = f"connected={connected} paired={paired} trusted={trusted}"

        if rssi:
            text = f"{text} rssi={rssi}"

        return {
            "code": code,
            "output": output,
            "info": info,
            "text": text,
            "rssi": rssi,
        }

    def get_rfcomm_status(self, node_id):
        node = self.nodes[node_id]
        index = node_id - 1
        code, output = self.run_command(["bash", "-lc", "rfcomm 2>/dev/null || true"], timeout=5)
        target = f"rfcomm{index}:"
        match = ""

        for line in output.splitlines():
            if target in line or node.mac.lower() in line.lower():
                match = line.strip()
                break

        return {
            "code": code,
            "output": output,
            "text": match or f"rfcomm{index}: not listed",
        }

    def get_rssi_status(self, node_id):
        node = self.nodes[node_id]
        bt_info = self.get_bluetooth_info(node_id)
        rssi = bt_info["rssi"]
        hcitool_output = ""

        if not rssi:
            command = f"command -v hcitool >/dev/null 2>&1 && hcitool rssi {node.mac} || true"
            _, hcitool_output = self.run_command(["bash", "-lc", command], timeout=8)
            parsed = self.parse_bluetooth_info(hcitool_output)
            rssi = parsed.get("RSSI return value") or parsed.get("RSSI")

        return {
            "rssi": rssi or "-",
            "bt_output": bt_info["output"],
            "hcitool_output": hcitool_output,
        }

    def run_node_bt_status(self, node_id):
        node = self.nodes[node_id]
        self.diag_log_from_thread(f"Node {node_id}: reading Bluetooth/rfcomm status...")

        try:
            bt_status = self.get_bluetooth_info(node_id)
            rfcomm_status = self.get_rfcomm_status(node_id)
        except Exception as exc:
            self.diag_log_from_thread(f"Node {node_id}: status failed: {exc}")
            self.diag_metric_from_thread(node_id, {"bt": f"Bluetooth: error {exc}"})
            self.write_diag_log("bt_status_error", node_id=node_id, mac=node.mac, error=repr(exc))
            return

        values = {
            "bt": f"Bluetooth: {bt_status['text']}",
            "rfcomm": f"rfcomm: {rfcomm_status['text']}",
        }
        self.diag_metric_from_thread(node_id, values)
        self.diag_log_from_thread(f"Node {node_id}: {bt_status['text']} | {rfcomm_status['text']}")
        self.write_diag_log(
            "bt_status",
            node_id=node_id,
            mac=node.mac,
            bluetooth=bt_status["info"],
            rfcomm=rfcomm_status["text"],
            bluetooth_output=bt_status["output"],
            rfcomm_output=rfcomm_status["output"],
        )

    def run_node_rssi(self, node_id):
        node = self.nodes[node_id]
        self.diag_log_from_thread(f"Node {node_id}: reading RSSI...")

        try:
            rssi_status = self.get_rssi_status(node_id)
        except Exception as exc:
            self.diag_log_from_thread(f"Node {node_id}: RSSI failed: {exc}")
            self.diag_metric_from_thread(node_id, {"rssi": f"RSSI: error {exc}"})
            self.write_diag_log("rssi_error", node_id=node_id, mac=node.mac, error=repr(exc))
            return

        self.diag_metric_from_thread(node_id, {"rssi": f"RSSI: {rssi_status['rssi']}"})
        self.diag_log_from_thread(f"Node {node_id}: RSSI {rssi_status['rssi']}")
        self.write_diag_log("rssi", node_id=node_id, mac=node.mac, **rssi_status)

    def read_diag_int(self, var, default, lower, upper):
        try:
            value = int(str(var.get()).strip())
        except Exception:
            return default

        return max(lower, min(upper, value))

    def percentile(self, values, ratio):
        if not values:
            return None

        ordered = sorted(values)
        index = int(round((len(ordered) - 1) * ratio))
        return ordered[index]

    def summarize_latencies(self, latencies):
        if not latencies:
            return {
                "min_ms": None,
                "avg_ms": None,
                "p95_ms": None,
                "max_ms": None,
            }

        return {
            "min_ms": round(min(latencies), 2),
            "avg_ms": round(sum(latencies) / len(latencies), 2),
            "p95_ms": round(self.percentile(latencies, 0.95), 2),
            "max_ms": round(max(latencies), 2),
        }

    def summarize_numeric_values(self, values):
        if not values:
            return {
                "min": None,
                "avg": None,
                "max": None,
            }

        return {
            "min": round(min(values), 4),
            "avg": round(sum(values) / len(values), 4),
            "max": round(max(values), 4),
        }

    def run_all_diagnostics(self):
        if not self.diag_test_lock.acquire(blocking=False):
            self.diag_log_from_thread("Another diagnostics test is already running.")
            return

        self.diag_log_from_thread("Running latency diagnostics for all nodes...")

        try:
            for node_id in (1, 2, 3):
                self._run_node_diagnostics(node_id)
        finally:
            self.diag_test_lock.release()

        self.diag_log_from_thread("All latency diagnostics finished.")

    def run_node_diagnostics(self, node_id):
        if not self.diag_test_lock.acquire(blocking=False):
            self.diag_log_from_thread("Another diagnostics test is already running.")
            return

        try:
            self._run_node_diagnostics(node_id)
        finally:
            self.diag_test_lock.release()

    def _run_node_diagnostics(self, node_id):
        node = self.nodes[node_id]
        sample_count = self.read_diag_int(self.diag_sample_count_var, 30, 1, 1000)
        interval_ms = self.read_diag_int(self.diag_interval_var, 100, 0, 5000)

        if self.receiving:
            self.receiving = False
            self.log_from_thread("Receiving paused for clean diagnostics timing.")
            self.diag_log_from_thread("Receiving paused for clean diagnostics timing.")

        self.diag_metric_from_thread(node_id, {
            "latency": "Latency: running...",
            "success": "Success: running...",
        })
        self.diag_log_from_thread(
            f"Node {node_id}: latency test started ({sample_count} samples, {interval_ms} ms interval)."
        )

        self.run_node_bt_status(node_id)
        self.run_node_rssi(node_id)

        with self.lock:
            ser_open = node.ser is not None and getattr(node.ser, "is_open", False)

        if not ser_open:
            self.diag_log_from_thread(f"Node {node_id}: serial was closed, opening {node.port}...")

            try:
                ser = self.open_serial(node_id)
            except Exception as exc:
                with self.lock:
                    node.errors += 1
                    node.status = "Open failed"

                self.set_node_status(node_id, "Open failed", str(exc))
                self.diag_metric_from_thread(node_id, {
                    "latency": "Latency: serial open failed",
                    "success": "Success: 0%",
                    "last": f"Last: {exc}",
                })
                self.diag_log_from_thread(f"Node {node_id}: open failed: {exc}")
                self.write_diag_log(
                    "latency_open_error",
                    node_id=node_id,
                    port=node.port,
                    mac=node.mac,
                    error=repr(exc),
                )
                return

            with self.lock:
                node.ser = ser
                node.status = "Open"

            self.set_node_status(node_id, "Open", "Opened by diagnostics.")

        latencies = []
        empty_count = 0
        parse_errors = 0
        read_errors = 0
        last_line = ""
        feature_values = {key: [] for key in hub.FEATURE_KEYS}
        esp_timestamps = []
        host_success_times = []
        started_at = time.perf_counter()

        for index in range(1, sample_count + 1):
            request_started = time.perf_counter()

            try:
                line = self.request_line(node_id)
                latency_ms = (time.perf_counter() - request_started) * 1000.0
            except Exception as exc:
                read_errors += 1
                self.write_diag_log(
                    "latency_read_error",
                    node_id=node_id,
                    port=node.port,
                    mac=node.mac,
                    sample_index=index,
                    error=repr(exc),
                )
                self.diag_log_from_thread(f"Node {node_id}: sample {index} read error: {exc}")
                time.sleep(interval_ms / 1000.0)
                continue

            last_line = line
            parsed = hub.parse_frame(line) if line else None
            ok = bool(line)

            if ok:
                latencies.append(latency_ms)
                host_success_times.append(time.perf_counter())
            else:
                empty_count += 1

            if line and parsed is None:
                parse_errors += 1

            self.write_diag_log(
                "latency_sample",
                node_id=node_id,
                port=node.port,
                mac=node.mac,
                sample_index=index,
                latency_ms=round(latency_ms, 2),
                ok=ok,
                parsed=parsed is not None,
                raw=line,
                parsed_sample=parsed,
            )

            if parsed:
                parsed = hub.calibrate_node_sample(parsed)
                esp_timestamps.append(parsed["t"])

                for key in hub.FEATURE_KEYS:
                    feature_values[key].append(float(parsed.get(key, 0.0)))

                with self.lock:
                    node.status = "Ready"
                    node.latest_line = line
                    node.latest_sample = parsed

                self.events.put(("sample", node_id, line, parsed, False))

            if index == 1 or index == sample_count or index % 5 == 0:
                summary = self.summarize_latencies(latencies)
                ok_count = len(latencies)
                self.diag_metric_from_thread(node_id, {
                    "latency": (
                        f"Latency: avg={summary['avg_ms']} ms "
                        f"p95={summary['p95_ms']} ms max={summary['max_ms']} ms"
                    ),
                    "success": (
                        f"Success: {ok_count}/{index} "
                        f"empty={empty_count} parse_err={parse_errors} read_err={read_errors}"
                    ),
                    "last": f"Last: {line[:120] if line else '-'}",
                })

            time.sleep(interval_ms / 1000.0)

        duration_s = time.perf_counter() - started_at
        success_count = len(latencies)
        summary = self.summarize_latencies(latencies)
        success_rate = round((success_count / sample_count) * 100.0, 1) if sample_count else 0.0
        parse_success = success_count - parse_errors
        parse_success_rate = round((parse_success / success_count) * 100.0, 1) if success_count else 0.0
        throughput_hz = round(success_count / duration_s, 2) if duration_s > 0 else 0.0
        sensor_stats = {
            key: self.summarize_numeric_values(values)
            for key, values in feature_values.items()
        }
        esp_deltas = [
            esp_timestamps[index] - esp_timestamps[index - 1]
            for index in range(1, len(esp_timestamps))
        ]
        host_deltas = [
            (host_success_times[index] - host_success_times[index - 1]) * 1000.0
            for index in range(1, len(host_success_times))
        ]
        timing_stats = {
            "esp_delta_ms": self.summarize_numeric_values(esp_deltas),
            "host_delta_ms": self.summarize_numeric_values(host_deltas),
        }

        values = {
            "latency": (
                f"Latency: avg={summary['avg_ms']} ms min={summary['min_ms']} ms "
                f"p95={summary['p95_ms']} ms max={summary['max_ms']} ms"
            ),
            "success": (
                f"Success: {success_count}/{sample_count} ({success_rate}%) "
                f"parse={parse_success_rate}% empty={empty_count} read_err={read_errors}"
            ),
            "last": f"Last: {last_line[:120] if last_line else '-'}",
        }
        self.diag_metric_from_thread(node_id, values)
        self.diag_log_from_thread(
            f"Node {node_id}: done. success={success_count}/{sample_count} "
            f"avg={summary['avg_ms']}ms p95={summary['p95_ms']}ms throughput={throughput_hz}Hz."
        )
        self.write_diag_log(
            "latency_summary",
            node_id=node_id,
            port=node.port,
            mac=node.mac,
            samples_requested=sample_count,
            interval_ms=interval_ms,
            samples_received=success_count,
            success_rate=success_rate,
            parse_errors=parse_errors,
            empty_count=empty_count,
            read_errors=read_errors,
            throughput_hz=throughput_hz,
            duration_s=round(duration_s, 3),
            last_raw=last_line,
            timing_stats=timing_stats,
            sensor_stats=sensor_stats,
            **summary,
        )

    def run_power_diagnostics(self):
        self.diag_log_from_thread("Reading Raspberry Pi power/thermal status...")
        commands = {
            "throttled": "command -v vcgencmd >/dev/null 2>&1 && vcgencmd get_throttled || echo 'vcgencmd not available'",
            "temperature": "command -v vcgencmd >/dev/null 2>&1 && vcgencmd measure_temp || true",
            "core_voltage": "command -v vcgencmd >/dev/null 2>&1 && vcgencmd measure_volts core || true",
            "bluetooth_rfkill": "rfkill list bluetooth 2>/dev/null || true",
            "power_supply": (
                "for d in /sys/class/power_supply/*; do "
                "[ -d \"$d\" ] || continue; echo \"[$d]\"; "
                "cat \"$d/uevent\" 2>/dev/null; done"
            ),
        }
        results = {}

        for name, command in commands.items():
            try:
                code, output = self.run_command(["bash", "-lc", command], timeout=8)
            except Exception as exc:
                code = -1
                output = repr(exc)

            results[name] = {
                "code": code,
                "output": output.strip(),
            }
            self.diag_log_from_thread(f"{name}:")

            for line in output.splitlines() or ["-"]:
                self.diag_log_from_thread(f"  {line}")

        self.diag_log_from_thread(
            "Power reality check: Raspberry Pi does not expose Bluetooth connection watt draw directly. "
            "For report-grade ESP current, use an inline USB power meter or INA219/INA226 sensor on the ESP supply."
        )
        self.write_diag_log("power_status", results=results)

    def open_serial(self, node_id):
        node = self.nodes[node_id]
        ser = serial.Serial(
            node.port,
            hub.BAUDRATE,
            timeout=0.25,
            write_timeout=0.35,
        )
        time.sleep(0.15)
        try:
            ser.reset_input_buffer()
            ser.reset_output_buffer()
        except Exception:
            pass
        return ser

    def connect_node(self, node_id):
        node = self.nodes[node_id]

        with self.lock:
            if node.ser is not None and getattr(node.ser, "is_open", False):
                self.log_from_thread(f"Node {node_id} already open on {node.port}.")
                self.set_node_status(node_id, node.status, "Already open")
                return

        self.log_from_thread(f"Node {node_id}: opening {node.port}...")

        try:
            ser = self.open_serial(node_id)
        except Exception as exc:
            with self.lock:
                node.errors += 1
                node.status = "Open failed"
            self.set_node_status(node_id, "Open failed", str(exc))
            self.log_from_thread(f"Node {node_id}: open failed: {exc}")
            hub.write_sensor_log("gui_open_error", node_id=node_id, port=node.port, error=repr(exc))
            return

        with self.lock:
            node.ser = ser
            node.status = "Open"

        self.set_node_status(node_id, "Open", "Serial opened; probing once.")
        self.probe_node(node_id)

    def disconnect_node(self, node_id):
        node = self.nodes[node_id]
        self.close_node_serial(node_id)

        self.status_vars[node_id].set("Closed")
        self.detail_vars[node_id].set(f"Port: {node.port} | MAC: {node.mac}")
        self.log(f"Node {node_id}: disconnected.")
        hub.write_sensor_log("gui_disconnect", node_id=node_id, port=node.port)

    def close_node_serial(self, node_id):
        node = self.nodes[node_id]

        with self.lock:
            ser = node.ser
            node.ser = None
            node.status = "Closed"

            try:
                if ser is not None and getattr(ser, "is_open", False):
                    ser.close()
            except Exception as exc:
                self.log_from_thread(f"Node {node_id}: close error: {exc}")

    def reconnect_node(self, node_id):
        node = self.nodes[node_id]
        self.close_node_serial(node_id)
        self.set_node_status(node_id, "Closed", "Reconnecting...")
        self.log_from_thread(f"Node {node_id}: reconnect requested.")
        hub.write_sensor_log("gui_reconnect", node_id=node_id, port=node.port)
        self.rebind_one_node(node_id)
        time.sleep(0.2)
        self.connect_node(node_id)

    def rebind_one_node(self, node_id):
        node = self.nodes[node_id]
        index = node_id - 1
        self.close_node_serial(node_id)
        self.log_from_thread(f"Node {node_id}: rebinding rfcomm{index} -> {node.mac}...")

        commands = [
            ["sudo", "rfcomm", "release", str(index)],
            ["sudo", "rfcomm", "bind", str(index), node.mac, "1"],
        ]

        for command in commands:
            try:
                code, output = self.run_command(command, timeout=10)
                self.log_command_output(output)
                self.log_from_thread(f"{' '.join(command)} exited with code {code}.")
            except Exception as exc:
                self.log_from_thread(f"{' '.join(command)} failed: {exc}")

        self.set_node_status(node_id, "Rebound", f"{node.port} | {node.mac}")

    def request_line(self, node_id):
        node = self.nodes[node_id]

        with self.lock:
            ser = node.ser

            if ser is None or not getattr(ser, "is_open", False):
                raise RuntimeError("serial is not open")

            ser.write(b"R")
            return ser.readline().decode(errors="ignore").strip()

    def probe_node(self, node_id):
        node = self.nodes[node_id]

        self.log_from_thread(f"Node {node_id}: probing one sample...")

        try:
            line = self.request_line(node_id)
        except Exception as exc:
            with self.lock:
                node.errors += 1
                node.status = "Probe failed"
            self.set_node_status(node_id, "Probe failed", str(exc))
            self.log_from_thread(f"Node {node_id}: probe failed: {exc}")
            hub.write_sensor_log("gui_probe_error", node_id=node_id, port=node.port, error=repr(exc))
            return

        if not line:
            with self.lock:
                node.status = "Open - no data"
            self.set_node_status(node_id, "Open - no data", "No line returned. Connection kept open.")
            self.log_from_thread(f"Node {node_id}: no data returned; connection kept open.")
            hub.write_sensor_log("gui_probe_empty", node_id=node_id, port=node.port)
            return

        parsed = hub.parse_frame(line)
        hub.write_sensor_log("gui_probe_raw", node_id=node_id, port=node.port, line=line)

        with self.lock:
            node.latest_line = line
            node.status = "Ready" if parsed else "Open - unreadable"
            if parsed:
                node.latest_sample = parsed

        self.events.put(("sample", node_id, line, parsed, False))

        if parsed:
            self.log_from_thread(f"Node {node_id}: ready, initial sample kept.")
        else:
            self.log_from_thread(f"Node {node_id}: unreadable line: {line}")

    def start_receiving(self):
        if self.receiving:
            self.log("Receiving is already running.")
            return

        self.node_windows = {
            node_id: deque(maxlen=hub.WINDOW_SIZE)
            for node_id in self.nodes
        }
        self.rows_since_prediction = 0
        self.last_prediction = "WAITING"
        self.receiving = True
        self.receiver_thread = threading.Thread(target=self.receive_loop, daemon=True)
        self.receiver_thread.start()

        self.prediction_var.set("Prediction: WAITING")
        self.window_var.set(f"Window: 0/{hub.WINDOW_SIZE}")
        self.log("Receiving started.")

    def stop_receiving(self):
        if not self.receiving:
            self.log("Receiving is already stopped.")
            return

        self.receiving = False
        self.log("Receiving stopped. Serial connections stay open.")

    def receive_loop(self):
        while self.receiving:
            frame_start = time.perf_counter()

            for node_id in (1, 2, 3):
                if not self.receiving:
                    break

                node = self.nodes[node_id]

                with self.lock:
                    ser_open = node.ser is not None and getattr(node.ser, "is_open", False)

                if not ser_open:
                    self.log_notice_from_thread(
                        f"node-{node_id}-not-connected",
                        f"Node {node_id}: not connected; skipping.",
                    )
                    continue

                try:
                    line = self.request_line(node_id)
                except Exception as exc:
                    with self.lock:
                        node.errors += 1
                        node.status = "Read failed"
                    self.set_node_status(node_id, "Read failed", str(exc))
                    self.log_from_thread(f"Node {node_id}: read failed: {exc}")
                    hub.write_sensor_log("gui_read_error", node_id=node_id, port=node.port, error=repr(exc))
                    continue

                if not line:
                    self.log_notice_from_thread(
                        f"node-{node_id}-no-data",
                        f"Node {node_id}: no data.",
                    )
                    hub.write_sensor_log("gui_read_empty", node_id=node_id, port=node.port)
                    continue

                parsed = hub.parse_frame(line)
                hub.write_sensor_log("gui_raw_sample", node_id=node_id, port=node.port, line=line)

                if parsed:
                    parsed = hub.calibrate_node_sample(parsed)
                    self.append_window(parsed)

                    with self.lock:
                        node.status = "Receiving"
                        node.latest_line = line
                        node.latest_sample = parsed

                self.events.put(("sample", node_id, line, parsed, True))

            self.maybe_predict()

            elapsed = time.perf_counter() - frame_start
            sleep_for = max(0.02, hub.FRAME_PERIOD - elapsed)
            time.sleep(sleep_for)

    def append_window(self, parsed):
        node_id = parsed["node_id"]

        if node_id not in self.node_windows:
            return

        self.node_windows[node_id].append({
            key: float(parsed.get(key, 0.0))
            for key in hub.FEATURE_KEYS
        })

    def maybe_predict(self):
        window_len = min(len(self.node_windows[nid]) for nid in (1, 2, 3))
        self.events.put(("window", window_len))

        if window_len < hub.WINDOW_SIZE:
            return

        self.rows_since_prediction += 1

        if self.rows_since_prediction < hub.PREDICT_EVERY:
            return

        self.rows_since_prediction = 0
        payload = {
            "windows_by_node": {
                str(node_id): list(self.node_windows[node_id])
                for node_id in (1, 2, 3)
            }
        }

        self.log_from_thread("Posting prediction window to backend...")

        try:
            body = json.dumps(payload).encode("utf-8")
            req = request.Request(
                hub.PREDICT_URL,
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )

            with request.urlopen(req, timeout=5.0) as response:
                raw = response.read().decode("utf-8", errors="ignore")
                result = json.loads(raw) if raw else {}

            label = result.get("activity", "unknown")
            confidence = result.get("confidence", "?")
            self.events.put(("prediction", f"{label} ({confidence})"))
            self.log_from_thread(f"Prediction: {label} ({confidence})")

        except error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="ignore")
            self.log_from_thread(f"Prediction HTTP error {exc.code}: {raw}")
            self.events.put(("prediction", "ERROR"))
        except Exception as exc:
            self.log_from_thread(f"Prediction error: {exc}")
            self.events.put(("prediction", "ERROR"))

    def rebind_rfcomm(self):
        self.stop_receiving()

        for node_id in (1, 2, 3):
            self.disconnect_node(node_id)

        self.async_call(self.run_rebind)

    def run_rebind(self):
        script = os.path.join(os.path.dirname(__file__), "rfcommstarter.sh")
        self.log_from_thread("Running rfcommstarter.sh...")

        try:
            proc = subprocess.run(
                ["bash", script],
                cwd=os.path.dirname(__file__),
                capture_output=True,
                text=True,
                timeout=20,
            )
            output = (proc.stdout or "") + (proc.stderr or "")
            for line in output.splitlines():
                self.log_from_thread(line)
            self.log_from_thread(f"rfcommstarter.sh exited with code {proc.returncode}.")
        except Exception as exc:
            self.log_from_thread(f"rfcommstarter.sh failed: {exc}")

    def drain_events(self):
        try:
            while True:
                event = self.events.get_nowait()
                kind = event[0]

                if kind == "log":
                    self.log(event[1])
                elif kind == "diag_log":
                    self.diag_log(event[1])
                elif kind == "diag_metric":
                    _, node_id, values = event

                    if node_id in self.diag_vars:
                        for key, value in values.items():
                            if key in self.diag_vars[node_id]:
                                self.diag_vars[node_id][key].set(value)
                elif kind == "node_status":
                    _, node_id, status, detail = event
                    node = self.nodes[node_id]
                    self.status_vars[node_id].set(status)
                    if detail:
                        self.detail_vars[node_id].set(f"{node.port} | {node.mac} | {detail}")
                    else:
                        self.detail_vars[node_id].set(f"Port: {node.port} | MAC: {node.mac}")
                elif kind == "sample":
                    _, node_id, line, parsed, show_line = event
                    if parsed:
                        text = (
                            f"Latest: t={parsed['t']} "
                            f"acc=({parsed['ax']:.2f}, {parsed['ay']:.2f}, {parsed['az']:.2f}) "
                            f"gyro=({parsed['gx']:.2f}, {parsed['gy']:.2f}, {parsed['gz']:.2f}) "
                            f"mag=({parsed['mx']:.0f}, {parsed['my']:.0f}, {parsed['mz']:.0f})"
                        )
                        self.sample_vars[node_id].set(text)
                        self.status_vars[node_id].set("Receiving" if show_line else "Ready")
                    else:
                        self.sample_vars[node_id].set(f"Latest raw: {line}")
                    if show_line:
                        self.log(f"Node {node_id}: {line}")
                elif kind == "window":
                    window_len = event[1]
                    self.window_var.set(f"Window: {window_len}/{hub.WINDOW_SIZE}")
                elif kind == "prediction":
                    prediction = event[1]
                    self.prediction_var.set(f"Prediction: {prediction}")
                elif kind == "disconnect":
                    self.disconnect_node(event[1])
        except queue.Empty:
            pass

        self.root.after(80, self.drain_events)

    def on_close(self):
        self.receiving = False
        time.sleep(0.1)

        for node_id in (1, 2, 3):
            node = self.nodes[node_id]
            try:
                if node.ser is not None and getattr(node.ser, "is_open", False):
                    node.ser.close()
            except Exception:
                pass

        self.root.destroy()


def main():
    root = tk.Tk()
    app = TdmaHubGui(root)
    root.mainloop()


if __name__ == "__main__":
    main()
