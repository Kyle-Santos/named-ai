# node_runner.py
import os, sys, socket, json, time, threading, queue, argparse
import NamedAI as NN  

send_queue = queue.Queue()

# -----------------------------
# Define a root path for configs
# -----------------------------
ROOT_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), ""))  
CONFIG_PATH = os.path.join(ROOT_PATH, "node_config.json")

# GUI imports (optional, only if GUI is needed)
GUI_AVAILABLE = False
try:
    from datetime import datetime
    from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QObject
    from PyQt5.QtGui import QFont, QTextCursor
    from PyQt5.QtWidgets import (
        QApplication, QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, QLabel, QLineEdit,
        QPushButton, QTableWidget, QTableWidgetItem, QHeaderView, QFrame
    )
    GUI_AVAILABLE = True
except ImportError:
    pass


def load_node_config(config_path: str, node_name: str):
    """Load node configuration by node_name."""
    with open(config_path, "r") as f:
        config = json.load(f)
    node_config = next(n for n in config["nodes"] if n["name"] == node_name)

    NN.set_ip_addr(config.get("ip", "127.0.0.1"))
    
    NN.NODE_NAME = node_config["name"]
    NN.STORAGE_PATH = node_config.get("storage", "")
    NN.FIB = node_config.get("FIB", {})
    NN.FACES = [iface["face"] for iface in node_config.get("interfaces", [])]
    return node_config


def create_interfaces(node_config):
    return NN.create_interface(node_config["interfaces"])


def receiver(face, entry, gui_callback=None):
    sock = entry["sock"]
    while True:
        try:
            raw_packet, addr = NN.receive_packet(sock)
            parsed, err = NN.parse_packet(raw_packet)

            if err:
                msg = f"[ERROR] {err}"
                print(msg)
                if gui_callback:
                    gui_callback("ERROR", msg)
                continue

            msg = f"Packet received on {face} from {addr}"
            print(f"\n{msg}")
            if gui_callback:
                gui_callback("INFO", msg)

            if parsed["type"] == "interest":
                send_queue.put(("interest", parsed, addr, sock, face))
            elif parsed["type"] == "data":
                send_queue.put(("data", parsed, raw_packet, sock))
        except Exception as e:
            msg = f"[Receiver {face}] Error: {e}"
            print(msg)
            if gui_callback:
                gui_callback("ERROR", msg)


def sender(gui_callback=None):
    while True:
        task = send_queue.get()
        try:
            if task[0] == "interest":
                _, parsed, addr, sock, face = task
                NN.process_interest(parsed, addr, sock, interface=face)
            elif task[0] == "data":
                _, parsed, raw_packet, sock = task
                NN.process_data(parsed, raw_packet, sock)
        except Exception as e:
            msg = f"[Sender] Error: {e}"
            print(msg)
            if gui_callback:
                gui_callback("ERROR", msg)


def run_node(node_name: str, config_path=CONFIG_PATH, gui_callback=None):
    node_config = load_node_config(config_path, node_name)
    interfaces = create_interfaces(node_config)

    # Load storage contents into Content Store
    NN.load_storage_to_cs(NN.STORAGE_PATH)

    msg = f"{NN.NODE_NAME} running with faces: {list(interfaces.keys())}"
    print(f"\033[92m{msg}\033[0m")
    if gui_callback:
        gui_callback("SUCCESS", msg)

    # Start receiver threads
    for face, entry in interfaces.items():
        t = threading.Thread(target=receiver, args=(face, entry, gui_callback), daemon=True)
        t.start()

    # Start sender thread
    threading.Thread(target=sender, args=(gui_callback,), daemon=True).start()

    # Start PIT cleanup thread
    threading.Thread(target=pit_cleanup_worker, args=(gui_callback,), daemon=True).start()

    # Keep alive
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down node...")


