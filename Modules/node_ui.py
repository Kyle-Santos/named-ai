import sys, time, threading, argparse, traceback
from datetime import datetime
from typing import Any, Dict, List
import node_runner
import NamedAI as NN
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QObject
from PyQt5.QtGui import QFont, QTextCursor
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, QLabel, QLineEdit,
    QPushButton, QTableWidget, QTableWidgetItem, QHeaderView, QFrame, QSizePolicy
)
DARK_BG = "#0f172a"
PANEL_BG = "#0d1321"
PANEL_BG2 = "#111827"
ACCENT = "#22d3ee"
ACCENT2 = "#60a5fa"
ACCENT3 = "#a78bfa"
SUCCESS = "#34d399"
INFO = "#60a5fa"
WARN = "#fbbf24"
ERROR = "#f87171"
TEXT = "#c7d2fe"
class QtStream(QObject):
    text = pyqtSignal(str, str)
    def write(self, msg):
        if msg.strip():
            self.text.emit("INFO", msg.rstrip("\n"))
    def flush(self):
        pass
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
class NodeMonitor(QWidget):
    def __init__(self, start_mode: str, node_name: str, interest_name: str|None):
        super().__init__()
        self.start_mode = start_mode
        self.node_name = node_name
        self.interest_name = interest_name
        self.setWindowTitle("NDN Node Monitor")
        self.resize(1100, 720)
        with open('styles.qss', 'r') as f:
            self.setStyleSheet(f.read())
        root = QVBoxLayout(self); root.setContentsMargins(14, 14, 14, 80); root.setSpacing(10)
        split = QHBoxLayout(); split.setSpacing(10)
        root.addLayout(split)
        self.left = QFrame(objectName="LeftPanel")
        self.left.setFrameShape(QFrame.StyledPanel)
        leftlay = QVBoxLayout(self.left); leftlay.setContentsMargins(12, 12, 12, 12); leftlay.setSpacing(8)
        title_logs = QLabel("DEBUG LOGS")
        title_logs.setStyleSheet(f"color:{SUCCESS}; font-weight:700;")
        self.ns_label = QLabel(self.node_name)
        self.ns_label.setStyleSheet("background:#0b1020; border:1px solid #1f2a44; border-radius:6px; padding:2px 6px; color:#9ca3af;")
        tt = QHBoxLayout(); tt.addWidget(title_logs); tt.addStretch(1); tt.addWidget(self.ns_label)
        leftlay.addLayout(tt)
        self.logs = QTextEdit(); self.logs.setReadOnly(True)
        self.logs.setFont(QFont("JetBrains Mono", 10))
        leftlay.addWidget(self.logs, 1)
        split.addWidget(self.left, 1)
        self.right = QFrame(objectName="RightPanel")
        self.right.setFrameShape(QFrame.StyledPanel)
        rightlay = QVBoxLayout(self.right); rightlay.setContentsMargins(12, 12, 12, 12); rightlay.setSpacing(8)
        title_ds = QLabel("DATA STRUCTURES")
        title_ds.setStyleSheet(f"color:{ACCENT2}; font-weight:700;")
        rightlay.addWidget(title_ds)
        counters = QHBoxLayout(); counters.setSpacing(10)
        self.pit_box = self._make_counter("PIT", ACCENT)
        self.fib_box = self._make_counter("FIB", ACCENT2)
        self.cs_box  = self._make_counter("CS", ACCENT3)
        for w in (self.pit_box, self.fib_box, self.cs_box):
            counters.addWidget(w)
        rightlay.addLayout(counters)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["NAME","SIZE","CACHED TIME"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        rightlay.addWidget(self.table, 1)
        split.addWidget(self.right, 1)
        bottom = QHBoxLayout(); bottom.setSpacing(8)
        self.cmd = QLineEdit(); self.cmd.setPlaceholderText("Enter command (e.g., show pit, show fib, show cs, show faces, clear logs, send interest /dlsu/ccs/img21, stats)")
        self.exec_btn = QPushButton("EXECUTE"); self.exec_btn.setObjectName("Exec"); self.exec_btn.clicked.connect(self.handle_command)
        for label in ["show pit", "show fib", "show cs", "clear logs", "send interest", "stats"]:
            b = QPushButton(label)
            b.clicked.connect(lambda checked=False, t=label: self.quick_command(t))
            bottom.addWidget(b)
        bottom.addStretch(1)
        bottom.addWidget(self.cmd, 3)
        bottom.addWidget(self.exec_btn, 0)
        root.addLayout(bottom)
        self.qt_stream = QtStream()
        self.qt_stream.text.connect(self.append_log)
        sys.stdout = self.qt_stream
        sys.stderr = self.qt_stream
        if self.start_mode == "node":
            self.backend = WorkerThread(target=node_runner.run_node, args=(self.node_name,))
            self.backend.start()
        elif self.start_mode == "client" and self.interest_name:
            self.backend = WorkerThread(target=node_runner.run_client, args=(self.node_name, self.interest_name))
            self.backend.start()
        else:
            self.backend = None
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh_stats)
        self.timer.start(800)
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
    def append_log(self, level: str, line: str):
        color = {"SUCCESS": SUCCESS, "INFO": INFO, "WARN": WARN, "ERROR": ERROR}.get(level, INFO)
        ts = datetime.now().strftime("%I:%M:%S %p")
        html = f'<span style="color:{INFO}">[{ts}]</span> <span style="color:{color}">[{level}]</span> {line}'
        self.logs.append(html)
        self.logs.moveCursor(QTextCursor.End)
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
        pit = getattr(NN, "PIT", {})
        fib = getattr(NN, "FIB", {})
        cs  = getattr(NN, "CS", {})
        self._set_counter("pit", self._safe_len(pit))
        self._set_counter("fib", self._safe_len(fib))
        self._set_counter("cs", self._safe_len(cs))
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
            pass
        if force_log:
            self.append_log("INFO", f"Stats — PIT: {self._safe_len(pit)}, FIB: {self._safe_len(fib)}, CS: {self._safe_len(cs)}")
    def show_structure(self, which: str):
        obj = None
        if which == "pit":
            obj = NN.INTERFACES
            # obj = getattr(NN, "INTERFACES", {})
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
