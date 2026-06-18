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
from har_dataset_utils import (
    ACTIVITIES,
    FEATURE_KEYS,
    NODE_LAYOUT,
    append_jsonl,
    default_dataset_root,
    ensure_dir,
    local_now_iso,
    normalize_activity,
    sanitize_token,
    write_json,
)


NODE_MACS = {
    1: "08:A6:F7:47:4C:CE",
    2: "08:D1:F9:DF:D7:BA",
    3: "08:A6:F7:47:43:72",
}

ACTIVITY_GUIDELINES = {
    "standing": (
        "Stand naturally in place with both feet on the floor. Keep arms relaxed, "
        "small natural body sway is okay, but do not walk, sit, turn around, or lean heavily."
    ),
    "sitting": (
        "Sit on a chair before warmup ends. Keep feet on the floor and stay seated. "
        "Do not include sitting down or standing up transitions in the recording."
    ),
    "lying": (
        "Lie down before warmup ends and stay stable. Back or side lying are both okay, "
        "but record them as separate clean sessions when possible. Do not include getting down or standing up."
    ),
    "walking": (
        "Walk continuously at one chosen speed. Use natural arm swing and avoid stops, "
        "phone handling, sudden turns, or standing pauses during the recording."
    ),
    "crouching": (
        "Use a consistent stand-crouch cycle: stand, crouch/squat, hold briefly, stand again. "
        "Do not sit on a chair, kneel, or pause for a long time."
    ),
    "x_pose": (
        "Stand in an X-pose before warmup ends: arms raised/spread and feet apart. "
        "Hold the pose steadily and avoid walking or turning."
    ),
    "punching": (
        "Punch forward repeatedly at a steady rhythm while keeping feet mostly planted. "
        "Use the same punching style for the whole session."
    ),
    "turning": (
        "Turn in place repeatedly at a steady pace, such as left-right or full body rotations. "
        "Avoid walking forward or mixing in punching/crouching movements."
    ),
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
        self.root.geometry("1180x960")
        self.root.minsize(1100, 900)

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
        self.resample_seconds = float(os.getenv("PAMAP2_RESAMPLE_SECONDS", "6.0"))
        self.min_resample_seconds = float(os.getenv("PAMAP2_MIN_RESAMPLE_SECONDS", "2.5"))
        self.min_raw_samples = int(os.getenv("PAMAP2_MIN_RAW_SAMPLES", "8"))
        self.rows_since_prediction = 0
        self.last_prediction = "WAITING"
        self.last_notice_at = {}
        self.low_performance = os.getenv("HAR_GUI_LOW_POWER", "1") not in ("0", "false", "False")
        self.show_raw_lines = os.getenv("HAR_GUI_SHOW_RAW_LINES", "0") not in ("0", "false", "False")
        self.skip_prediction_while_collecting = (
            os.getenv("HAR_GUI_SKIP_PREDICT_WHILE_COLLECTING", "1")
            not in ("0", "false", "False")
        )
        self.sample_ui_interval = float(os.getenv("HAR_GUI_SAMPLE_UI_INTERVAL", "0.5"))
        self.terminal_max_lines = int(os.getenv("HAR_GUI_TERMINAL_MAX_LINES", "300"))
        self.last_sample_ui_at = {node_id: 0.0 for node_id in (1, 2, 3)}

        self.status_vars = {}
        self.detail_vars = {}
        self.sample_vars = {}
        self.diagnostics_window = None
        self.diag_terminal = None
        self.diag_vars = {}
        self.diag_sample_count_var = tk.StringVar(value="30")
        self.diag_interval_var = tk.StringVar(value="100")
        self.diag_test_lock = threading.Lock()
        self.node_order_var = tk.StringVar(
            value=",".join(str(node_id) for node_id in hub.PAMAP2_NODE_ORDER)
        )
        self.axis_transform_var = tk.StringVar(value=hub.PAMAP2_AXIS_TRANSFORM)
        self.node_axis_vars = {
            node_id: tk.StringVar(value=hub.PAMAP2_NODE_AXIS_TRANSFORMS[node_id])
            for node_id in (1, 2, 3)
        }
        self.mag_mode_var = tk.StringVar(value=hub.PAMAP2_MAG_MODE)
        self.config_target_var = tk.StringVar(value="standing")
        self.sweep_axis_var = tk.BooleanVar(value=True)
        self.use_live_calibration_var = tk.BooleanVar(value=False)
        self.pamap2_sweep_running = False
        self.low_performance_var = tk.BooleanVar(value=self.low_performance)
        self.show_raw_lines_var = tk.BooleanVar(value=self.show_raw_lines)
        self.skip_prediction_while_collecting_var = tk.BooleanVar(
            value=self.skip_prediction_while_collecting
        )
        self.low_performance_var.trace_add("write", lambda *_: self.sync_performance_options())
        self.show_raw_lines_var.trace_add("write", lambda *_: self.sync_performance_options())
        self.skip_prediction_while_collecting_var.trace_add(
            "write",
            lambda *_: self.sync_performance_options(),
        )
        self.dataset_root = os.getenv("HAR_DATASET_ROOT", default_dataset_root())
        self.dataset_collection = None
        self.dataset_participant_var = tk.StringVar(value="p01")
        self.dataset_activity_var = tk.StringVar(value="standing")
        self.dataset_duration_var = tk.StringVar(value="60")
        self.dataset_warmup_var = tk.StringVar(value="5")
        self.dataset_notes_var = tk.StringVar(value="")
        self.dataset_status_var = tk.StringVar(value="Dataset: idle")
        self.dataset_guideline_var = tk.StringVar(
            value=self.dataset_guideline_text(self.dataset_activity_var.get())
        )
        self.dataset_activity_var.trace_add("write", lambda *_: self.update_dataset_guideline())

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
        ttk.Button(controls, text="Reset Window", command=self.reset_prediction_window).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        ttk.Button(controls, text="Predict Now", command=self.predict_now).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        ttk.Button(controls, text="Test Orders", command=self.test_node_orders).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        ttk.Button(controls, text="Stop", command=self.stop_receiving).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        ttk.Button(controls, text="Clear Terminal", command=self.clear_terminal).pack(
            side=tk.LEFT
        )

        performance_controls = ttk.Frame(left)
        performance_controls.pack(fill=tk.X, pady=(0, 10))

        ttk.Checkbutton(
            performance_controls,
            text="Low Performance Mode",
            variable=self.low_performance_var,
        ).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Checkbutton(
            performance_controls,
            text="Show Raw Lines",
            variable=self.show_raw_lines_var,
        ).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Checkbutton(
            performance_controls,
            text="Skip Predict While Collecting",
            variable=self.skip_prediction_while_collecting_var,
        ).pack(side=tk.LEFT)

        model_controls = ttk.Frame(left)
        model_controls.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(model_controls, text="Order").pack(side=tk.LEFT, padx=(0, 4))
        ttk.Combobox(
            model_controls,
            values=hub.NODE_ORDER_OPTIONS,
            textvariable=self.node_order_var,
            width=7,
            state="readonly",
        ).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Label(model_controls, text="Axis").pack(side=tk.LEFT, padx=(0, 4))
        ttk.Combobox(
            model_controls,
            values=hub.AXIS_TRANSFORM_OPTIONS,
            textvariable=self.axis_transform_var,
            width=9,
            state="readonly",
        ).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Label(model_controls, text="Mag").pack(side=tk.LEFT, padx=(0, 4))
        ttk.Combobox(
            model_controls,
            values=hub.MAG_MODE_OPTIONS,
            textvariable=self.mag_mode_var,
            width=13,
            state="readonly",
        ).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Label(model_controls, text="Target").pack(side=tk.LEFT, padx=(0, 4))
        ttk.Combobox(
            model_controls,
            values=ACTIVITIES,
            textvariable=self.config_target_var,
            width=10,
            state="readonly",
        ).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(model_controls, text="Test Configs", command=self.test_preprocess_configs).pack(
            side=tk.LEFT, padx=(0, 8)
        )
        ttk.Button(model_controls, text="Save Live Calib", command=lambda: self.async_call(self.save_calibration_sample)).pack(
            side=tk.LEFT, padx=(0, 8)
        )
        ttk.Button(model_controls, text="Clear Live Calib", command=lambda: self.async_call(self.clear_calibration_samples)).pack(
            side=tk.LEFT, padx=(0, 8)
        )
        ttk.Checkbutton(
            model_controls,
            text="Sweep Axes",
            variable=self.sweep_axis_var,
        ).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(model_controls, text="Sync Backend Config", command=self.sync_backend_config).pack(
            side=tk.LEFT
        )

        pamap2_calib_controls = ttk.Frame(left)
        pamap2_calib_controls.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(pamap2_calib_controls, text="PAMAP2 Calib").pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(
            pamap2_calib_controls,
            text="Save Window",
            command=lambda: self.async_call(self.save_pamap2_calibration_sample),
        ).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(
            pamap2_calib_controls,
            text="Run Sweep",
            command=lambda: self.async_call(self.run_pamap2_calibration_sweep),
        ).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(
            pamap2_calib_controls,
            text="Clear Set",
            command=lambda: self.async_call(self.clear_pamap2_calibration_samples),
        ).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Checkbutton(
            pamap2_calib_controls,
            text="Use Live Calib",
            variable=self.use_live_calibration_var,
        ).pack(side=tk.LEFT)

        node_axis_controls = ttk.Frame(left)
        node_axis_controls.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(node_axis_controls, text="Node Axes").pack(side=tk.LEFT, padx=(0, 6))

        for node_id in (1, 2, 3):
            ttk.Label(node_axis_controls, text=f"N{node_id}").pack(side=tk.LEFT, padx=(0, 3))
            ttk.Combobox(
                node_axis_controls,
                values=hub.AXIS_TRANSFORM_OPTIONS,
                textvariable=self.node_axis_vars[node_id],
                width=9,
                state="readonly",
            ).pack(side=tk.LEFT, padx=(0, 8))

        ttk.Button(
            node_axis_controls,
            text="Same Orientation",
            command=self.use_same_orientation_config,
        ).pack(side=tk.LEFT, padx=(0, 8))

        self.build_dataset_panel(left)

        self.prediction_var = tk.StringVar(value="Prediction: WAITING")
        self.window_var = tk.StringVar(value=f"Window: 0.0s/{self.resample_seconds:.1f}s")
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
        self.log(
            f"Prediction window uses last {self.resample_seconds:.1f}s resampled to "
            f"{hub.WINDOW_SIZE} model timesteps."
        )
        self.root.after(300, self.sync_backend_config)

    def build_dataset_panel(self, parent):
        frame = ttk.LabelFrame(parent, text="Dataset Collection", padding=10)
        frame.pack(fill=tk.X, pady=(0, 10))

        row1 = ttk.Frame(frame)
        row1.pack(fill=tk.X, pady=(0, 6))

        ttk.Label(row1, text="Participant").pack(side=tk.LEFT, padx=(0, 4))
        ttk.Entry(row1, textvariable=self.dataset_participant_var, width=8).pack(
            side=tk.LEFT, padx=(0, 8)
        )

        ttk.Label(row1, text="Activity").pack(side=tk.LEFT, padx=(0, 4))
        ttk.Combobox(
            row1,
            values=ACTIVITIES,
            textvariable=self.dataset_activity_var,
            width=10,
            state="readonly",
        ).pack(side=tk.LEFT, padx=(0, 8))

        ttk.Label(row1, text="Duration").pack(side=tk.LEFT, padx=(0, 4))
        ttk.Spinbox(
            row1,
            from_=10,
            to=3600,
            increment=10,
            width=6,
            textvariable=self.dataset_duration_var,
        ).pack(side=tk.LEFT, padx=(0, 8))

        ttk.Label(row1, text="Warmup").pack(side=tk.LEFT, padx=(0, 4))
        ttk.Spinbox(
            row1,
            from_=0,
            to=60,
            increment=1,
            width=5,
            textvariable=self.dataset_warmup_var,
        ).pack(side=tk.LEFT)

        row2 = ttk.Frame(frame)
        row2.pack(fill=tk.X, pady=(0, 6))

        ttk.Label(row2, text="Notes").pack(side=tk.LEFT, padx=(0, 4))
        ttk.Entry(row2, textvariable=self.dataset_notes_var, width=35).pack(
            side=tk.LEFT,
            fill=tk.X,
            expand=True,
            padx=(0, 8),
        )

        ttk.Button(row2, text="Start Dataset", command=self.start_dataset_collection).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        ttk.Button(row2, text="Stop Dataset", command=self.stop_dataset_collection).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        ttk.Button(row2, text="Build Windows", command=lambda: self.async_call(self.build_window_dataset)).pack(
            side=tk.LEFT
        )

        ttk.Label(frame, textvariable=self.dataset_guideline_var, wraplength=520).pack(
            anchor=tk.W,
            pady=(0, 6),
        )
        ttk.Label(frame, textvariable=self.dataset_status_var, wraplength=520).pack(anchor=tk.W)

    def get_activity_guideline(self, activity):
        return ACTIVITY_GUIDELINES.get(
            normalize_activity(activity),
            "Keep the selected activity clean and avoid transition movements during recording.",
        )

    def dataset_guideline_text(self, activity):
        return f"Guideline: {self.get_activity_guideline(activity)}"

    def update_dataset_guideline(self):
        self.dataset_guideline_var.set(
            self.dataset_guideline_text(self.dataset_activity_var.get())
        )

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

    def sync_backend_config(self):
        self.async_call(self.fetch_backend_config)

    def fetch_backend_config(self):
        health_url = hub.PREDICT_URL.rsplit("/", 1)[0] + "/health"

        try:
            with request.urlopen(health_url, timeout=2.0) as response:
                raw = response.read().decode("utf-8", errors="ignore")
                config = json.loads(raw) if raw else {}

            self.events.put(("backend_config", config))
        except Exception as exc:
            self.log_from_thread(f"Backend config sync skipped: {exc}")

    def async_call(self, fn, *args):
        thread = threading.Thread(target=fn, args=args, daemon=True)
        thread.start()

    def sync_performance_options(self):
        self.low_performance = bool(self.low_performance_var.get())
        self.show_raw_lines = bool(self.show_raw_lines_var.get())
        self.skip_prediction_while_collecting = bool(
            self.skip_prediction_while_collecting_var.get()
        )

    def is_dataset_collection_active(self):
        with self.lock:
            return bool(self.dataset_collection and self.dataset_collection.get("active"))

    def should_emit_sample_event(self, node_id):
        if not self.low_performance:
            return True

        now = time.monotonic()

        if now - self.last_sample_ui_at.get(node_id, 0.0) < self.sample_ui_interval:
            return False

        self.last_sample_ui_at[node_id] = now
        return True

    def should_log_raw_sample_line(self):
        return self.show_raw_lines

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

        line_count = int(self.terminal.index("end-1c").split(".")[0])

        if line_count > self.terminal_max_lines:
            delete_until = max(1, line_count - self.terminal_max_lines + 1)
            self.terminal.delete("1.0", f"{delete_until}.0")

        self.terminal.see(tk.END)
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
            self.log_from_thread(f"Node {node_id}: open failed: {exc}")
            self.log_from_thread(f"Node {node_id}: trying Bluetooth connect + rfcomm rebind once...")

            self.bluetooth_connect_node(node_id)
            time.sleep(0.5)
            self.rebind_one_node(node_id)
            time.sleep(0.2)

            try:
                ser = self.open_serial(node_id)
            except Exception as retry_exc:
                with self.lock:
                    node.errors += 1
                    node.status = "Open failed"
                self.set_node_status(node_id, "Open failed", str(retry_exc))
                self.log_from_thread(f"Node {node_id}: retry open failed: {retry_exc}")
                hub.write_sensor_log(
                    "gui_open_error",
                    node_id=node_id,
                    port=node.port,
                    error=repr(retry_exc),
                    first_error=repr(exc),
                )
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

        self.clear_prediction_window()
        self.receiving = True
        self.receiver_thread = threading.Thread(target=self.receive_loop, daemon=True)
        self.receiver_thread.start()

        self.log("Receiving started.")

    def clear_prediction_window(self):
        self.node_windows = {
            node_id: deque(maxlen=hub.WINDOW_SIZE)
            for node_id in self.nodes
        }
        self.rows_since_prediction = 0
        self.last_prediction = "WAITING"

        self.prediction_var.set("Prediction: WAITING")
        self.window_var.set(f"Window: 0.0s/{self.resample_seconds:.1f}s")

    def reset_prediction_window(self):
        self.clear_prediction_window()
        self.log(
            "Prediction window reset. Hold the current activity until the Window timer is ready."
        )

    def predict_now(self):
        self.async_call(self.maybe_predict, True)

    def test_node_orders(self):
        self.async_call(self.run_node_order_test)

    def test_preprocess_configs(self):
        self.async_call(self.run_preprocess_config_test)

    def stop_receiving(self):
        if not self.receiving:
            self.log("Receiving is already stopped.")
            return

        self.receiving = False
        self.log("Receiving stopped. Serial connections stay open.")

    def parse_dataset_seconds(self, value, field_name):
        try:
            seconds = float(str(value).strip())
        except Exception as exc:
            raise ValueError(f"{field_name} must be a number") from exc

        if seconds < 0:
            raise ValueError(f"{field_name} must be 0 or greater")

        return seconds

    def start_dataset_collection(self):
        with self.lock:
            if self.dataset_collection and self.dataset_collection.get("active"):
                self.log("Dataset collection is already running.")
                return

        try:
            participant = sanitize_token(self.dataset_participant_var.get())
            activity = normalize_activity(self.dataset_activity_var.get())
            duration_seconds = self.parse_dataset_seconds(
                self.dataset_duration_var.get(),
                "Duration",
            )
            warmup_seconds = self.parse_dataset_seconds(
                self.dataset_warmup_var.get(),
                "Warmup",
            )
        except ValueError as error:
            self.log(str(error))
            return

        if activity not in ACTIVITIES:
            self.log(f"Activity must be one of: {', '.join(ACTIVITIES)}")
            return

        if duration_seconds <= 0:
            self.log("Duration must be greater than 0 seconds.")
            return

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        session_id = f"session_{stamp}_{participant}_{activity}"
        session_dir = ensure_dir(os.path.join(self.dataset_root, "raw_sessions", session_id))
        metadata_path = os.path.join(session_dir, "metadata.json")
        samples_path = os.path.join(session_dir, "raw_samples.jsonl")
        metadata = {
            "session_id": session_id,
            "participant_id": participant,
            "activity": activity,
            "started_at": local_now_iso(),
            "duration_seconds": float(duration_seconds),
            "warmup_seconds": float(warmup_seconds),
            "node_layout": NODE_LAYOUT,
            "node_ports": {str(node_id): hub.NODE_PORTS[node_id] for node_id in (1, 2, 3)},
            "features": list(FEATURE_KEYS),
            "notes": self.dataset_notes_var.get().strip(),
            "activity_guideline": self.get_activity_guideline(activity),
            "status": "running",
        }

        try:
            write_json(metadata_path, metadata)
            samples_file = open(samples_path, "a", encoding="utf-8")
        except Exception as error:
            self.log(f"Failed to start dataset session: {error}")
            return

        now_monotonic = time.monotonic()
        collection = {
            "active": True,
            "session_id": session_id,
            "participant_id": participant,
            "activity": activity,
            "session_dir": session_dir,
            "metadata_path": metadata_path,
            "samples_path": samples_path,
            "metadata": metadata,
            "file": samples_file,
            "started_monotonic": now_monotonic,
            "warmup_until": now_monotonic + warmup_seconds,
            "stop_at": now_monotonic + warmup_seconds + duration_seconds,
            "duration_seconds": duration_seconds,
            "warmup_seconds": warmup_seconds,
            "sample_count": 0,
            "node_counts": {"1": 0, "2": 0, "3": 0},
            "last_status_at": 0.0,
        }

        with self.lock:
            self.dataset_collection = collection

        self.dataset_status_var.set(
            f"Dataset: warmup {warmup_seconds:.0f}s -> {session_id}"
        )
        self.log(f"Dataset session started: {session_id}")
        self.log(f"Raw samples: {samples_path}")

        if not self.receiving:
            self.start_receiving()

    def stop_dataset_collection(self):
        self.finish_dataset_collection(status="stopped", from_thread=False)

    def finish_dataset_collection(self, status="completed", from_thread=False):
        with self.lock:
            collection = self.dataset_collection

            if not collection or not collection.get("active"):
                if not from_thread:
                    self.log("Dataset collection is not running.")
                return

            collection["active"] = False
            samples_file = collection.get("file")
            metadata = dict(collection.get("metadata") or {})
            metadata.update({
                "finished_at": local_now_iso(),
                "status": status,
                "sample_count": int(collection.get("sample_count", 0)),
                "node_sample_counts": dict(collection.get("node_counts", {})),
                "samples_path": collection.get("samples_path"),
            })
            metadata_path = collection.get("metadata_path")
            session_id = collection.get("session_id")
            sample_count = int(collection.get("sample_count", 0))
            self.dataset_collection = collection

        try:
            if samples_file is not None:
                samples_file.flush()
                samples_file.close()
        except Exception as error:
            message = f"Dataset file close failed: {error}"
            self.events.put(("log", message)) if from_thread else self.log(message)

        try:
            write_json(metadata_path, metadata)
        except Exception as error:
            message = f"Dataset metadata update failed: {error}"
            self.events.put(("log", message)) if from_thread else self.log(message)

        status_text = f"Dataset: {status} {session_id}, samples={sample_count}"

        if from_thread:
            self.events.put(("dataset_status", status_text))
            self.events.put(("log", status_text))
        else:
            self.dataset_status_var.set(status_text)
            self.log(status_text)

    def update_dataset_status_from_thread(self, text):
        self.events.put(("dataset_status", text))

    def check_dataset_collection_timeout(self):
        with self.lock:
            collection = self.dataset_collection
            active = bool(collection and collection.get("active"))
            stop_at = collection.get("stop_at") if active else None

        if active and time.monotonic() >= stop_at:
            self.finish_dataset_collection(status="completed", from_thread=True)

    def record_dataset_sample(self, parsed):
        now_monotonic = time.monotonic()
        should_finish = False
        status_text = None

        with self.lock:
            collection = self.dataset_collection

            if not collection or not collection.get("active"):
                return

            if now_monotonic >= collection["stop_at"]:
                should_finish = True
            elif now_monotonic < collection["warmup_until"]:
                remaining = collection["warmup_until"] - now_monotonic

                if now_monotonic - collection.get("last_status_at", 0.0) >= 1.0:
                    collection["last_status_at"] = now_monotonic
                    status_text = f"Dataset: warmup {remaining:.1f}s"
            else:
                entry = {
                    "session_id": collection["session_id"],
                    "participant_id": collection["participant_id"],
                    "activity": collection["activity"],
                    "node_id": int(parsed["node_id"]),
                    "node_name": NODE_LAYOUT[str(parsed["node_id"])],
                    "t_device_ms": int(parsed["t"]),
                    "t_host": time.time(),
                }

                for feature in FEATURE_KEYS:
                    entry[feature] = float(parsed.get(feature, 0.0))

                append_jsonl(collection["file"], entry)
                collection["sample_count"] += 1
                collection["node_counts"][str(parsed["node_id"])] += 1

                if collection["sample_count"] % 20 == 0:
                    collection["file"].flush()

                if now_monotonic - collection.get("last_status_at", 0.0) >= 1.0:
                    collection["last_status_at"] = now_monotonic
                    elapsed = now_monotonic - collection["warmup_until"]
                    remaining = max(0.0, collection["stop_at"] - now_monotonic)
                    status_text = (
                        f"Dataset: recording {elapsed:.1f}/"
                        f"{collection['duration_seconds']:.1f}s "
                        f"samples={collection['sample_count']} "
                        f"remaining={remaining:.1f}s"
                    )

        if status_text:
            self.update_dataset_status_from_thread(status_text)

        if should_finish:
            self.finish_dataset_collection(status="completed", from_thread=True)

    def build_window_dataset(self):
        python_path = os.path.join(os.path.dirname(__file__), "HAR-backend", ".venv", "bin", "python")

        if not os.path.exists(python_path):
            python_path = sys.executable

        script_path = os.path.join(os.path.dirname(__file__), "build_window_dataset.py")
        command = [
            python_path,
            script_path,
            "--dataset-root",
            self.dataset_root,
        ]

        self.log_from_thread("Building 200x27 dataset windows...")

        try:
            proc = subprocess.run(
                command,
                cwd=os.path.dirname(__file__),
                capture_output=True,
                text=True,
                timeout=300,
            )
            output = (proc.stdout or "") + (proc.stderr or "")

            for line in output.splitlines():
                self.log_from_thread(line)

            status = "completed" if proc.returncode == 0 else f"failed ({proc.returncode})"
            self.events.put(("dataset_status", f"Dataset windows build {status}"))
        except Exception as error:
            self.log_from_thread(f"Build windows failed: {error}")
            self.events.put(("dataset_status", "Dataset windows build failed"))

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
                    self.record_dataset_sample(parsed)

                    with self.lock:
                        node.status = "Receiving"
                        node.latest_line = line
                        node.latest_sample = parsed

                if self.should_emit_sample_event(node_id):
                    self.events.put((
                        "sample",
                        node_id,
                        line,
                        parsed,
                        self.should_log_raw_sample_line(),
                    ))

            if self.skip_prediction_while_collecting and self.is_dataset_collection_active():
                self.rows_since_prediction = 0
            else:
                self.maybe_predict()
            self.check_dataset_collection_timeout()

            elapsed = time.perf_counter() - frame_start
            sleep_for = max(0.02, hub.FRAME_PERIOD - elapsed)
            time.sleep(sleep_for)

    def append_window(self, parsed):
        node_id = parsed["node_id"]

        if node_id not in self.node_windows:
            return

        sample = {
            key: float(parsed.get(key, 0.0))
            for key in hub.FEATURE_KEYS
        }
        sample["_host_time"] = time.monotonic()
        self.node_windows[node_id].append(sample)

    def get_resample_status(self):
        with self.lock:
            windows = {
                node_id: list(self.node_windows[node_id])
                for node_id in (1, 2, 3)
            }

        if any(not windows[node_id] for node_id in (1, 2, 3)):
            counts = [len(windows[node_id]) for node_id in (1, 2, 3)]
            return False, f"raw {min(counts)}/{self.min_raw_samples}", None, {}

        common_end = min(
            readings[-1].get("_host_time", 0.0)
            for readings in windows.values()
        )
        cutoff = common_end - self.resample_seconds
        recent_by_node = {}
        spans = []
        counts = []

        for node_id, readings in windows.items():
            recent = [
                reading
                for reading in readings
                if cutoff <= reading.get("_host_time", 0.0) <= common_end
            ]
            recent_by_node[node_id] = recent
            counts.append(len(recent))

            if recent:
                spans.append(recent[-1]["_host_time"] - recent[0]["_host_time"])
            else:
                spans.append(0.0)

        min_count = min(counts) if counts else 0
        min_span = min(spans) if spans else 0.0
        ready = min_count >= self.min_raw_samples and min_span >= self.min_resample_seconds
        status = (
            f"{min(min_span, self.resample_seconds):.1f}s/{self.resample_seconds:.1f}s "
            f"({min_count} raw)"
        )

        return ready, status, common_end, recent_by_node

    def resample_node_readings(self, readings, common_end):
        cutoff = common_end - self.resample_seconds
        ordered = sorted(
            (
                reading
                for reading in readings
                if cutoff <= reading.get("_host_time", 0.0) <= common_end
            ),
            key=lambda reading: reading.get("_host_time", 0.0),
        )

        if not ordered:
            raise ValueError("No readings available for resampling")

        if len(ordered) == 1:
            return [
                {key: float(ordered[0].get(key, 0.0)) for key in hub.FEATURE_KEYS}
                for _ in range(hub.WINDOW_SIZE)
            ]

        target_times = [
            cutoff + (self.resample_seconds * index / (hub.WINDOW_SIZE - 1))
            for index in range(hub.WINDOW_SIZE)
        ]
        result = []
        source_index = 0

        for target_time in target_times:
            while (
                source_index < len(ordered) - 2
                and ordered[source_index + 1].get("_host_time", 0.0) < target_time
            ):
                source_index += 1

            left = ordered[source_index]
            right = ordered[min(source_index + 1, len(ordered) - 1)]
            left_time = left.get("_host_time", 0.0)
            right_time = right.get("_host_time", left_time)

            if target_time <= left_time or right_time <= left_time:
                ratio = 0.0
            elif target_time >= right_time:
                ratio = 1.0
            else:
                ratio = (target_time - left_time) / (right_time - left_time)

            result.append({
                key: (
                    float(left.get(key, 0.0))
                    + (float(right.get(key, 0.0)) - float(left.get(key, 0.0))) * ratio
                )
                for key in hub.FEATURE_KEYS
            })

        return result

    def current_node_order(self):
        return hub.parse_node_order(self.node_order_var.get())

    def current_axis_transform(self):
        return hub.parse_axis_transform(self.axis_transform_var.get())

    def current_node_axis_transforms(self):
        return {
            node_id: hub.parse_axis_transform(self.node_axis_vars[node_id].get())
            for node_id in (1, 2, 3)
        }

    def current_mag_mode(self):
        return hub.parse_mag_mode(self.mag_mode_var.get())

    def use_same_orientation_config(self):
        self.node_order_var.set("1,2,3")
        self.axis_transform_var.set("+x+y+z")
        self.mag_mode_var.set("raw")

        for node_id in (1, 2, 3):
            self.node_axis_vars[node_id].set("+x+y+z")

        self.sweep_axis_var.set(True)
        self.log("Same-orientation preset applied: node axes all +x+y+z, axis sweep enabled.")

    def current_window_len(self):
        ready, _, _, recent_by_node = self.get_resample_status()

        if not ready:
            return min(len(recent_by_node.get(node_id, [])) for node_id in (1, 2, 3))

        return hub.WINDOW_SIZE

    def build_resampled_windows_by_node(self):
        ready, status, common_end, recent_by_node = self.get_resample_status()

        if not ready or common_end is None:
            raise ValueError(f"Prediction window is not ready: {status}")

        return {
            str(node_id): self.resample_node_readings(recent_by_node[node_id], common_end)
            for node_id in (1, 2, 3)
        }

    def build_payload_from_windows(
        self,
        node_order=None,
        axis_transform=None,
        node_axis_transforms=None,
        mag_mode=None,
    ):
        node_order = tuple(node_order or self.current_node_order())
        axis_transform = hub.parse_axis_transform(axis_transform or self.current_axis_transform())
        node_axis_transforms = hub.parse_node_axis_transforms(
            node_axis_transforms or self.current_node_axis_transforms(),
            axis_transform=axis_transform,
        )
        mag_mode = hub.parse_mag_mode(mag_mode or self.current_mag_mode())

        with self.lock:
            return {
                "node_order": list(node_order),
                "axis_transform": axis_transform,
                "node_axis_transforms": {
                    str(node_id): node_axis
                    for node_id, node_axis in node_axis_transforms.items()
                },
                "mag_mode": mag_mode,
                "use_live_calibration": bool(self.use_live_calibration_var.get()),
                "windows_by_node": self.build_resampled_windows_by_node(),
                "resampled_window": {
                    "source": "gui_recent_seconds",
                    "seconds": self.resample_seconds,
                    "model_timesteps": hub.WINDOW_SIZE,
                },
            }

    def post_prediction_payload(self, payload, prediction_id, source, node_order, axis_transform, mag_mode):
        payload_summary = hub.summarize_predict_payload(payload)
        hub.write_prediction_log(
            "request",
            prediction_id=prediction_id,
            source=source,
            node_order=list(node_order),
            axis_transform=axis_transform,
            node_axis_transforms=payload.get("node_axis_transforms"),
            mag_mode=mag_mode,
            payload_summary=payload_summary,
        )

        body = json.dumps(payload).encode("utf-8")
        req = request.Request(
            hub.PREDICT_URL,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        started_at = time.perf_counter()

        with request.urlopen(req, timeout=5.0) as response:
            raw = response.read().decode("utf-8", errors="ignore")
            result = json.loads(raw) if raw else {}

        hub.write_prediction_log(
            "success",
            prediction_id=prediction_id,
            source=source,
            node_order=list(node_order),
            axis_transform=axis_transform,
            node_axis_transforms=payload.get("node_axis_transforms"),
            mag_mode=mag_mode,
            latency_ms=round((time.perf_counter() - started_at) * 1000.0, 2),
            response=result,
        )
        return result

    def run_node_order_test(self):
        ready, status, _, _ = self.get_resample_status()
        self.events.put(("window_text", status))

        if not ready:
            self.log_from_thread(
                f"Order test skipped: prediction window not ready ({status})."
            )
            return

        axis_transform = self.current_axis_transform()
        node_axis_transforms = self.current_node_axis_transforms()
        mag_mode = self.current_mag_mode()
        self.log_from_thread(
            f"Testing all PAMAP2 node orders... axis={axis_transform} "
            f"node_axes={node_axis_transforms} mag={mag_mode}"
        )
        results = []

        for order_text in hub.NODE_ORDER_OPTIONS:
            node_order = hub.parse_node_order(order_text)
            prediction_id = hub.make_prediction_id()
            payload = self.build_payload_from_windows(
                node_order=node_order,
                axis_transform=axis_transform,
                mag_mode=mag_mode,
            )
            payload["order_sweep"] = False

            try:
                result = self.post_prediction_payload(
                    payload,
                    prediction_id,
                    source="gui_order_test",
                    node_order=node_order,
                    axis_transform=axis_transform,
                    mag_mode=mag_mode,
                )
                label = result.get("activity", "unknown")
                confidence = float(result.get("confidence", 0.0))
                probabilities = result.get("probabilities", {})
                results.append((confidence, order_text, label, probabilities))
            except Exception as exc:
                self.log_from_thread(f"Order {order_text}: error {exc}")
                hub.write_prediction_log(
                    "error",
                    prediction_id=prediction_id,
                    source="gui_order_test",
                    node_order=list(node_order),
                    axis_transform=axis_transform,
                    mag_mode=mag_mode,
                    error=repr(exc),
                )

        for confidence, order_text, label, probabilities in sorted(results, reverse=True):
            prob_text = ", ".join(
                f"{name}={float(value):.3f}"
                for name, value in sorted(probabilities.items())
            )
            self.log_from_thread(
                f"Order {order_text}: {label} ({confidence:.3f}) [{prob_text}]"
            )

    def save_calibration_sample(self):
        ready, status, _, _ = self.get_resample_status()
        self.events.put(("window_text", status))

        if not ready:
            self.log_from_thread(
                f"Calibration skipped: prediction window not ready ({status})."
            )
            return

        label = self.config_target_var.get()
        payload = self.build_payload_from_windows()
        payload["label"] = label

        try:
            body = json.dumps(payload).encode("utf-8")
            req = request.Request(
                hub.PREDICT_URL.rsplit("/", 1)[0] + "/calibration/sample",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )

            with request.urlopen(req, timeout=10.0) as response:
                raw = response.read().decode("utf-8", errors="ignore")
                result = json.loads(raw) if raw else {}

            counts = result.get("counts", {})
            counts_text = ", ".join(
                f"{name}={count}"
                for name, count in sorted(counts.items())
            )
            self.log_from_thread(
                f"Calibration saved for {label}. Samples: {counts_text or result.get('sample_count')}"
            )
        except error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="ignore")
            self.log_from_thread(f"Calibration HTTP error {exc.code}: {raw}")
        except Exception as exc:
            self.log_from_thread(f"Calibration error: {exc}")

    def clear_calibration_samples(self):
        try:
            req = request.Request(
                hub.PREDICT_URL.rsplit("/", 1)[0] + "/calibration/clear",
                data=b"{}",
                headers={"Content-Type": "application/json"},
                method="POST",
            )

            with request.urlopen(req, timeout=10.0) as response:
                response.read()

            self.log_from_thread("Live calibration cleared.")
        except error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="ignore")
            self.log_from_thread(f"Clear calibration HTTP error {exc.code}: {raw}")
        except Exception as exc:
            self.log_from_thread(f"Clear calibration error: {exc}")

    def save_pamap2_calibration_sample(self):
        ready, status, _, _ = self.get_resample_status()
        self.events.put(("window_text", status))

        if not ready:
            self.log_from_thread(
                f"PAMAP2 calibration skipped: prediction window not ready ({status})."
            )
            return

        label = self.config_target_var.get()
        payload = self.build_payload_from_windows()
        payload["label"] = label
        payload["target_activity"] = label

        try:
            body = json.dumps(payload).encode("utf-8")
            req = request.Request(
                hub.PREDICT_URL.rstrip("/") + "/pamap2_calibration/sample",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )

            with request.urlopen(req, timeout=20.0) as response:
                raw = response.read().decode("utf-8", errors="ignore")
                result = json.loads(raw) if raw else {}

            counts = result.get("counts", {})
            counts_text = ", ".join(
                f"{name}={count}"
                for name, count in sorted(counts.items())
            )
            self.log_from_thread(
                f"PAMAP2 window saved for {label}. Samples: {counts_text or result.get('sample_count')}"
            )
        except error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="ignore")
            self.log_from_thread(f"PAMAP2 save HTTP error {exc.code}: {raw}")
        except Exception as exc:
            self.log_from_thread(f"PAMAP2 save error: {exc}")

    def clear_pamap2_calibration_samples(self):
        try:
            req = request.Request(
                hub.PREDICT_URL.rstrip("/") + "/pamap2_calibration/clear",
                data=b"{}",
                headers={"Content-Type": "application/json"},
                method="POST",
            )

            with request.urlopen(req, timeout=10.0) as response:
                response.read()

            self.log_from_thread("PAMAP2 calibration set cleared.")
        except error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="ignore")
            self.log_from_thread(f"PAMAP2 clear HTTP error {exc.code}: {raw}")
        except Exception as exc:
            self.log_from_thread(f"PAMAP2 clear error: {exc}")

    def run_pamap2_calibration_sweep(self):
        if self.pamap2_sweep_running:
            self.log_from_thread("PAMAP2 calibration sweep is already running.")
            return

        self.pamap2_sweep_running = True
        prediction_id = hub.make_prediction_id()
        payload = {
            "node_orders": "all",
            "axis_transforms": "all" if self.sweep_axis_var.get() else [self.current_axis_transform()],
            "mag_modes": ["raw", "zero", "center", "div100", "center_div100"],
            "top_n": 30,
        }

        if not self.sweep_axis_var.get():
            payload["node_axis_transforms"] = {
                str(node_id): node_axis
                for node_id, node_axis in self.current_node_axis_transforms().items()
            }

        self.log_from_thread(
            "Running PAMAP2 calibration sweep across saved labeled windows... "
            f"axis_sweep={self.sweep_axis_var.get()} ({prediction_id})"
        )
        hub.write_prediction_log(
            "pamap2_calibration_sweep_request",
            prediction_id=prediction_id,
            source="gui_pamap2_calibration",
            payload=payload,
        )

        try:
            body = json.dumps(payload).encode("utf-8")
            req = request.Request(
                hub.PREDICT_URL.rstrip("/") + "/pamap2_calibration/sweep",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            started_at = time.perf_counter()

            with request.urlopen(req, timeout=300.0) as response:
                raw = response.read().decode("utf-8", errors="ignore")
                result = json.loads(raw) if raw else {}

            latency_ms = round((time.perf_counter() - started_at) * 1000.0, 2)
            best = result.get("best_config") or {}
            hub.write_prediction_log(
                "pamap2_calibration_sweep_success",
                prediction_id=prediction_id,
                source="gui_pamap2_calibration",
                latency_ms=latency_ms,
                response=result,
            )

            self.log_from_thread(
                f"PAMAP2 calibration sweep done: samples={result.get('sample_count')} "
                f"tested={result.get('tested_configs')} latency={latency_ms}ms"
            )

            if best:
                config = {
                    "pamap2_node_order": best.get("node_order"),
                    "pamap2_axis_transform": best.get("axis_transform"),
                    "pamap2_node_axis_transforms": best.get("node_axis_transforms"),
                    "pamap2_mag_mode": best.get("mag_mode"),
                }
                self.events.put(("backend_config", config))
                self.log_from_thread(
                    f"Best PAMAP2 config applied: score={float(best.get('score') or 0):.3f} "
                    f"acc={float(best.get('accuracy') or 0):.3f} "
                    f"target={float(best.get('mean_target_probability') or 0):.3f} "
                    f"order={','.join(str(n) for n in best.get('node_order', []))} "
                    f"axis={best.get('axis_transform')} mag={best.get('mag_mode')}"
                )

            for index, item in enumerate(result.get("results", [])[:10], start=1):
                per_label = item.get("per_label", {})
                label_text = "; ".join(
                    f"{label}:{float(stats.get('accuracy') or 0):.2f}/"
                    f"{float(stats.get('mean_target_probability') or 0):.2f}"
                    for label, stats in sorted(per_label.items())
                )
                self.log_from_thread(
                    f"#{index} score={float(item.get('score') or 0):.3f} "
                    f"acc={float(item.get('accuracy') or 0):.3f} "
                    f"target={float(item.get('mean_target_probability') or 0):.3f} "
                    f"order={','.join(str(n) for n in item.get('node_order', []))} "
                    f"axis={item.get('axis_transform')} mag={item.get('mag_mode')} "
                    f"[{label_text}]"
                )

        except error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="ignore")
            self.log_from_thread(f"PAMAP2 sweep HTTP error {exc.code}: {raw}")
            hub.write_prediction_log(
                "pamap2_calibration_sweep_http_error",
                prediction_id=prediction_id,
                source="gui_pamap2_calibration",
                http_status=exc.code,
                error=raw,
            )
        except Exception as exc:
            self.log_from_thread(f"PAMAP2 sweep error: {exc}")
            hub.write_prediction_log(
                "pamap2_calibration_sweep_error",
                prediction_id=prediction_id,
                source="gui_pamap2_calibration",
                error=repr(exc),
            )
        finally:
            self.pamap2_sweep_running = False

    def run_preprocess_config_test(self):
        ready, status, _, _ = self.get_resample_status()
        self.events.put(("window_text", status))

        if not ready:
            self.log_from_thread(
                f"Config test skipped: prediction window not ready ({status})."
            )
            return

        target_activity = self.config_target_var.get()
        prediction_id = hub.make_prediction_id()
        payload = self.build_payload_from_windows()
        axis_transforms = "all" if self.sweep_axis_var.get() else [payload["axis_transform"]]
        mag_modes = "all" if self.sweep_axis_var.get() else ["raw", "zero", "center", "div100"]

        if self.sweep_axis_var.get():
            # Let the backend apply each global axis transform to every node.
            # Sending fixed node axes here would override the global sweep.
            payload.pop("node_axis_transforms", None)

        payload.update({
            "node_orders": "all",
            "axis_transforms": axis_transforms,
            "mag_modes": mag_modes,
            "target_activity": target_activity,
            "top_n": 30,
        })

        self.log_from_thread(
            f"Testing configs for target={target_activity} with selected node axes; "
            f"axis_sweep={self.sweep_axis_var.get()}... ({prediction_id})"
        )
        hub.write_prediction_log(
            "config_sweep_request",
            prediction_id=prediction_id,
            source="gui_config_sweep",
            target_activity=target_activity,
            node_orders="all",
            axis_transforms=payload["axis_transforms"],
            node_axis_transforms=payload.get("node_axis_transforms"),
            mag_modes=payload["mag_modes"],
            payload_summary=hub.summarize_predict_payload(payload),
        )

        try:
            body = json.dumps(payload).encode("utf-8")
            req = request.Request(
                hub.PREDICT_URL.rstrip("/") + "/config_sweep",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            started_at = time.perf_counter()

            with request.urlopen(req, timeout=120.0) as response:
                raw = response.read().decode("utf-8", errors="ignore")
                result = json.loads(raw) if raw else {}

            latency_ms = round((time.perf_counter() - started_at) * 1000.0, 2)
            hub.write_prediction_log(
                "config_sweep_success",
                prediction_id=prediction_id,
                source="gui_config_sweep",
                target_activity=target_activity,
                latency_ms=latency_ms,
                response=result,
            )

            self.log_from_thread(
                f"Config sweep done: tested={result.get('tested_configs')} latency={latency_ms}ms"
            )

            for index, item in enumerate(result.get("results", [])[:12], start=1):
                probabilities = item.get("probabilities", {})
                prob_text = ", ".join(
                    f"{name}={float(value):.3f}"
                    for name, value in sorted(probabilities.items())
                )
                self.log_from_thread(
                    f"#{index} score={float(item.get('score') or 0):.3f} "
                    f"target={float(item.get('target_probability') or 0):.3f} "
                    f"top={item.get('activity')}({float(item.get('confidence') or 0):.3f}) "
                    f"order={','.join(str(n) for n in item.get('node_order', []))} "
                    f"axis={item.get('axis_transform')} mag={item.get('mag_mode')} "
                    f"[{prob_text}]"
                )

        except error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="ignore")
            self.log_from_thread(f"Config sweep HTTP error {exc.code}: {raw}")
            hub.write_prediction_log(
                "config_sweep_http_error",
                prediction_id=prediction_id,
                source="gui_config_sweep",
                target_activity=target_activity,
                http_status=exc.code,
                error=raw,
            )
        except Exception as exc:
            self.log_from_thread(f"Config sweep error: {exc}")
            hub.write_prediction_log(
                "config_sweep_error",
                prediction_id=prediction_id,
                source="gui_config_sweep",
                target_activity=target_activity,
                error=repr(exc),
            )

    def maybe_predict(self, force=False):
        ready, status, _, _ = self.get_resample_status()
        self.events.put(("window_text", status))

        if not ready:
            if force:
                self.log_from_thread(
                    f"Predict skipped: prediction window not ready ({status})."
                )
            return

        if not force:
            self.rows_since_prediction += 1

        if not force and self.rows_since_prediction < hub.PREDICT_EVERY:
            return

        self.rows_since_prediction = 0
        node_order = self.current_node_order()
        axis_transform = self.current_axis_transform()
        node_axis_transforms = self.current_node_axis_transforms()
        mag_mode = self.current_mag_mode()
        payload = self.build_payload_from_windows(
            node_order=node_order,
            axis_transform=axis_transform,
            node_axis_transforms=node_axis_transforms,
            mag_mode=mag_mode,
        )

        prediction_id = hub.make_prediction_id()
        source = "gui_manual" if force else "gui_auto"
        self.log_from_thread(
            f"Posting PAMAP2 prediction window to backend... ({prediction_id}, "
            f"order={','.join(str(n) for n in node_order)} axis={axis_transform} "
            f"node_axes={node_axis_transforms} mag={mag_mode})"
        )

        try:
            result = self.post_prediction_payload(
                payload,
                prediction_id,
                source=source,
                node_order=node_order,
                axis_transform=axis_transform,
                mag_mode=mag_mode,
            )

            label = result.get("activity", "unknown")
            confidence = result.get("confidence", "?")
            classifier = result.get("classifier", "pamap2")
            pamap2_label = result.get("pamap2_activity")
            pamap2_confidence = result.get("pamap2_confidence")
            display = f"{label} ({confidence})"

            if classifier == "live_calibrated" and pamap2_label:
                display = f"{display} | calib, PAMAP2={pamap2_label}({pamap2_confidence})"

            self.events.put(("prediction", display))
            self.log_from_thread(
                f"Prediction: {display} id={result.get('prediction_id', prediction_id)}"
            )

        except error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="ignore")
            self.log_from_thread(f"Prediction HTTP error {exc.code}: {raw}")
            self.events.put(("prediction", "ERROR"))
            hub.write_prediction_log(
                "http_error",
                prediction_id=prediction_id,
                source=source,
                node_order=list(node_order),
                axis_transform=axis_transform,
                mag_mode=mag_mode,
                http_status=exc.code,
                error=raw,
            )
        except Exception as exc:
            self.log_from_thread(f"Prediction error: {exc}")
            self.events.put(("prediction", "ERROR"))
            hub.write_prediction_log(
                "error",
                prediction_id=prediction_id,
                source=source,
                node_order=list(node_order),
                axis_transform=axis_transform,
                mag_mode=mag_mode,
                error=repr(exc),
            )

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
                        self.status_vars[node_id].set("Receiving")
                    else:
                        self.sample_vars[node_id].set(f"Latest raw: {line}")
                    if show_line:
                        self.log(f"Node {node_id}: {line}")
                elif kind == "window":
                    window_len = event[1]
                    self.window_var.set(f"Window: {window_len}/{hub.WINDOW_SIZE}")
                elif kind == "window_text":
                    self.window_var.set(f"Window: {event[1]}")
                elif kind == "prediction":
                    prediction = event[1]
                    self.prediction_var.set(f"Prediction: {prediction}")
                elif kind == "dataset_status":
                    self.dataset_status_var.set(event[1])
                elif kind == "backend_config":
                    config = event[1]
                    best_config = config.get("pamap2_best_config") or {}
                    node_order = best_config.get("node_order") or config.get("pamap2_node_order")
                    axis_transform = (
                        best_config.get("axis_transform")
                        or config.get("pamap2_axis_transform")
                    )
                    node_axis_transforms = (
                        best_config.get("node_axis_transforms")
                        or config.get("pamap2_node_axis_transforms")
                        or {}
                    )
                    mag_mode = best_config.get("mag_mode") or config.get("pamap2_mag_mode")

                    if node_order:
                        self.node_order_var.set(",".join(str(node_id) for node_id in node_order))

                    if axis_transform:
                        self.axis_transform_var.set(hub.parse_axis_transform(axis_transform))

                    for node_id in (1, 2, 3):
                        node_axis = node_axis_transforms.get(str(node_id), node_axis_transforms.get(node_id))

                        if node_axis:
                            self.node_axis_vars[node_id].set(hub.parse_axis_transform(node_axis))

                    if mag_mode:
                        self.mag_mode_var.set(hub.parse_mag_mode(mag_mode))

                    self.log(
                        "Synced backend config: "
                        f"order={self.node_order_var.get()} "
                        f"axes={{1:{self.node_axis_vars[1].get()}, "
                        f"2:{self.node_axis_vars[2].get()}, "
                        f"3:{self.node_axis_vars[3].get()}}} "
                        f"mag={self.mag_mode_var.get()}"
                    )
                elif kind == "disconnect":
                    self.disconnect_node(event[1])
        except queue.Empty:
            pass

        self.root.after(80, self.drain_events)

    def on_close(self):
        with self.lock:
            collection_active = bool(self.dataset_collection and self.dataset_collection.get("active"))

        if collection_active:
            self.finish_dataset_collection(status="stopped", from_thread=False)

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
