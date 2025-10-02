import sys, time, threading, argparse, traceback
from datetime import datetime
from typing import Any, Dict, List

# Local modules
import node_runner
import NamedAI as NN

from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QObject
from PyQt5.QtGui import QFont, QTextCursor
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, QLabel, QLineEdit,
    QPushButton, QTableWidget, QTableWidgetItem, QHeaderView, QFrame, QSizePolicy
)

# --------------------
# Styles (matches ref)
# --------------------
DARK_BG = "#0f172a"        # slate/navy
PANEL_BG = "#0d1321"
PANEL_BG2 = "#111827"
ACCENT = "#22d3ee"         # cyan
ACCENT2 = "#60a5fa"        # blue
ACCENT3 = "#a78bfa"        # violet
SUCCESS = "#34d399"
INFO = "#60a5fa"
WARN = "#fbbf24"
ERROR = "#f87171"
TEXT = "#c7d2fe"

QSS = f"""
QWidget {{
    background: {DARK_BG};
    color: {TEXT};
    font-family: 'JetBrains Mono', 'Cascadia Mono', Consolas, monospace;
    font-size: 12px;
}}
QFrame#LeftPanel {{
    background: {PANEL_BG};
    border-radius: 10px;
    border: 1px solid #1f2a44;
}}
QFrame#RightPanel {{
    background: {PANEL_BG2};
    border-radius: 10px;
    border: 1px solid #1f2a44;
}}
QLineEdit, QTextEdit {{
    background: #0b1020;
    border: 1px solid #1f2a44;
    border-radius: 8px;
    padding: 8px;
    color: {TEXT};
}}
QPushButton {{
    background: #1f2a44;
    border: 1px solid #2a3d6b;
    border-radius: 8px;
    padding: 6px 10px;
}}
QPushButton:hover {{
    border-color: {ACCENT2};
}}
QPushButton#Exec {{
    background: {ACCENT2};
    color: #0b1020;
    font-weight: 600;
}}
QTableWidget {{
    background: #0b1020;
    border: 1px solid #1f2a44;
    border-radius: 8px;
    gridline-color: #2a3d6b;
}}
QHeaderView::section {{
    background: #0b1730;
    color: {TEXT};
    padding: 6px;
    border: none;
}}
"""

# ---------------------------------
# Stream redirect to capture prints
# ---------------------------------
class QtStream(QObject):
    text = pyqtSignal(str, str)  # (level, line)

    def write(self, msg):
        if msg.strip():
            self.text.emit("INFO", msg.rstrip("\n"))

    def flush(self):  # needed for file-like compliance
        pass

# ----------------
# Worker utilities
# ----------------
class WorkerThread(threading.Thread):
    def __init__(self, target, *args, **kwargs):
        super().__init__(daemon=True)
        self._target = target
        self._args = args
        self._kwargs = kwargs
        self.exc = None

    def run(self):
        try:
            self._target(*self._args, **self._kwargs)
        except Exception as e:
            self.exc = e
            traceback.print_exc()


