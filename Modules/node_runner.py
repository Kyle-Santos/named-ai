# node_runner.py
import os, sys, socket, json, time, threading, queue, argparse

from torch import addr
import NamedAI as NN
import functions

SEND_QUEUE = queue.Queue()
PROCESSOR_QUEUE = queue.Queue()
PACKET_QUEUE = queue.Queue()

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
        QPushButton, QTableWidget, QTableWidgetItem, QHeaderView, QFrame, QSizePolicy
    )
    GUI_AVAILABLE = True
except ImportError:
    pass


def load_node_config(config_path: str, node_name: str):
    """Load node configuration by node_name."""
    with open(config_path, "r") as f:
        config = json.load(f)
    node_config = next(n for n in config["nodes"] if n["name"] == node_name)
    cam = next(n for n in config["nodes"] if n["name"] == "/dlsu/goks/cam")

    # NN.set_ip_addr(config.get("ip", "127.0.0.1"))
    
    NN.NODE_NAME = node_config["name"]
    NN.FIB = node_config.get("FIB", {})
    NN.FACES = [iface["face"] for iface in node_config.get("interfaces", [])]

    # Apply per-node CS storage cap (MB) before initializing content store
    max_storage_mb = node_config.get("max_storage_mb", 10)
    NN.set_cs_max_storage(max_storage_mb)
    NN.XBEE_PORT = node_config.get("xbee_port", None)

    # Initialize content store
    NN.initialize_content_store(node_config.get("storage", ""))

    NN.NODE_FUNCTIONS_MAPPING = node_config.get("node_functions_mapping", {})
    
    # functions_list = cam["node_functions_mapping"].get(NN.NODE_NAME, []) 
    functions_list = []
    print(f"Functions for {NN.NODE_NAME}: {functions_list}")
    for func_name in functions_list:
        if func_name == "detect":
            functions.load_mtcnn()

        if func_name == "recognize":
            functions.load_facebank()

        # if func_name == "insightface_embedding":
        #     functions.load_insightface()
        #     print("InsightFace model loaded.")

        # if func_name == "facenet_embedding":
        #     functions.load_facenet()
        #     print("Facenet model loaded.")

        # if func_name == "mfn_embedding":
        #     functions.load_mfn()
        #     print("MobileFaceNet model loaded.")
            
        NN.FUNCTIONS_TABLE[func_name] = functions.get_function(func_name)

    # print(NN.FUNCTIONS_TABLE)

    return node_config


def create_interfaces(node_config):
    return NN.create_interface(node_config["interfaces"])


GUI_CALLBACK = None
def log(level, message, path=""):
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    level_upper = level.upper()
    if level_upper not in ["INFO", "WARN", "ERROR", "SUCCESS", "DEBUG"]:
        level_upper = "INFO"  # default to INFO if invalid level

    # if GUI_CALLBACK:
    if GUI_CALLBACK and level_upper not in ["INFO", "SUCCESS"]:
        GUI_CALLBACK(level_upper, message)
    # GUI_QUEUE.put((level, message))   # put into thread-safe queue

    print(f"\n[{timestamp}] [{level_upper}] {message}" + (f" {path}" if path else ""))