def run_client(node_name: str, interest_name=None, config_path=CONFIG_PATH, gui_callback=None):
    node_config = load_node_config(config_path, node_name)
    interfaces = create_interfaces(node_config)

    msg = f"{NN.NODE_NAME} running with faces: {list(interfaces.keys())}"
    print(f"\033[92m{msg}\033[0m")
    if gui_callback:
        gui_callback("SUCCESS", msg)

    entry = interfaces["face0"]
    sock = entry["sock"]

    if interest_name:
        # Build Interest packet
        interest_packet = NN.build_interest_packet(interest_name)
        print(f"[DEBUG] Raw Interest Packet: {interest_packet}")
        print(f"[DEBUG] Packet Size: {len(interest_packet)} bytes")
   
        face, dest_port = NN.lookup_fib(interest_name)
        sock.sendto(interest_packet, (NN.IP_ADDR, dest_port))

        NN.store_interest(interest_name, None, (NN.IP_ADDR, entry["port"]))
        msg = f"Sending Interest for '{interest_name}' at {time.strftime('%H:%M:%S', time.localtime(NN.get_PIT_entry(interest_name)['time']))}"
        print(msg)
        if gui_callback:
            gui_callback("INFO", msg)

    # Start receiver threads
    for face, entry in interfaces.items():
        t = threading.Thread(target=receiver_client, 
                             args=(face, entry, gui_callback))
        t.start()

    # Start PIT cleanup thread
    threading.Thread(target=pit_cleanup_worker, args=(gui_callback,), daemon=True).start()

# a way to keep track of send times for RTT calculation
def receiver_client(face, entry, gui_callback=None):
    sock = entry["sock"]
    while True:
        try:
            raw_packet, addr = NN.receive_packet(sock)
            parsed, err = NN.parse_packet(raw_packet)

            if err:
                msg = f"[ERROR] {err}"
                print(msg)
                if gui_callback:
                    gui_callback("ERROR", msg)
                continue

            msg = f"Packet received on {face} from {addr}"
            print(f"\n{msg}")
            if gui_callback:
                gui_callback("INFO", msg)

            if parsed["type"] == "data":
                recv_time = time.time()
                msg = f"Got fragment from {addr} at {time.strftime('%H:%M:%S', time.localtime(recv_time))}"
                print(msg)
                if gui_callback:
                    gui_callback("INFO", msg)

                send_time = NN.get_PIT_entry(parsed.get("name"))["time"]
                complete = NN.process_data(parsed, raw_packet, sock)

                frag_total = parsed.get("frag_total", 0)
                
                if complete and frag_total != 0 and parsed.get("name") not in NN.FRAG_BUFFER:
                    rtt = recv_time - send_time
                    msg = f"Interest satisfied, RTT: {rtt:.4f}s"
                    print(msg)
                    if gui_callback:
                        gui_callback("SUCCESS", msg)
                    # return
                    continue
        except Exception as e:
            msg = f"[Receiver {face}] Error: {e}"
            print(msg)
            if gui_callback:
                gui_callback("ERROR", msg)


def pit_cleanup_worker(gui_callback=None):
    """Background thread to periodically clean up expired PIT entries."""
    CLEANUP_INTERVAL = 5  # seconds
    
    while True:
        time.sleep(CLEANUP_INTERVAL)
        
        try:
            expired_count = NN.cleanup_expired_pit_entries()
            
            if expired_count > 0:
                msg = f"[PIT Cleanup] Removed {expired_count} expired Interest(s)"
                print(msg)
                if gui_callback:
                    gui_callback("INFO", msg)
            
            # Optional: Print PIT stats
            # stats = NN.get_pit_stats()
            # if stats["total"] > 0:
            #     msg = f"[PIT Stats] Total: {stats['total']}, Active: {stats['active']}, Expired: {stats['expired']}"
            #     print(msg)
            #     if gui_callback:
            #         gui_callback("INFO", msg)
                    
        except Exception as e:
            msg = f"[PIT Cleanup] Error: {e}"
            print(msg)
            if gui_callback:
                gui_callback("ERROR", msg)


# =============================================================================
# GUI INTEGRATION
# =============================================================================

