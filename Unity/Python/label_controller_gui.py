import tkinter as tk
from tkinter import ttk, messagebox
import threading
import socket
import json
from datetime import datetime
import hmac
import hashlib
import random
import string
import time
import requests

# Flask backend configuration
FLASK_BACKEND_URL = "http://192.168.1.100:3000"  # Change this to your Raspberry Pi IP

DISCOVERY_PORT = 5006
DISCOVERY_TIMEOUT = 3.0

# Must match SALT in bridge_server.py
SALT = b"unity-bridge-salt-01"

def generate_pairing_code(length=6) -> str:
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))

def compute_secret_hash(code: str) -> str:
    return hmac.new(SALT, code.encode("utf-8"), hashlib.sha256).hexdigest()

def discover_bridge(secret_hash: str):
    message = f"DISCOVER {secret_hash}".encode("utf-8")

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.settimeout(DISCOVERY_TIMEOUT)

        s.sendto(message, ("255.255.255.255", DISCOVERY_PORT))

        while True:
            try:
                data, addr = s.recvfrom(1024)
            except socket.timeout:
                raise TimeoutError("No Unity bridge found.")

            reply = data.decode("utf-8", errors="ignore").strip()

            if reply.startswith("BRIDGE_OK "):
                port_str = reply.split(" ", 1)[1]
                port = int(port_str)
                ip = addr[0]
                return ip, port

class LabelControllerGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("HAR Label Controller")
        self.root.geometry("450x500")
        self.root.resizable(False, False)
        
        # Generate pairing code for Unity
        self.pairing_code = generate_pairing_code()
        self.secret_hash = compute_secret_hash(self.pairing_code)
        self.unity_sock = None
        self.unity_connected = False
        
        # Flask backend
        self.backend_url = FLASK_BACKEND_URL
        self.flask_connected = False
        
        # Create UI
        self.create_widgets()
        
        # Connect to both Unity bridge and Flask backend
        threading.Thread(target=self.connect_to_unity, daemon=True).start()
        threading.Thread(target=self.connect_to_flask, daemon=True).start()
    
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
        
        # Pairing code section for Unity
        pairing_frame = tk.Frame(self.root, pady=10)
        pairing_frame.pack(fill=tk.X, padx=20)
        
        pairing_label = tk.Label(
            pairing_frame,
            text="Unity Pairing Code:",
            font=("Arial", 11, "bold")
        )
        pairing_label.pack()
        
        code_frame = tk.Frame(pairing_frame, bg="#9b59b6", pady=8, padx=20)
        code_frame.pack(pady=5)
        
        code_label = tk.Label(
            code_frame,
            text=self.pairing_code,
            font=("Courier New", 20, "bold"),
            bg="#9b59b6",
            fg="white"
        )
        code_label.pack()
        
        # Unity connection status
        self.unity_status_label = tk.Label(
            pairing_frame,
            text="Unity: Connecting...",
            font=("Arial", 9),
            fg="#e67e22"
        )
        self.unity_status_label.pack(pady=2)
        
        # Flask backend section
        flask_frame = tk.Frame(self.root, pady=10)
        flask_frame.pack(fill=tk.X, padx=20)
        
        flask_label = tk.Label(
            flask_frame,
            text="Flask Backend URL:",
            font=("Arial", 10)
        )
        flask_label.pack()
        
        self.url_entry = tk.Entry(
            flask_frame,
            font=("Arial", 9),
            width=35
        )
        self.url_entry.insert(0, FLASK_BACKEND_URL)
        self.url_entry.pack(pady=5)
        
        connect_btn = tk.Button(
            flask_frame,
            text="Update & Reconnect",
            bg="#3498db",
            fg="white",
            font=("Arial", 9),
            command=self.update_backend_url
        )
        connect_btn.pack()
        
        # Flask connection status
        self.flask_status_label = tk.Label(
            flask_frame,
            text="Flask: Connecting...",
            font=("Arial", 9),
            fg="#e67e22"
        )
        self.flask_status_label.pack(pady=2)
        
        # Buttons frame
        buttons_frame = tk.Frame(self.root, pady=15)
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
    
    def connect_to_unity(self):
        """Connect to Unity bridge server"""
        retry_interval = 2.0
        max_retries = 60
        retries = 0
        
        while retries < max_retries and not self.unity_connected:
            try:
                host, port = discover_bridge(self.secret_hash)
                self.unity_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.unity_sock.connect((host, port))
                
                self.unity_connected = True
                self.update_unity_status("Unity: Connected!", "#27ae60")
                self.check_enable_buttons()
                print(f"Connected to Unity bridge at {host}:{port}")
                return
                
            except (TimeoutError, ConnectionRefusedError, OSError) as e:
                retries += 1
                if retries < max_retries:
                    self.update_unity_status(f"Unity: Waiting... ({retries}/{max_retries})", "#e67e22")
                    time.sleep(retry_interval)
                else:
                    self.update_unity_status("Unity: Failed (optional)", "#95a5a6")
    
    def connect_to_flask(self):
        """Connect to Flask backend"""
        retry_interval = 2.0
        max_retries = 30
        retries = 0
        
        while retries < max_retries and not self.flask_connected:
            try:
                response = requests.get(f"{self.backend_url}/health", timeout=3)
                if response.status_code == 200:
                    self.flask_connected = True
                    self.update_flask_status("Flask: Connected!", "#27ae60")
                    self.check_enable_buttons()
                    print(f"Connected to Flask backend at {self.backend_url}")
                    return
                else:
                    raise Exception(f"Backend returned {response.status_code}")
                    
            except Exception as e:
                retries += 1
                if retries < max_retries:
                    self.update_flask_status(f"Flask: Waiting... ({retries}/{max_retries})", "#e67e22")
                    time.sleep(retry_interval)
                else:
                    self.update_flask_status("Flask: Failed (optional)", "#95a5a6")
    
    def update_backend_url(self):
        """Update backend URL and reconnect"""
        new_url = self.url_entry.get().strip()
        if new_url:
            self.backend_url = new_url
            self.flask_connected = False
            self.update_flask_status("Flask: Reconnecting...", "#e67e22")
            threading.Thread(target=self.connect_to_flask, daemon=True).start()
    
    def update_unity_status(self, text, color):
        """Thread-safe Unity status update"""
        self.root.after(0, lambda: self.unity_status_label.config(text=text, fg=color))
    
    def update_flask_status(self, text, color):
        """Thread-safe Flask status update"""
        self.root.after(0, lambda: self.flask_status_label.config(text=text, fg=color))
    
    def check_enable_buttons(self):
        """Enable buttons if at least one connection is active"""
        if self.unity_connected or self.flask_connected:
            self.enable_buttons()
    
    def enable_buttons(self):
        """Thread-safe button enabler"""
        def enable():
            self.walk_btn.config(state=tk.NORMAL)
            self.idle_btn.config(state=tk.NORMAL)
            self.sit_btn.config(state=tk.NORMAL)
        
        self.root.after(0, enable)
    
    def send_label(self, label: str):
        """Send label to BOTH Unity bridge AND Flask backend"""
        success_unity = False
        success_flask = False
        
        # Send to Unity bridge
        if self.unity_connected and self.unity_sock:
        if self.unity_sock:
            try:
                self.unity_sock.close()
            except:
                pass
            try:
                msg = {
                    "label": label,
            try:
                msg = {
                    "label": label,
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                    "source": "gui-controller",
                    "secret": self.secret_hash
                }
                line = json.dumps(msg, ensure_ascii=False) + "\n"
                self.unity_sock.sendall(line.encode("utf-8"))
                success_unity = True
                print(f"Sent to Unity: {label}")
            except Exception as e:
                print(f"Unity send failed: {e}")
                self.update_unity_status("Unity: Send failed!", "#e74c3c")
        
        # Send to Flask backend
        if self.flask_connected:
            try:
                response = requests.post(
                    f"{self.backend_url}/label",
                    json={"label": label},
                    headers={"Content-Type": "application/json"},
                    timeout=5
                )
                
                if response.status_code == 200:
                    success_flask = True
                    print(f"Sent to Flask: {label}")
                else:
                    raise Exception(f"Backend returned {response.status_code}")
                
            except Exception as e:
                print(f"Flask send failed: {e}")
                self.update_flask_status("Flask: Send failed!", "#e74c3c")
        
        # Update UI
        if success_unity or success_flask:
            self.flash_button(label)
            destinations = []
            if success_unity:
                destinations.append("Unity")
            if success_flask:
                destinations.append("Flask")
            print(f"Label '{label}' sent to: {', '.join(destinations)}")
        else:
            messagebox.showwarning("Send Failed", "Failed to send to any destination!
        
        btn = btn_map.get(label)
        if btn:
            original_bg = btn.cget("bg")
            btn.config(relief=tk.SUNKEN)
            self.root.after(200, lambda: btn.config(relief=tk.RAISED))
    
    def on_closing(self):
        """Clean up on window close"""
        self.root.destroy()

def main():
    root = tk.Tk()
    app = LabelControllerGUI(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()

if __name__ == "__main__":
    main()
if self.unity_sock:
            try:
                self.unity_sock.close()
            except:
                pass
        