# --------------
# Main UI Window
# --------------
class NodeMonitor(QWidget):
    def __init__(self, start_mode: str, node_name: str, interest_name: str|None):
        super().__init__()
        self.start_mode = start_mode
        self.node_name = node_name
        self.interest_name = interest_name

        self.setWindowTitle("NDN Node Monitor")
        self.resize(1100, 720)
        self.setStyleSheet(QSS)

        # Layout scaffold
        root = QVBoxLayout(self); root.setContentsMargins(14, 14, 14, 80); root.setSpacing(10)
        split = QHBoxLayout(); split.setSpacing(10)
        root.addLayout(split)

        # Left: Logs
        self.left = QFrame(objectName="LeftPanel")
        self.left.setFrameShape(QFrame.StyledPanel)
        leftlay = QVBoxLayout(self.left); leftlay.setContentsMargins(12, 12, 12, 12); leftlay.setSpacing(8)
        title_logs = QLabel("DEBUG LOGS")
        title_logs.setStyleSheet(f"color:{SUCCESS}; font-weight:700;")
        self.ns_label = QLabel("/dlsu/goks")
        self.ns_label.setStyleSheet("background:#0b1020; border:1px solid #1f2a44; border-radius:6px; padding:2px 6px; color:#9ca3af;")
        tt = QHBoxLayout(); tt.addWidget(title_logs); tt.addStretch(1); tt.addWidget(self.ns_label)
        leftlay.addLayout(tt)

        self.logs = QTextEdit(); self.logs.setReadOnly(True)
        self.logs.setFont(QFont("JetBrains Mono", 10))
        leftlay.addWidget(self.logs, 1)
        split.addWidget(self.left, 1)

        # Right: Data structures
        self.right = QFrame(objectName="RightPanel")
        self.right.setFrameShape(QFrame.StyledPanel)
        rightlay = QVBoxLayout(self.right); rightlay.setContentsMargins(12, 12, 12, 12); rightlay.setSpacing(8)
        title_ds = QLabel("DATA STRUCTURES")
        title_ds.setStyleSheet(f"color:{ACCENT2}; font-weight:700;")
        rightlay.addWidget(title_ds)

        # Counters panel (PIT, FIB, CS, Faces)
        counters = QHBoxLayout(); counters.setSpacing(10)
        self.pit_box = self._make_counter("PIT", ACCENT)
        self.fib_box = self._make_counter("FIB", ACCENT2)
        self.cs_box  = self._make_counter("CS", ACCENT3)
        self.face_box= self._make_counter("FACES", SUCCESS)
        for w in (self.pit_box, self.fib_box, self.cs_box, self.face_box):
            counters.addWidget(w)
        rightlay.addLayout(counters)

        # Cache table
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["NAME","SIZE","CACHED TIME"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        rightlay.addWidget(self.table, 1)
        split.addWidget(self.right, 1)

        # Bottom command bar
        bottom = QHBoxLayout(); bottom.setSpacing(8)
        self.cmd = QLineEdit(); self.cmd.setPlaceholderText("Enter command (e.g., show pit, show fib, show cs, show faces, clear logs, send interest /dlsu/ccs/img21, stats)")
        self.exec_btn = QPushButton("EXECUTE"); self.exec_btn.setObjectName("Exec"); self.exec_btn.clicked.connect(self.handle_command)
        # quick actions
        for label in ["show pit", "show fib", "show cs", "show faces", "clear logs", "send interest", "stats"]:
            b = QPushButton(label)
            b.clicked.connect(lambda checked=False, t=label: self.quick_command(t))
            bottom.addWidget(b)
        bottom.addStretch(1)
        bottom.addWidget(self.cmd, 3)
        bottom.addWidget(self.exec_btn, 0)
        root.addLayout(bottom)

        # Connect stdout
        self.qt_stream = QtStream()
        self.qt_stream.text.connect(self.append_log)
        sys.stdout = self.qt_stream  # redirect prints
        sys.stderr = self.qt_stream

        # Start backend in a worker if requested
        if self.start_mode == "node":
            self.backend = WorkerThread(target=node_runner.run_node, args=(self.node_name,))
            self.backend.start()
        elif self.start_mode == "client" and self.interest_name:
            # run client in a thread so UI stays responsive
            self.backend = WorkerThread(target=node_runner.run_client, args=(self.node_name, self.interest_name))
            self.backend.start()
        else:
            self.backend = None

        # Timer to refresh counters/table
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh_stats)
        self.timer.start(800)

    # ----- UI helpers -----
    def _make_counter(self, label: str, color: str) -> QWidget:
        box = QFrame()
        box.setFrameShape(QFrame.StyledPanel)
        lay = QVBoxLayout(box); lay.setContentsMargins(10,10,10,10)
        t = QLabel(label); t.setStyleSheet(f"color:{color}; font-size:12pt; font-weight:700;")
        v = QLabel("0"); v.setStyleSheet("font-size:22pt; font-weight:800;")
        v.setObjectName(f"val_{label.lower()}")
        lay.addWidget(t); lay.addWidget(v); lay.addStretch(1)
        return box

    def _set_counter(self, name: str, value: int):
        lab = self.findChild(QLabel, f"val_{name}")
        if lab:
            lab.setText(str(value))

    # ----- Logging -----
    def append_log(self, level: str, line: str):
        color = {"SUCCESS": SUCCESS, "INFO": INFO, "WARN": WARN, "ERROR": ERROR}.get(level, INFO)
        ts = datetime.now().strftime("%I:%M:%S %p")
        html = f'<span style="color:{INFO}">[{ts}]</span> <span style="color:{color}">[{level}]</span> {line}'
        self.logs.append(html)
        self.logs.moveCursor(QTextCursor.End)

    # ----- Commands -----
    def quick_command(self, txt: str):
        if txt == "send interest":
            # prefill with example path
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
                parts = raw.split(" ", 2)
                if len(parts) < 3:
                    self.append_log("WARN", "Usage: send interest /path/name")
                    return
                name = parts[2].strip()
                self.append_log("INFO", f"Sending interest for {name} ...")
                t = WorkerThread(target=node_runner.run_client, args=(self.node_name, name))
                t.start()
                return

            self.append_log("WARN", f"Unknown command: {raw}")
        except Exception as e:
            self.append_log("ERROR", f"{e}")

    def _safe_len(self, obj):
        try:
            return len(obj)
        except Exception:
            return 0

    def refresh_stats(self, force_log: bool=False):
        # Try to read common structures from NamedAI
        pit = getattr(NN, "PIT", {})
        fib = getattr(NN, "FIB", {})
        cs  = getattr(NN, "CS", {})
        faces = getattr(NN, "FACES", None)

        self._set_counter("pit", self._safe_len(pit))
        self._set_counter("fib", self._safe_len(fib))
        self._set_counter("cs", self._safe_len(cs))
        if isinstance(faces, (list, dict)):
            self._set_counter("faces", self._safe_len(faces))
        else:
            # Try to infer faces from FIB next-hops
            unique_faces = set()
            try:
                for v in fib.values():
                    if isinstance(v, (list, tuple)):
                        unique_faces.update(v)
                self._set_counter("faces", len(unique_faces) or 0)
            except Exception:
                self._set_counter("faces", 0)

        # Populate cache/table from CS (assuming dict-like)
        try:
            entries = []
            if isinstance(cs, dict):
                for name, meta in cs.items():
                    size = meta.get("size", "")
                    ctime = meta.get("cached_time", "")
                    entries.append((name, size, ctime))
            elif isinstance(cs, list):
                for item in cs:
                    name = item.get("name","")
                    size = item.get("size","")
                    ctime = item.get("cached_time","")
                    entries.append((name, size, ctime))
            else:
                entries = []

            self.table.setRowCount(len(entries))
            for r, (name, size, ctime) in enumerate(entries):
                self.table.setItem(r, 0, QTableWidgetItem(str(name)))
                self.table.setItem(r, 1, QTableWidgetItem(str(size)))
                self.table.setItem(r, 2, QTableWidgetItem(str(ctime)))
        except Exception as e:
            # Non-fatal
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--node", help="Run a node with this node_name (per node_config.json).")
    ap.add_argument("--client", nargs=2, metavar=("NODE_NAME", "INTEREST"), help="Send Interest from NODE_NAME for INTEREST.")
    args = ap.parse_args()

    if (args.node is None) == (args.client is None):
        print("Choose exactly one mode: --node <node_name>  OR  --client <node_name> <interest_name>")
        return

    if args.node:
        start_mode = "node"; node_name = args.node; interest = None
    else:
        start_mode = "client"; node_name, interest = args.client

    app = QApplication(sys.argv)
    win = NodeMonitor(start_mode, node_name, interest)
    win.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()