if GUI_AVAILABLE:
    # GUI Color Scheme
    SUCCESS = "#34d399"
    INFO = "#60a5fa"
    WARN = "#fbbf24"
    ERROR = "#f87171"
    ACCENT = "#22d3ee"
    ACCENT2 = "#60a5fa"
    ACCENT3 = "#a78bfa"

    class QtStream(QObject):
        text = pyqtSignal(str, str)
        
        def write(self, msg):
            if msg.strip():
                self.text.emit("INFO", msg.rstrip("\n"))
        
        def flush(self):
            pass

    class NodeMonitor(QWidget):
        def __init__(self, start_mode: str, node_name: str, interest_name: str = None):
            super().__init__()
            self.start_mode = start_mode
            self.node_name = node_name
            self.interest_name = interest_name
            
            self.setWindowTitle(f"NDN Node Monitor - {node_name}")
            self.resize(1100, 720)
            
            # Try to load stylesheet, fallback to basic styling
            try:
                with open('Modules/styles.qss', 'r') as f:
                    self.setStyleSheet(f.read())
            except FileNotFoundError:
                self.setStyleSheet(self._get_default_style())
            
            self._setup_ui()
            self._start_backend()
            
            # Refresh timer
            self.timer = QTimer(self)
            self.timer.timeout.connect(self.refresh_stats)
            self.timer.start(800)

        def _get_default_style(self):
            return """
                QWidget { background-color: #0f172a; color: #c7d2fe; }
                QTextEdit { background-color: #1e293b; border: 1px solid #334155; border-radius: 6px; padding: 8px; }
                QLineEdit { background-color: #1e293b; border: 1px solid #334155; border-radius: 6px; padding: 8px; }
                QPushButton { background-color: #3b82f6; border: none; border-radius: 6px; padding: 8px 16px; font-weight: 600; }
                QPushButton:hover { background-color: #2563eb; }
                QTableWidget { background-color: #1e293b; border: 1px solid #334155; }
                QHeaderView::section { background-color: #334155; color: #c7d2fe; padding: 8px; border: none; }
            """

        def _setup_ui(self):
            root = QVBoxLayout(self)
            root.setContentsMargins(14, 14, 14, 14)
            root.setSpacing(10)
            
            split = QHBoxLayout()
            split.setSpacing(10)
            root.addLayout(split)
            
            # Left Panel - Logs
            self.left = QFrame()
            self.left.setFrameShape(QFrame.StyledPanel)
            leftlay = QVBoxLayout(self.left)
            leftlay.setContentsMargins(12, 12, 12, 12)
            leftlay.setSpacing(8)
            
            title_logs = QLabel("DEBUG LOGS")
            title_logs.setStyleSheet(f"color:{SUCCESS}; font-weight:700; font-size:12pt;")
            
            self.ns_label = QLabel(f"{self.node_name}")
            self.ns_label.setStyleSheet("background:#0b1020; border:1px solid #1f2a44; border-radius:6px; padding:4px 8px; color:#9ca3af;")
            
            tt = QHBoxLayout()
            tt.addWidget(title_logs)
            tt.addStretch(1)
            tt.addWidget(self.ns_label)
            leftlay.addLayout(tt)
            
            self.logs = QTextEdit()
            self.logs.setReadOnly(True)
            try:
                self.logs.setFont(QFont("JetBrains Mono", 10))
            except:
                self.logs.setFont(QFont("Monospace", 10))
            leftlay.addWidget(self.logs, 1)
            
            split.addWidget(self.left, 1)
            
            # Right Panel - Data Structures
            self.right = QFrame()
            self.right.setFrameShape(QFrame.StyledPanel)
            rightlay = QVBoxLayout(self.right)
            rightlay.setContentsMargins(12, 12, 12, 12)
            rightlay.setSpacing(8)
            
            title_ds = QLabel("DATA STRUCTURES")
            title_ds.setStyleSheet(f"color:{ACCENT2}; font-weight:700; font-size:12pt;")
            rightlay.addWidget(title_ds)
            
            # Counters
            counters = QHBoxLayout()
            counters.setSpacing(10)
            self.pit_box = self._make_counter("PIT", ACCENT)
            self.fib_box = self._make_counter("FIB", ACCENT2)
            self.cs_box = self._make_counter("CS", ACCENT3)

            for w in (self.pit_box, self.fib_box, self.cs_box):
                counters.addWidget(w)
            rightlay.addLayout(counters)
            
            # Content Store Table
            self.table = QTableWidget(0, 3)
            self.table.setHorizontalHeaderLabels(["NAME", "SIZE", "CACHED TIME"])
            self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
            self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
            self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
            rightlay.addWidget(self.table, 1)
            
            split.addWidget(self.right, 1)
            
            # Bottom Command Bar
            bottom = QHBoxLayout()
            bottom.setSpacing(8)
            
            for label in ["show pit", "show fib", "clear logs", "stats"]:
                b = QPushButton(label)
                b.clicked.connect(lambda checked=False, t=label: self.quick_command(t))
                bottom.addWidget(b)
            
            bottom.addStretch(1)
            
            self.cmd = QLineEdit()
            self.cmd.setPlaceholderText("Enter command (e.g., send interest /dlsu/ccs/img21)")
            self.cmd.returnPressed.connect(self.handle_command)
            bottom.addWidget(self.cmd, 3)
            
            self.exec_btn = QPushButton("EXECUTE")
            self.exec_btn.clicked.connect(self.handle_command)
            bottom.addWidget(self.exec_btn)
            
            root.addLayout(bottom)

        def _make_counter(self, label: str, color: str):
            box = QFrame()
            box.setFrameShape(QFrame.StyledPanel)
            lay = QVBoxLayout(box)
            lay.setContentsMargins(10, 10, 10, 10)
            
            t = QLabel(label)
            t.setStyleSheet(f"color:{color}; font-size:11pt; font-weight:700;")
            
            v = QLabel("0")
            v.setStyleSheet("font-size:20pt; font-weight:800;")
            v.setObjectName(f"val_{label.lower()}")
            
            lay.addWidget(t)
            lay.addWidget(v)
            lay.addStretch(1)
            return box

        def _set_counter(self, name: str, value: int):
            lab = self.findChild(QLabel, f"val_{name}")
            if lab:
                lab.setText(str(value))

        def append_log(self, level: str, line: str):
            color = {"SUCCESS": SUCCESS, "INFO": INFO, "WARN": WARN, "ERROR": ERROR}.get(level, INFO)
            ts = datetime.now().strftime("%I:%M:%S %p")
            html = f'<span style="color:{INFO}">[{ts}]</span> <span style="color:{color}">[{level}]</span> {line}'
            self.logs.append(html)
            self.logs.moveCursor(QTextCursor.End)

        def _start_backend(self):
            """Start the node/client backend in a separate thread"""
            def backend_wrapper():
                try:
                    if self.start_mode == "node":
                        run_node(self.node_name, gui_callback=self.append_log)
                    elif self.start_mode == "client":
                        run_client(self.node_name, self.interest_name, gui_callback=self.append_log)
                except Exception as e:
                    self.append_log("ERROR", f"Backend error: {e}")
                    import traceback
                    traceback.print_exc()
            
            t = threading.Thread(target=backend_wrapper, daemon=True)
            t.start()


        def quick_command(self, txt: str):
            if txt == "send interest":
                self.cmd.setText("send interest /dlsu/goks/img21")
            else:
                self.cmd.setText(txt)
            self.handle_command()

        def handle_command(self):
            raw = self.cmd.text().strip()
            if not raw:
                return
            self.cmd.clear()
            
            try:
                if raw.lower() == "clear logs":
                    self.logs.clear()
                    self.append_log("SUCCESS", "Logs cleared")
                    return
                
                if raw.lower() in ("stats", "show stats"):
                    self.refresh_stats(force_log=True)
                    return
                
                if raw.lower().startswith("show "):
                    what = raw.split(" ", 1)[1].strip().lower()
                    self.show_structure(what)
                    return
                
                if raw.lower().startswith("send interest"):
                    parts = raw.split(" ")
                    if len(parts) < 3:
                        self.append_log("WARN", "Usage: send interest /path/name")
                        return
                    name = parts[2].strip()
                    
                    interest_packet = NN.build_interest_packet(name)
                    print(f"[DEBUG] Raw Interest Packet: {interest_packet}")
                    print(f"[DEBUG] Packet Size: {len(interest_packet)} bytes")
                                
                    face, dest_port = NN.lookup_fib(name)
                    NN.INTERFACES["face0"]["sock"].sendto(interest_packet, (NN.IP_ADDR, dest_port))

                    NN.store_interest(name, None, (NN.IP_ADDR, NN.INTERFACES["face0"]["port"]))
                    msg = f"Sending Interest for '{name}' at {time.strftime('%H:%M:%S', time.localtime(NN.get_PIT_entry(name)['time']))}"
                    print(msg)
                    self.append_log("INFO", msg)

                    return
                
                self.append_log("WARN", f"Unknown command: {raw}")
            except Exception as e:
                self.append_log("ERROR", f"{e}")

        def _safe_len(self, obj):
            try:
                return len(obj)
            except Exception:
                return 0

        def refresh_stats(self, force_log: bool = False):
            pit = getattr(NN, "PIT", {})
            fib = getattr(NN, "FIB", {})
            cs = getattr(NN, "CS", {})

            self._set_counter("pit", self._safe_len(pit))
            self._set_counter("fib", self._safe_len(fib))
            self._set_counter("cs", self._safe_len(cs))
            
            # Update CS table
            try:
                entries = []
                if isinstance(cs, dict):
                    for name, meta in cs.items():
                        size = meta.get("size", "")
                        ctime = meta.get("cached_time", "")
                        if ctime:
                            ctime = datetime.fromtimestamp(ctime).strftime("%Y-%m-%d %H:%M:%S")
                        entries.append((name, size, ctime))
                elif isinstance(cs, list):
                    for item in cs:
                        name = item.get("name", "")
                        size = item.get("size", "")
                        ctime = item.get("cached_time", "")
                        if ctime:
                            ctime = datetime.fromtimestamp(ctime).strftime("%Y-%m-%d %H:%M:%S")
                        entries.append((name, size, ctime))
                
                self.table.setRowCount(len(entries))
                for r, (name, size, ctime) in enumerate(entries):
                    self.table.setItem(r, 0, QTableWidgetItem(str(name)))
                    self.table.setItem(r, 1, QTableWidgetItem(str(size)))
                    self.table.setItem(r, 2, QTableWidgetItem(str(ctime)))
            except Exception:
                pass
            
            if force_log:
                self.append_log("INFO", f"Stats — PIT: {self._safe_len(pit)}, FIB: {self._safe_len(fib)}, CS: {self._safe_len(cs)}")

        def show_structure(self, which: str):
            obj = None
            if which == "pit":
                obj = getattr(NN, "PIT", {})
            elif which == "fib":
                obj = getattr(NN, "FIB", {})
            elif which == "cs":
                obj = getattr(NN, "CS", {})
            elif which in ("face", "faces"):
                obj = getattr(NN, "FACES", {})
            else:
                self.append_log("WARN", f"Unknown structure: {which}")
                return
            
            self.append_log("SUCCESS", f"=== {which.upper()} ===")
            try:
                self.append_log("INFO", repr(obj))
            except Exception:
                self.append_log("INFO", str(obj))


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