def processor_thread():
    """
    Reads complete packets from circular buffer and processes them.
    Each packet is delimited by preamble and postamble.
    """
    
    while True:
        try:
            packet, sock, face, entry = PACKET_QUEUE.get()
            
            # print(packet)

            start_time = time.time()
            # Parse the packet
            parsed, err = NN.parse_packet(packet)
            end_time = time.time()
            NN.update_metrics("parsing_time", end_time - start_time)
            
            # print("Parsed content: ", parsed)
            if err:
                msg = f"Parse error: {err}"
                print(msg)
                # log("ERROR", msg)
                if err == "Checksum mismatch":
                    log("DEBUG", f"Parsed packet: {packet}")
                continue
            
            # You'll need to track face/sock/addr information
            # This might require a separate metadata structure or per-face buffers
            msg = f"Processing {parsed['type']} packet \"{parsed['name']}\""
            # print(f"\n{msg}")
            # log("INFO", msg)

            face = next(
                (iface for iface in NN.INTERFACES.values()
                if iface["port"] == parsed["dst"]),
                None
            )
            # log("DEBUG", f"Identified incoming face: {face['face'] if face else 'Unknown'} for packet destined to port {parsed['dst']}")
            try:
                # Process based on packet type
                if parsed["type"] == "interest":
                    start_time = time.time()
                    NN.process_interest(parsed, addr=None, sock=sock, 
                                      SEND_QUEUE=SEND_QUEUE, interface=face['face'])
                    end_time = time.time()
                    NN.update_metrics("processing_time", end_time - start_time)
                    if NN.NODE_NAME.startswith("/dlsu/goks/cam"):
                        log("DEBUG", f"FINAL Parsing Time: {NN.METRICS['parsing_time'] * 1000:.4f} ms")
                        log("DEBUG", f"Finished processing Interest '{parsed['name']}' in {NN.METRICS['processing_time'] * 1000:.4f} ms")

                elif parsed["type"] == "data":
                    start_time = time.time()
                    log("DEBUG", f"Processing fragment {parsed['frag_num']}/{parsed['frag_total']}")
                    NN.process_data(parsed, packet, sock=sock, 
                                  SEND_QUEUE=SEND_QUEUE)
                    end_time = time.time()
                    NN.update_metrics("processing_time", end_time - start_time)
                    if (not NN.FRAG_BUFFER.get(parsed["name"])) or parsed["frag_num"] is None:
                        log("DEBUG", f"FINAL Parsing Time: {NN.METRICS['parsing_time'] * 1000:.4f} ms")
                        log("DEBUG", f"Finished processing Data '{parsed['name']}' in {NN.METRICS['processing_time'] * 1000:.4f} ms")

                        NN.append_metrics_to_csv({
                            "name": parsed["name"],
                            "RTT": NN.METRICS["ave_RTT"],  # in ms
                            "interest_sent_time": NN.METRICS["interest_sent_time"], # make this float
                            "interest_receive_time": NN.METRICS["interest_receive_time"],
                            "data_sent_time": NN.METRICS["data_sent_time"],
                            "data_receive_time": NN.METRICS["data_receive_time"],
                            "parsing_time": NN.METRICS["parsing_time"],
                            "processing_time": NN.METRICS["processing_time"],
                            "send_time": NN.METRICS["send_time"]
                        })

            except Exception as e:
                msg = f"[Processor] Error processing packet: {e}"
                print(msg)
                log("ERROR", msg)
                
        except Exception as e:
            msg = f"[Processor] Critical error: {e}"
            print(msg)
            log("ERROR", msg)
            import traceback
            traceback.print_exc()
            time.sleep(0.1)


def receiver(face, entry):
    sock = entry["sock"]
    buf = [b""]  # mutable container so receive_packet can update it

    while True:
        try:
            packet = NN.receive_packet(sock, buf)
            if packet:
                PACKET_QUEUE.put((packet, sock, face, entry))
            # else:
            #     time.sleep(0.001)  # avoid busy waiting if no complete packet

        except Exception as e:
            log("ERROR", f"[Receiver {face}] {e}")
            # time.sleep(0.01)


def sender():
    while True:
        task = SEND_QUEUE.get()

        try:
            sock, addr, response = task
            start_time = time.time()
            for resp in response:
                NN.send_packet(sock, addr, resp)
                # sleep = len(resp) * 10 / 115200 * 1.2
                time.sleep(0.02)  # slight delay to avoid UDP packet loss
            end_time = time.time()
            NN.update_metrics("send_time", end_time - start_time)
            # log("DEBUG", f"Sent response to {addr} in {NN.METRICS['send_time'] * 1000:.4f} ms")

            if NN.NODE_NAME.startswith("/dlsu/goks/cam"):
                NN.append_metrics_to_csv({
                    "name": NN.NODE_NAME,  # or use a specific name if available
                    "RTT": NN.METRICS["ave_RTT"],  # in ms
                    "interest_sent_time": NN.METRICS["interest_sent_time"], # make this float
                    "interest_receive_time": NN.METRICS["interest_receive_time"],
                    "data_sent_time": NN.METRICS["data_sent_time"],
                    "data_receive_time": NN.METRICS["data_receive_time"],
                    "parsing_time": NN.METRICS["parsing_time"],
                    "processing_time": NN.METRICS["processing_time"],
                    "send_time": NN.METRICS["send_time"]
                })
        except Exception as e:
            msg = f"[Sender] Error: {e}"
            print(msg)
            log("ERROR", msg)


