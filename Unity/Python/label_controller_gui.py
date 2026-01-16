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
        self.root.geometry("400x350")
        self.root.resizable(False, False)
        
        # Generate pairing code
        self.pairing_code = generate_pairing_code()
        self.secret_hash = compute_secret_hash(self.pairing_code)
        self.sock = None
        self.connected = False
        
        # Create UI
        self.create_widgets()
        
        # Auto-connect in background
        self.connection_thread = threading.Thread(target=self.auto_connect, daemon=True)
        self.connection_thread.start()
    
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
        
        # Pairing code section
        pairing_frame = tk.Frame(self.root, pady=20)
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
        
        # Status
        self.status_label = tk.Label(
            pairing_frame,
            text="Connecting to bridge...",
            font=("Arial", 10),
            fg="#e67e22"
        )
        self.status_label.pack(pady=5)
        
        # Instructions
        instructions = tk.Label(
            pairing_frame,
            text="Enter this code in Unity and press Connect",
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
    
    def auto_connect(self):
        """Auto-connect with retries until bridge is available"""
        retry_interval = 2.0
        max_retries = 60
        retries = 0
        
        while retries < max_retries and not self.connected:
            try:
                host, port = discover_bridge(self.secret_hash)
                self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.sock.connect((host, port))
                
                self.connected = True
                self.update_status("Connected!", "#27ae60")
                self.enable_buttons()
                print(f"Connected to bridge at {host}:{port}")
                return
                
            except (TimeoutError, ConnectionRefusedError, OSError) as e:
                retries += 1
                if retries < max_retries:
                    self.update_status(f"Waiting for bridge... ({retries}/{max_retries})", "#e67e22")
                    time.sleep(retry_interval)
                else:
                    self.update_status("Connection failed!", "#e74c3c")
                    messagebox.showerror("Connection Error", "Failed to connect to bridge server.")
    
    def update_status(self, text, color):
        """Thread-safe status update"""
        self.root.after(0, lambda: self.status_label.config(text=text, fg=color))
    
    def enable_buttons(self):
        """Thread-safe button enabler"""
        def enable():
            self.walk_btn.config(state=tk.NORMAL)
            self.idle_btn.config(state=tk.NORMAL)
            self.sit_btn.config(state=tk.NORMAL)
        
        self.root.after(0, enable)
    
    def send_label(self, label: str):
        """Send label to bridge server"""
        if not self.connected or not self.sock:
            messagebox.showwarning("Not Connected", "Not connected to bridge server.")
            return
        
        try:
            msg = {
                "label": label,
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "source": "gui-controller",
                "secret": self.secret_hash
            }
            line = json.dumps(msg, ensure_ascii=False) + "\n"
            self.sock.sendall(line.encode("utf-8"))
            
            print(f"Sent label: {label}")
            self.update_status(f"Sent: {label.upper()}", "#27ae60")
            
            # Flash the button
            self.flash_button(label)
            
        except Exception as e:
            print(f"Error sending label: {e}")
            self.update_status("Send failed!", "#e74c3c")
            messagebox.showerror("Send Error", f"Failed to send label: {e}")
    
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
        if self.sock:
            try:
                self.sock.close()
            except:
                pass
        self.root.destroy()

def main():
    root = tk.Tk()
    app = LabelControllerGUI(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()

if __name__ == "__main__":
    main()