def main():
    ap = argparse.ArgumentParser(description="NDN Node Runner with optional GUI")
    ap.add_argument("--node", help="Run a node with this node_name (per node_config.json)")
    ap.add_argument("--client", nargs="+", metavar=("NODE_NAME", "INTEREST"), 
                    help="Send Interest from NODE_NAME for INTEREST")
    ap.add_argument("--gui", action="store_true", help="Launch with GUI monitor")
    args = ap.parse_args()

    if (args.node is None) == (args.client is None):
        print("Choose exactly one mode: --node <node_name>  OR  --client <node_name> <interest_name>")
        return

    # Determine mode
    if args.node:
        start_mode = "node"
        node_name = args.node
        interest = None
    elif args.client:
        start_mode = "client"
        if len(args.client) > 2:
            ap.error("--client takes at most 2 arguments: NODE_NAME [INTEREST]")
        node_name = args.client[0]
        interest  = args.client[1] if len(args.client) == 2 else None

    # Launch with or without GUI
    if args.gui:
        if not GUI_AVAILABLE:
            print("ERROR: PyQt5 is not installed. Install it with: pip install PyQt5")
            print("Running in CLI mode instead...")
            args.gui = False
        else:
            app = QApplication(sys.argv)
            win = NodeMonitor(start_mode, node_name, interest)
            win.show()
            sys.exit(app.exec_())
    
    # CLI mode
    if start_mode == "node":
        run_node(node_name)
    else:
        run_client(node_name, interest)


if __name__ == "__main__":
    main()