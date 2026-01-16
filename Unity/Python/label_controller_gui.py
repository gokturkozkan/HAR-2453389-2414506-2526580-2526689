import argparse
import json
import socket
import threading
import tkinter as tk
from tkinter import messagebox


DEFAULT_REMOTE_PORT = 5010


class RemoteControllerClient:
    def __init__(self):
        self._lock = threading.Lock()
        self._sock: socket.socket | None = None
        self._reader = None
        self._writer = None
        self._next_id = 1

    def connect(self, host: str, port: int, timeout: float = 5.0) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect((host, port))
        sock.settimeout(timeout)

        with self._lock:
            self._sock = sock
            self._reader = sock.makefile("r", encoding="utf-8", newline="\n")
            self._writer = sock.makefile("w", encoding="utf-8", newline="\n")
            self._next_id = 1

    def close(self) -> None:
        with self._lock:
            if self._sock is None:
                return
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
            self._reader = None
            self._writer = None

    def request(self, cmd: str, **kwargs):
        with self._lock:
            if self._sock is None or self._reader is None or self._writer is None:
                raise ConnectionError("Not connected to remote controller")
            req_id = self._next_id
            self._next_id += 1

            payload = {"cmd": cmd, "id": req_id, **kwargs}
            self._writer.write(json.dumps(payload, ensure_ascii=False) + "\n")
            self._writer.flush()

            line = self._reader.readline()
            if not line:
                raise ConnectionError("Remote controller closed connection")
            resp = json.loads(line)
            return resp