def run_node(node_name: str, config_path=CONFIG_PATH, gui_callback=None):
    """Main node runner with separated receiver and processor threads."""
    NN.GUI_CALLBACK = gui_callback
    
    global GUI_CALLBACK
    GUI_CALLBACK = gui_callback

    time.sleep(1.0)
    node_config = load_node_config(config_path, node_name)
    interfaces = create_interfaces(node_config)
    
    msg = f"{NN.NODE_NAME} running with faces: {list(interfaces.keys())}"
    print(f"\033[92m{msg}\033[0m")
    log("SUCCESS", msg)

    threads = []

    # Start receiver threads
    # for face, entry in interfaces.items():
    face = list(interfaces.keys())[0]
    t = threading.Thread(target=receiver, args=(face, interfaces[face]), daemon=False, name=f"Receiver-{face}")
    t.start()
    threads.append(t)

    # Start global processor thread - PROCESS ALL PACKETS
    t = threading.Thread(
        target=processor_thread,
        args=(),
        daemon=False,
        name="Processor"
    )
    t.start()
    threads.append(t)

    # Start sender thread
    threading.Thread(target=sender, args=(), daemon=False, name="Sender").start()

    # Start PIT cleanup thread
    threading.Thread(target=pit_cleanup_worker, args=(), daemon=False, name="PIT_Cleanup").start()

    threading.Thread(
      target=NN.frag_watchdog, args=(SEND_QUEUE,),
      daemon=False, name="FragWatchdog"
    ).start()

    # Monitor threads
    def thread_monitor():
        while True:
            time.sleep(5)
            for t in threads:
                if not t.is_alive():
                    msg = f"[CRITICAL] Thread {t.name} has died!"
                    print(msg)
                    log("ERROR", msg)

    monitor_thread = threading.Thread(target=thread_monitor, daemon=True, name="Monitor")
    monitor_thread.start()

    # Keep alive
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down node...")

        try:
            NN.clear_content_store()
        except Exception as e:
            print(f"Error clearing content store: {e}")


def pit_cleanup_worker():
    """Background thread to periodically clean up expired PIT entries."""
    CLEANUP_INTERVAL = 5  # seconds
    
    while True:
        time.sleep(CLEANUP_INTERVAL)
        
        try:
            expired_count = NN.cleanup_expired_pit_entries()
            
            if expired_count > 0:
                msg = f"[PIT Cleanup] Removed {expired_count} expired Interest(s)"
                print(msg)
                log("INFO", msg)
            
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
            log("ERROR", msg)

# GUI INTEGRATION

