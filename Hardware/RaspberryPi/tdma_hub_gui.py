import json
import os
import queue
import subprocess
import threading
import time
import tkinter as tk
from collections import deque
from dataclasses import dataclass, field
from tkinter import scrolledtext, ttk
from urllib import error, request

import serial

import tdma_hub as hub


NODE_MACS = {
    1: "08:A6:F7:47:4C:CE",
    2: "94:54:C5:E7:E4:1A",
    3: "94:54:C5:E7:E7:16",
}


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

    def async_call(self, fn, *args):
        thread = threading.Thread(target=fn, args=args, daemon=True)
        thread.start()

    def set_node_status(self, node_id, status, detail=None):
        self.events.put(("node_status", node_id, status, detail))

    def log_from_thread(self, message):
        self.events.put(("log", message))

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