class LabelControllerGUI:
    def __init__(self, root, default_host: str = "", default_port: int = DEFAULT_REMOTE_PORT):
        self.root = root
        self.root.title("HAR Label Controller")
        self.root.geometry("460x420")
        self.root.resizable(False, False)

        self.client = RemoteControllerClient()
        self.connected_to_remote = False
        self.bridge_connected = False
        self.pairing_code = "------"

        self.remote_host_var = tk.StringVar(value=default_host)
        self.remote_port_var = tk.StringVar(value=str(default_port))

        self.create_widgets()

        self._polling = True
        threading.Thread(target=self._poll_loop, daemon=True).start()
    
    def create_widgets(self):
        # Title
        title_frame = tk.Frame(self.root, bg="#2c3e50", pady=15)
        title_frame.pack(fill=tk.X)
        
        title_label = tk.Label(
            title_frame, 
            text="HAR Label Controller", 
            font=("Arial", 18, "bold"),
            bg="#2c3e50",
            fg="white"
        )
        title_label.pack()
        
        # Remote connection section
        remote_frame = tk.Frame(self.root, pady=12)
        remote_frame.pack(fill=tk.X, padx=20)

        tk.Label(remote_frame, text="Remote Controller IP/Host:", font=("Arial", 10)).grid(row=0, column=0, sticky="w")
        tk.Entry(remote_frame, textvariable=self.remote_host_var, width=22).grid(row=0, column=1, padx=8)

        tk.Label(remote_frame, text="Port:", font=("Arial", 10)).grid(row=0, column=2, sticky="e")
        tk.Entry(remote_frame, textvariable=self.remote_port_var, width=6).grid(row=0, column=3, padx=6)

        self.connect_btn = tk.Button(remote_frame, text="Connect", command=self.connect_to_remote, width=10)
        self.connect_btn.grid(row=1, column=0, pady=8, sticky="w")
        self.disconnect_btn = tk.Button(remote_frame, text="Disconnect", command=self.disconnect_from_remote, width=10, state=tk.DISABLED)
        self.disconnect_btn.grid(row=1, column=1, pady=8, sticky="w")

        # Pairing code section
        pairing_frame = tk.Frame(self.root, pady=10)
        pairing_frame.pack(fill=tk.X, padx=20)
        
        pairing_label = tk.Label(
            pairing_frame,
            text="Pairing Code:",
            font=("Arial", 12)
        )
        pairing_label.pack()
        
        code_frame = tk.Frame(pairing_frame, bg="#3498db", pady=10, padx=20)
        code_frame.pack(pady=10)
        
        code_label = tk.Label(
            code_frame,
            text=self.pairing_code,
            font=("Courier New", 24, "bold"),
            bg="#3498db",
            fg="white"
        )
        code_label.pack()
        self.code_label = code_label
        
        # Status
        self.status_label = tk.Label(
            pairing_frame,
            text="Not connected to remote controller",
            font=("Arial", 10),
            fg="#e74c3c"
        )
        self.status_label.pack(pady=5)
        
        # Instructions
        instructions = tk.Label(
            pairing_frame,
            text="Start bridge_server.py on Unity PC with this SAME code",
            font=("Arial", 9),
            fg="#7f8c8d"
        )
        instructions.pack()
        
        # Buttons frame
        buttons_frame = tk.Frame(self.root, pady=20)
        buttons_frame.pack(fill=tk.X, padx=20)
        
        button_style = {
            "font": ("Arial", 14, "bold"),
            "width": 15,
            "height": 2,
            "relief": tk.RAISED,
            "bd": 3
        }
        
        # Walk button
        self.walk_btn = tk.Button(
            buttons_frame,
            text="🚶 WALK",
            bg="#27ae60",
            fg="white",
            command=lambda: self.send_label("walking"),
            state=tk.DISABLED,
            **button_style
        )
        self.walk_btn.pack(pady=5)
        
        # Idle button
        self.idle_btn = tk.Button(
            buttons_frame,
            text="🧍 IDLE",
            bg="#f39c12",
            fg="white",
            command=lambda: self.send_label("idle"),
            state=tk.DISABLED,
            **button_style
        )
        self.idle_btn.pack(pady=5)
        
        # Sit button
        self.sit_btn = tk.Button(
            buttons_frame,
            text="🪑 SIT",
            bg="#3498db",
            fg="white",
            command=lambda: self.send_label("sitting"),
            state=tk.DISABLED,
            **button_style
        )
        self.sit_btn.pack(pady=5)

    def connect_to_remote(self):
        host = self.remote_host_var.get().strip()
        if not host:
            messagebox.showwarning("Missing host", "Enter Remote Controller IP/Host")
            return

        try:
            port = int(self.remote_port_var.get().strip())
        except ValueError:
            messagebox.showwarning("Invalid port", "Port must be a number")
            return

        def do_connect():
            try:
                self.client.connect(host, port)
                self.connected_to_remote = True
                self.root.after(0, lambda: self._set_connected_ui(True))
                self.update_status("Connected to remote controller", "#27ae60")
            except Exception as e:
                self.connected_to_remote = False
                self.root.after(0, lambda: self._set_connected_ui(False))
                self.update_status(f"Remote connect failed: {e}", "#e74c3c")

        threading.Thread(target=do_connect, daemon=True).start()

    def disconnect_from_remote(self):
        self.client.close()
        self.connected_to_remote = False
        self.bridge_connected = False
        self.pairing_code = "------"
        self.code_label.config(text=self.pairing_code)
        self._set_connected_ui(False)
        self.update_status("Disconnected", "#e74c3c")

    def _set_connected_ui(self, connected: bool):
        self.connect_btn.config(state=(tk.DISABLED if connected else tk.NORMAL))
        self.disconnect_btn.config(state=(tk.NORMAL if connected else tk.DISABLED))
        if not connected:
            self.walk_btn.config(state=tk.DISABLED)
            self.idle_btn.config(state=tk.DISABLED)
            self.sit_btn.config(state=tk.DISABLED)
    
    def update_status(self, text, color):
        """Thread-safe status update"""
        self.root.after(0, lambda: self.status_label.config(text=text, fg=color))
    
    def _enable_buttons(self, enabled: bool):
        def apply():
            st = tk.NORMAL if enabled else tk.DISABLED
            self.walk_btn.config(state=st)
            self.idle_btn.config(state=st)
            self.sit_btn.config(state=st)

        self.root.after(0, apply)
    
    def send_label(self, label: str):
        if not self.connected_to_remote:
            messagebox.showwarning("Not Connected", "Not connected to remote controller.")
            return

        def do_send():
            try:
                resp = self.client.request("send_label", label=label)
                if resp.get("ok"):
                    self.update_status(f"Sent: {label.upper()}", "#27ae60")
                    self.flash_button(label)
                else:
                    self.update_status(f"Send failed: {resp.get('error') or resp.get('message')}", "#e74c3c")
            except Exception as e:
                self.update_status(f"Send failed: {e}", "#e74c3c")

        threading.Thread(target=do_send, daemon=True).start()
    
    def flash_button(self, label):
        """Visual feedback for button press"""
        btn_map = {
            "walking": self.walk_btn,
            "idle": self.idle_btn,
            "sitting": self.sit_btn
        }
        
        btn = btn_map.get(label)
        if btn:
            original_bg = btn.cget("bg")
            btn.config(relief=tk.SUNKEN)
            self.root.after(200, lambda: btn.config(relief=tk.RAISED))
    
    def on_closing(self):
        """Clean up on window close"""
        self._polling = False
        self.client.close()
        self.root.destroy()

    def _poll_loop(self):
        while self._polling:
            try:
                if self.connected_to_remote:
                    resp = self.client.request("get_state")
                    if resp.get("ok") and isinstance(resp.get("state"), dict):
                        state = resp["state"]
                        code = state.get("pairing_code") or "------"
                        bridge_ok = bool(state.get("bridge_connected"))
                        last_error = state.get("last_error")

                        def apply():
                            self.pairing_code = code
                            self.code_label.config(text=code)
                            self.bridge_connected = bridge_ok
                            if bridge_ok:
                                self.status_label.config(text="Remote connected to Unity bridge", fg="#27ae60")
                                self._enable_buttons(True)
                            else:
                                msg = "Remote NOT connected to Unity bridge"
                                if last_error:
                                    msg += f" ({last_error})"
                                self.status_label.config(text=msg, fg="#e67e22")
                                self._enable_buttons(False)

                        self.root.after(0, apply)

            except Exception:
                # If remote drops, show it but don't spam popups.
                self.connected_to_remote = False
                self.root.after(0, lambda: self._set_connected_ui(False))
                self.update_status("Remote controller disconnected", "#e74c3c")
                self.client.close()

            finally:
                threading.Event().wait(1.0)

def main():
    parser = argparse.ArgumentParser(description="GUI client for remote_controller.py")
    parser.add_argument("--remote-host", default="", help="Remote controller IP/Host")
    parser.add_argument("--remote-port", type=int, default=DEFAULT_REMOTE_PORT)
    args = parser.parse_args()

    root = tk.Tk()
    app = LabelControllerGUI(root, default_host=args.remote_host, default_port=args.remote_port)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()

if __name__ == "__main__":
    main()