if GUI_AVAILABLE:
    # GUI Color Scheme
    SUCCESS = "#34d399"
    INFO = "#60a5fa"
    WARN = "#fbbf24"
    ERROR = "#f87171"
    DEBUG = "#ffc800"
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

    class  NodeMonitor(QWidget):
        log_signal = pyqtSignal(str, str)  # level, line

        def __init__(self, start_mode: str, node_name: str, auto_send: bool):
            super().__init__()
            self.start_mode = start_mode
            self.node_name = node_name
            self.current_table = "pit"  # Default to PIT table
            self.auto_send_packets_gui = auto_send

            # Determine colors based on node type
            node_lower = self.node_name.lower()
            if "/cam" in node_lower:
                self.SUCCESS = "#00FFFF"  
                self.INFO = "#66FF99"     
                self.WARN = "#CCCCFF"     
                self.ERROR = "#f87171"
                self.DEBUG = "#FFC800"     
                self.ACCENT = "#00FFFF"   
                self.ACCENT2 = "#66FF99"  
                self.ACCENT3 = "#CCCCFF"  
                bg_color = "#000000"
            elif node_lower.startswith("/dlsu"):
                self.SUCCESS = "#34d399"  
                self.INFO = "#00BFFF"     
                self.WARN = "#E0C3FC"     
                self.ERROR = "#f87171"
                self.DEBUG = "#FFC800"    
                self.ACCENT = "#00BFFF"   
                self.ACCENT2 = "#5CFFB5"  
                self.ACCENT3 = "#E0C3FC"  
                bg_color = "#001F3F"
            else:
                self.SUCCESS = "#34d399" 
                self.INFO = "#00BFFF" 
                self.WARN = "#fbbf24" 
                self.ERROR = "#f87171"
                self.DEBUG = "#FFC800" 
                self.ACCENT = "#22d3ee" 
                self.ACCENT2 = "#60a5fa" 
                self.ACCENT3 = "#a78bfa"

                bg_color = "#1c0f2a"

            self.TIME_COLOR = "#ffffff"

            self.setWindowTitle(f"Named Networking Node Monitor - {node_name}")

            # connect signal to slot
            self.log_signal.connect(self.append_log)

            self.setStyleSheet(self._get_default_style(bg_color))
            
            self._setup_ui()
            self._start_backend()
            
            # Set GUI to 1/4 of 1920x1080
            self.resize(1920 // 2, 1080 // 2)  # 960x540

            # Refresh timer
            self.timer = QTimer(self)
            self.timer.timeout.connect(self.refresh_stats)
            self.timer.start(800)

        def _get_default_style(self, bg_color):
            return f"""
                QWidget {{ background-color: {bg_color}; color: #c7d2fe; }}
                QTextEdit {{ background-color: #1e293b; border: 1px solid #334155; border-radius: 6px; padding: 8px; }}
                QLineEdit {{ background-color: #1e293b; border: 1px solid #334155; border-radius: 6px; padding: 8px; }}
                QPushButton {{ background-color: #3b82f6; border: none; border-radius: 6px; padding: 8px 16px; font-weight: 600; }}
                QPushButton:hover {{ background-color: #2563eb; }}
                QTableWidget {{ background-color: #1e293b; border: 1px solid #334155; }}
                QHeaderView::section {{ background-color: #334155; color: #c7d2fe; padding: 8px; border: none; }}
            """

        def _setup_ui(self):
            root = QVBoxLayout(self)
            root.setContentsMargins(14, 14, 14, 14)
            root.setSpacing(10)
            
            split = QHBoxLayout()
            split.setSpacing(10)
            root.addLayout(split)
            
            # -----------------------------
            # Left Panel – Logs
            # -----------------------------
            self.left = QFrame()
            self.left.setFrameShape(QFrame.StyledPanel)
            leftlay = QVBoxLayout(self.left)
            leftlay.setContentsMargins(12, 12, 12, 12)
            leftlay.setSpacing(8)
            
            title_logs = QLabel("DEBUG LOGS")
            title_logs.setStyleSheet(f"color:{self.SUCCESS}; font-weight:700; font-size:12pt;")
            
            self.ns_label = QLabel(f"{self.node_name}")
            self.ns_label.setStyleSheet(
                "background:#0b1020; border:1px solid #1f2a44; "
                "border-radius:6px; padding:4px 8px; color:#9ca3af;"
            )
            
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
            
            # -----------------------------
            # Right Panel – Stats & Table
            # -----------------------------
            self.right = QFrame()
            self.right.setFrameShape(QFrame.StyledPanel)
            rightlay = QVBoxLayout(self.right)
            rightlay.setContentsMargins(12, 12, 12, 12)
            rightlay.setSpacing(8)

            # =============================
            # TOP ROW: DATA STRUCTURES | STATS
            # =============================
            stats_row = QHBoxLayout()
            stats_row.setSpacing(12)

            # ----- Data Structures group -----
            ds_frame = QFrame()
            ds_layout = QVBoxLayout(ds_frame)
            ds_layout.setContentsMargins(10, 10, 10, 10)
            ds_layout.setSpacing(8)

            title_ds = QLabel("DATA STRUCTURES")
            title_ds.setStyleSheet(f"color:{self.ACCENT2}; font-weight:700; font-size:12pt;")
            ds_layout.addWidget(title_ds)

            ds_counters = QVBoxLayout()
            ds_counters.setSpacing(5)

            # Data Structures: PIT, CS
            self.pit_box = self._make_counter("pit", "PIT", self.ACCENT)
            self.cs_box = self._make_counter("cs", "CS", self.ACCENT3)

            ds_counters.addWidget(self.pit_box)
            ds_counters.addWidget(self.cs_box)


            ds_layout.addLayout(ds_counters)
            stats_row.addWidget(ds_frame, 1)

            # ----- Metrics group -----
            metrics_frame = QFrame()
            m_layout = QVBoxLayout(metrics_frame)
            m_layout.setContentsMargins(10, 10, 10, 10)
            m_layout.setSpacing(8)

            metrics_title = QLabel("STATS")
            metrics_title.setStyleSheet(f"color:{self.WARN}; font-weight:700; font-size:12pt;")
            m_layout.addWidget(metrics_title)

            # Create horizontal layout for two vertical columns
            metrics_hbox = QHBoxLayout()
            metrics_hbox.setSpacing(10)

            # Left vertical column
            left_vbox = QVBoxLayout()
            left_vbox.setSpacing(8)

            self.interests_sent_box = self._make_counter(
                "interests_sent", "Interests Sent", self.SUCCESS
            )
            self.data_packets_sent_box = self._make_counter(
                "data_total_sent", "Data Sent", self.ACCENT
            )
            self.failed_packets_box = self._make_counter(
                "failed_packets", "Failed Packets", self.ERROR
            )

            left_vbox.addWidget(self.interests_sent_box)
            left_vbox.addWidget(self.data_packets_sent_box)
            left_vbox.addWidget(self.failed_packets_box)

            # Right vertical column
            right_vbox = QVBoxLayout()
            right_vbox.setSpacing(8)

            self.interests_received_box = self._make_counter(
                "interests_received", "Interests Received", self.SUCCESS
            )
            self.data_packets_received_box = self._make_counter(
                "data_total_received", "Data Received", self.ACCENT
            )
            self.total_data_bytes_received_box = self._make_counter(
                "total_data_bytes_received", "Total KBs Received", self.ACCENT3
            )

            right_vbox.addWidget(self.interests_received_box)
            right_vbox.addWidget(self.data_packets_received_box)
            right_vbox.addWidget(self.total_data_bytes_received_box)

            metrics_hbox.addLayout(left_vbox)
            metrics_hbox.addLayout(right_vbox)

            m_layout.addLayout(metrics_hbox)

            stats_row.addWidget(metrics_frame, 1)

            # Add the whole top row to the right panel
            rightlay.addLayout(stats_row)

            # =============================
            # TABLE (PIT / CS / FIB)
            # =============================
            self.table = QTableWidget(0, 3)
            self.set_table_headers("pit")
            self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
            self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
            self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
            rightlay.addWidget(self.table, 1)

            rightlay.setStretch(0, 1)   # stats_row
            rightlay.setStretch(1, 3)   # table (increased to give more space)
            
            split.addWidget(self.right, 1)
            
            # -----------------------------
            # Bottom Command Bar
            # -----------------------------
            bottom = QHBoxLayout()
            bottom.setSpacing(8)

            for label in ["show pit", "show cs", "show fib", "show metrics", "clear logs"]:
                b = QPushButton(label)
                b.clicked.connect(lambda checked=False, t=label: self.quick_command(t))
                bottom.addWidget(b)

            bottom.addStretch(1)
            
            self.cmd = QLineEdit()
            self.cmd.setPlaceholderText("Enter command (e.g., send interest /dlsu/ccs/img21)")
            self.cmd.returnPressed.connect(self.handle_command)
            # if self.start_mode == "client":
            #     bottom.addWidget(self.cmd, 3)
            bottom.addWidget(self.cmd, 3)
            
            self.exec_btn = QPushButton("SEND")
            self.exec_btn.clicked.connect(self.handle_command)
            if self.start_mode == "client":
                bottom.addWidget(self.exec_btn)
            
            root.addLayout(bottom)

        def _make_counter(self, metric_name: str, display_label: str, color: str):
            box = QFrame()
            box.setFrameShape(QFrame.StyledPanel)

            lay = QVBoxLayout(box)
            lay.setContentsMargins(3, 5, 3, 5)

            t = QLabel(display_label)
            t.setStyleSheet(f"color:{color}; font-size:9pt; font-weight:700;")

            v = QLabel("0")
            v.setStyleSheet("font-size:14pt; font-weight:800;")
            v.setObjectName(f"val_{metric_name}")

            lay.addWidget(t)
            lay.addWidget(v)
            lay.addStretch(1)
            return box


        def _set_counter(self, name: str, value: int):
            lab = self.findChild(QLabel, f"val_{name}")
            if lab:
                lab.setText(str(value))

        def set_table_headers(self, mode: str):
            if mode == "pit":
                self.table.setColumnCount(3)
                headers = ["NAME", "FACE", "TIME"]
            elif mode == "cs":
                self.table.setColumnCount(3)
                headers = ["NAME", "HIT COUNT", "ACCESS TIME"]
            elif mode == "fib":
                self.table.setColumnCount(3)
                headers = ["PREFIX", "FACE", "PORT"]
            elif mode == "metrics":
                self.table.setColumnCount(2)
                headers = ["METRIC", "VALUE"]
            else:
                self.table.setColumnCount(3)
                headers = ["NAME", "VALUE1", "VALUE2"]
            self.table.setHorizontalHeaderLabels(headers)

        def append_log(self, level: str, line: str):
            color = {"SUCCESS": self.SUCCESS, "INFO": self.INFO, "WARN": self.WARN, "ERROR": self.ERROR, "DEBUG": self.DEBUG}.get(level, self.INFO)
            ts = datetime.now().strftime("%I:%M:%S %p")
            html = f'<span style="color:{self.TIME_COLOR}">[{ts}]</span> <span style="color:{color}">[{level}]</span> {line}'
            self.logs.append(html)
            self.logs.moveCursor(QTextCursor.End)

        def _start_backend(self):
            """Start the node/client backend in a separate thread"""
            def backend_wrapper():
                try:
                    run_node(self.node_name, gui_callback=self.log_signal.emit)
                except Exception as e:
                    self.append_log("ERROR", f"Backend error: {e}")
                    import traceback
                    traceback.print_exc()
            
            t = threading.Thread(target=backend_wrapper, daemon=False)
            t.start()

            # simulate receiving a packet after startup for demonstration
            # time.sleep(5)
            # # parsed_packet = {'type': 'interest', 'name': '/dlsu/goks/cam/txt6.txt', 'valid': True}
            # parsed_packet = {'type': 'interest', 'name': '/txt6.txt', 'valid': True}
            # parsed_packet = {'type': 'interest', 'name': '/cap17.jpg', 'valid': True}
            # NN.process_interest(parsed_packet, addr=None, sock=NN.INTERFACES["face0"]["sock"], SEND_QUEUE=SEND_QUEUE, interface=None)

            # Auto-send packets via GUI command handler if specified
            if hasattr(self, 'auto_send_packets_gui') and self.auto_send_packets_gui:
                self.auto_send_interests()

        def auto_send_interests(self):
            """Automatically send interest packets using the GUI command handler"""
                
            # NN.METRICS["test_start_time"] = time.time()
            TEST_DURATION = 30   # seconds — change this to whatever you need
            SEND_INTERVAL = 0.5

            packets = [f"/dlsu/goks/cam/capture{n}.jpg" for n in range(1, 201)]

            def send_loop():
                # ── wait for backend init ──────────────────────────────────────
                time.sleep(3)

                self.append_log("INFO",
                    f"Timed test starting: {TEST_DURATION}s, "
                    f"cycling {len(packets)} name(s), interval={SEND_INTERVAL}s")
                print(f"\033[96m[AutoSend] Timed test: {TEST_DURATION}s\033[0m")

                # ── reset metrics and start the clock ─────────────────────────
                for key in ("interests_sent", "data_total_received", "data_total_sent",
                            "failed_packets", "total_data_bytes_received",
                            "total_data_overhead_bytes_received", "ave_RTT",
                            "throughput", "goodput", "PDR",
                            "data_packets_to_receive"):
                    NN.METRICS[key] = 0 if isinstance(NN.METRICS[key], int) else 0.0
                NN.METRICS["data_packets_to_receive_buffer"] = {}

                start_time = time.time()
                NN.METRICS["test_start_time"] = start_time
                deadline   = start_time + TEST_DURATION
                idx        = 0

                print(f"\033[96m[AutoSend] Starting timed test loop...\033[0m")
                # ── send loop ─────────────────────────────────────────────────
                while time.time() < deadline:
                    name = packets[idx % len(packets)]
                    idx += 1

                    try:
                        interest_packet = NN.build_interest_packet(name)
                        _, dest_port = NN.lookup_fib(name)
                        SEND_QUEUE.put((
                            NN.INTERFACES["face0"]["sock"],
                            (NN.IP_ADDR, dest_port),
                            [interest_packet]
                        ))
                        NN.update_metrics("interests_sent")
                        NN.store_interest(name, None,
                                        (NN.IP_ADDR, NN.INTERFACES["face0"]["port"]))

                        elapsed   = time.time() - start_time
                        remaining = max(0.0, deadline - time.time())
                        # self.append_log("DEBUG",
                        #     f"[{elapsed:5.1f}s / {remaining:5.1f}s left] "
                        #     f"Sent Interest: {name}")
                        print(f"\033[96m[AutoSend] Sent Interest: {name}\033[0m")
                    except Exception as e:
                        self.append_log("ERROR", f"[AutoSend] {e}")
                        NN.update_metrics("failed_packets")

                    # sleep for SEND_INTERVAL but bail early if deadline passed
                    wake = time.time() + SEND_INTERVAL
                    while time.time() < wake and time.time() < deadline:
                        time.sleep(0.05)

                # ── test over — collect and log metrics ───────────────────────
                end_time   = time.time()
                elapsed    = end_time - start_time
                NN.METRICS["test_end_time"] = end_time

                m = NN.get_metrics()

                if elapsed > 0:
                    m["throughput"] = m["total_data_overhead_bytes_received"] / 1024 / elapsed
                    m["goodput"]    = m["total_data_bytes_received"] / 1024 / elapsed
                    NN.METRICS["throughput"] = m["throughput"]
                    NN.METRICS["goodput"]    = m["goodput"]

                separator = "─" * 55
                self.append_log("SUCCESS", separator)
                self.append_log("SUCCESS", f"  TIMED TEST COMPLETE  ({elapsed:.2f} s)")
                self.append_log("SUCCESS", separator)
                self.append_log("SUCCESS", f"  Interests Sent    : {m['interests_sent']}")
                self.append_log("SUCCESS", f"  Data Pkts Received: {m['data_total_received']}")
                self.append_log("SUCCESS", f"  Failed Packets    : {m['failed_packets']}")
                self.append_log("SUCCESS", f"  PDR               : {m['PDR']:.1f} %")
                self.append_log("SUCCESS", f"  Avg RTT           : {m['ave_RTT']:.2f} ms")
                self.append_log("SUCCESS", f"  Throughput        : {m['throughput']:.2f} KB/s")
                self.append_log("SUCCESS", f"  Goodput           : {m['goodput']:.2f} KB/s")
                self.append_log("SUCCESS", separator)

                # Mirror to stdout so it's visible in the terminal too
                print(f"\n\033[92m{'='*55}")
                print(f"  TIMED TEST COMPLETE  ({elapsed:.2f} s)")
                print(f"{'='*55}")
                print(f"  Interests Sent    : {m['interests_sent']}")
                print(f"  Data Pkts Received: {m['data_total_received']}")
                print(f"  Failed Packets    : {m['failed_packets']}")
                print(f"  PDR               : {m['PDR']:.1f} %")
                print(f"  Avg RTT           : {m['ave_RTT']:.2f} ms")
                print(f"  Throughput        : {m['throughput']:.2f} KB/s")
                print(f"  Goodput           : {m['goodput']:.2f} KB/s")
                print(f"{'='*55}\033[0m\n")

            threading.Thread(target=send_loop, daemon=True, name="AutoSend").start()

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
                    if what in ("pit", "cs", "fib"):
                        self.current_table = what
                        self.set_table_headers(what)
                        self.refresh_stats()
                        self.append_log("SUCCESS", f"Switched table to {what.upper()}")
                    elif what == "metrics":
                        self.current_table = "metrics"
                        self.set_table_headers("metrics")
                        self.refresh_stats()
                        self.append_log("SUCCESS", f"Switched table to METRICS")
                    else:
                        self.show_structure(what)
                    return
                
                if raw.lower().startswith("send interest"):
                    parts = raw.split(" ")
                    if len(parts) < 3:
                        self.append_log("WARN", "Usage: send interest /path/name")
                        return
                    name = parts[2].strip()
                    
                    _, dest_port = NN.lookup_fib(name)

                    interest_packet = NN.build_interest_packet(name, dest_port=dest_port)
                    print(f"[DEBUG] Raw Interest Packet: {interest_packet}")
                    print(f"[DEBUG] Packet Size: {len(interest_packet)} bytes")
                                
                    SEND_QUEUE.put((NN.INTERFACES["face0"]["sock"], ("", dest_port), [interest_packet]))
                    
                    # 10.0.0.106
                    # SEND_QUEUE.put((NN.INTERFACES["face0"]["sock"], ("10.0.0.106", dest_port), [interest_packet]))
                    
                    NN.update_metrics("interests_sent")

                    NN.store_interest(name, None, ("", NN.INTERFACES["face0"]["port"]))
                    msg = f"Sending Interest for '{name}' at {time.strftime('%H:%M:%S', time.localtime(NN.get_PIT_entry(name)['time']))}"
                    print(msg)
                    self.append_log("INFO", msg)

                    # append log sent timestamp
                    from datetime import datetime
                    sent_time = datetime.now()
                    NN.update_metrics("interest_sent_time", sent_time.timestamp())
                    self.append_log(
                        "DEBUG",
                        f"Interest '{name}' sent at {sent_time.strftime('%H:%M:%S.%f')}"  # HH:MM:SS.mmm
                    )

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
            faces = getattr(NN, "FACES", None)
            metrics = NN.get_metrics()

            self._set_counter("pit", self._safe_len(pit))
            self._set_counter("fib", self._safe_len(fib))
            self._set_counter("cs", self._safe_len(cs))

            if isinstance(faces, (list, dict)):
                self._set_counter("faces", self._safe_len(faces))
            else:
                unique_faces = set()
                try:
                    for v in fib.values():
                        if isinstance(v, (list, tuple)):
                            unique_faces.update(v)
                    self._set_counter("faces", len(unique_faces) or 0)
                except Exception:
                    self._set_counter("faces", 0)

            # Update METRICS counters
            for metric_name, value in metrics.items():
                if metric_name == "total_data_bytes_received":
                    value = round(value / 1024, 2)  # Convert to KB
                self._set_counter(metric_name, value)
                
            
            # Update table based on current mode
            try:
                entries = []
                if self.current_table == "cs":
                    if isinstance(cs, dict):
                        for name, meta in cs.items():
                            hit_count = meta.get("hit_count", 0)
                            ctime = meta.get("timestamp", "")
                            entries.append((name, hit_count, time.strftime('%H:%M:%S', time.localtime(ctime))))
                    elif isinstance(cs, list):
                        for item in cs:
                            name = item.get("name", "")
                            hit_count = item.get("hit_count", 0)
                            ctime = item.get("timestamp", "")
                            entries.append((name, hit_count, time.strftime('%H:%M:%S', time.localtime(ctime))))
                elif self.current_table == "pit":
                    if isinstance(pit, dict):
                        for name, entry in pit.items():
                            face = entry.get("interface", "")
                            time_val = entry.get("time", "")
                            entries.append((name, face, time.strftime('%H:%M:%S', time.localtime(time_val))))
                elif self.current_table == "fib":
                    if isinstance(fib, dict):
                        for prefix, value in fib.items():
                            entries.append((prefix, value["face"], value["port"]))
                elif self.current_table == "metrics":
                    names = {
                        "ave_RTT": "Average RTT (ms)",
                        "PDR": "Packet Delivery Ratio (%)",
                        "throughput": "Throughput (kbs/s)",
                        "goodput": "Goodput (kbs/s)",
                    }
                    for key in ["ave_RTT", "PDR", "throughput", "goodput"]:
                        display_name = names.get(key, key)
                        value = metrics.get(key, 0.0)
                        entries.append((display_name, f"{value:.2f}"))

                self.table.setRowCount(len(entries))

                if self.current_table in ("metrics",):
                    for r, (col1, col2) in enumerate(entries):
                        self.table.setItem(r, 0, QTableWidgetItem(str(col1)))
                        self.table.setItem(r, 1, QTableWidgetItem(str(col2)))
                else:
                    for r, (col1, col2, col3) in enumerate(entries):
                        self.table.setItem(r, 0, QTableWidgetItem(str(col1)))
                        self.table.setItem(r, 1, QTableWidgetItem(str(col2)))
                        self.table.setItem(r, 2, QTableWidgetItem(str(col3)))
            except Exception:
                pass
            
            if force_log:
                self.append_log("INFO", f"Stats — PIT: {self._safe_len(pit)}, FIB: {self._safe_len(fib)}, CS: {self._safe_len(cs)}")


        def show_structure(self, which: str):
            obj = None
            if which == "pit":
                obj = getattr(NN, "PIT", {})
            elif which == "fib":
                fib_raw = getattr(NN, "FIB", {})
                # Exclude port mappings: display only the face name
                obj = {}
                for prefix, face_dict in fib_raw.items():
                    if isinstance(face_dict, dict) and 'face' in face_dict:
                        obj[prefix] = face_dict['face']
                    else:
                        obj[prefix] = face_dict
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

        def show_metrics(self):
            metrics = getattr(NN, "METRICS", {})
            self.append_log("SUCCESS", "=== METRICS ===")
            # Display only the specified metrics
            for key in ["ave_RTT", "PDR", "latency", "throughput"]:
                value = metrics.get(key, 0.0)
                self.append_log("INFO", f"{key}: {value}")
        
        def closeEvent(self, event):
            """Ensure backend threads and the entire program exit when GUI window is closed."""
            try:
                self.append_log("INFO", "Shutting down...")

                # Stop refresh timer
                if hasattr(self, "timer"):
                    self.timer.stop()

                try:
                    NN.clear_content_store()
                except Exception as e:
                    print(f"Error clearing content store: {e}")
                
                # Hard exit (forces all threads to close)
                os._exit(0)

            except Exception as e:
                print("Error during shutdown:", e)
                os._exit(1)


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

def main():
    ap = argparse.ArgumentParser(description="NDN Node Runner with GUI")
    ap.add_argument("--node", help="Run a node with this node_name (per node_config.json)")
    ap.add_argument("--client", help="Run a client with this node_name (per node_config.json)")
    # ap.add_argument("--gui", action="store_true", help="Launch with GUI monitor")
    ap.add_argument("--auto-send", action="store_true", help="Automatically send default packets on startup")
    args = ap.parse_args()

    if (args.node is None) == (args.client is None):
        print("Choose exactly one mode: --node <node_name>  OR  --client <node_name>")
        return

    # Determine mode
    if args.node:
        start_mode = "node"
        node_name = args.node
    elif args.client:
        start_mode = "client"
        node_name = args.client

    auto_send = True if args.auto_send else False

    # Launch with or without GUI
    if not GUI_AVAILABLE:
        print("ERROR: PyQt5 is not installed. Install it with: pip install PyQt5")
        print("Running in CLI mode instead...")
        return
    else: 
        app = QApplication(sys.argv)
        win = NodeMonitor(start_mode, node_name, auto_send=auto_send)

        win.show()
        sys.exit(app.exec_())

if __name__ == "__main__":
    main()