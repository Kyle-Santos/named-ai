


import sys
import random
from datetime import datetime
from PyQt5 import QtCore, QtGui, QtWidgets
import ui_interface

DARK_BG = "#0e1621"
PANEL_BG = "#111c2b"
CARD_BG = "#0f1b2a"
ACCENT = "#00d4ff"
SUCCESS = "#2dd36f"
INFO = "#4dabf7"
WARNING = "#ffc107"
ERROR = "#ff6b6b"
TEXT = "#c7d5e0"
MUTED = "#7f8ca3"
BORDER = "#213147"

def ts():
    return datetime.now().strftime("%I:%M:%S %p")

class PillButton(QtWidgets.QPushButton):
    def __init__(self, text, checkable=False, parent=None):
        super().__init__(text, parent)
        self.setCheckable(checkable)
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setMinimumHeight(30)
        self.setStyleSheet(f"""
            QPushButton {{
                color: {TEXT};
                background-color: #0e2236;
                border: 1px solid {BORDER};
                border-radius: 16px;
                padding: 4px 12px;
            }}
            QPushButton:hover {{
                background-color: #12324d;
            }}
            QPushButton:checked {{
                background-color: #15527e;
                border-color: {ACCENT};
            }}
        """)

class StatCard(QtWidgets.QFrame):
    def __init__(self, title, value="0", parent=None):
        super().__init__(parent)
        self.setObjectName("StatCard")
        self.setStyleSheet(f"""
            QFrame#StatCard {{
                background-color: {CARD_BG};
                border: 1px solid {BORDER};
                border-radius: 12px;
            }}
            QLabel {{ color: {TEXT}; }}
            QLabel[role="title"] {{
                color: {MUTED};
                font-size: 12px;
                letter-spacing: .5px;
            }}
            QLabel[role="value"] {{
                font-size: 28px;
                font-weight: 700;
            }}
        """)
        lay = QtWidgets.QVBoxLayout(self); lay.setContentsMargins(14, 12, 14, 12); lay.setSpacing(4)
        self.title = QtWidgets.QLabel(title); self.title.setProperty("role", "title")
        self.value = QtWidgets.QLabel(value); self.value.setProperty("role", "value")
        lay.addWidget(self.title)
        lay.addStretch(1)
        lay.addWidget(self.value, alignment=QtCore.Qt.AlignLeft | QtCore.Qt.AlignBottom)

    def setValue(self, v):
        self.value.setText(str(v))

class LogsPanel(QtWidgets.QFrame):
    appendRequested = QtCore.pyqtSignal(str, str, str)  # level, path, message

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {PANEL_BG};
                border: 1px solid {BORDER};
                border-radius: 12px;
            }}
            QLabel {{ color: {TEXT}; }}
            QPlainTextEdit {{
                background-color: transparent;
                color: {TEXT};
                border: none;
                font-family: 'JetBrains Mono', Consolas, monospace;
                font-size: 12px;
            }}
        """)
        wrap = QtWidgets.QVBoxLayout(self); wrap.setContentsMargins(12, 10, 12, 10); wrap.setSpacing(8)
        hdr = QtWidgets.QHBoxLayout(); hdr.setSpacing(8)
        icon = QtWidgets.QLabel("🪵")
        title = QtWidgets.QLabel("DEBUG LOGS")
        title.setStyleSheet("font-weight: 700; letter-spacing: .5px;")
        self.scope = QtWidgets.QLineEdit("/dlsu/goks")
        self.scope.setReadOnly(True)
        self.scope.setFixedWidth(120)
        self.scope.setStyleSheet(f"color:{TEXT}; background:#0e2236; border:1px solid {BORDER}; border-radius:8px; padding:2px 6px;")
        hdr.addWidget(icon); hdr.addWidget(title); hdr.addStretch(1); hdr.addWidget(self.scope)
        wrap.addLayout(hdr)

        self.view = QtWidgets.QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setWordWrapMode(QtGui.QTextOption.NoWrap)
        wrap.addWidget(self.view, 1)

        # Load real logs from backend
        self.load_logs()

    def color_for(self, level):
        return {
            "SUCCESS": SUCCESS,
            "INFO": INFO,
            "WARN": WARNING,
            "ERROR": ERROR,
        }.get(level, TEXT)

    def add_log(self, level, path, message):
        color = self.color_for(level)
        prefix = f"[{ts()}] "
        lvl = f"[{level}]"
        line = f'{prefix}{lvl:<10} {message}'
        if path:
            line += f": {path}"
        self.append_line(line, color)

    def append_line(self, line, color):
        cursor = self.view.textCursor()
        cursor.movePosition(QtGui.QTextCursor.End)
        fmt = QtGui.QTextCharFormat()
        fmt.setForeground(QtGui.QBrush(QtGui.QColor(color)))
        cursor.insertText(line + "\n", fmt)
        self.view.setTextCursor(cursor)
        self.view.ensureCursorVisible()

    def load_logs(self):
        self.view.clear()
        logs = ui_interface.get_logs()
        for timestamp, level, message, path in logs:
            self.add_log(level, path, message)

class DataPanel(QtWidgets.QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {PANEL_BG};
                border: 1px solid {BORDER};
                border-radius: 12px;
            }}
            QLabel {{ color: {TEXT}; }}
            QTableWidget {{
                background-color: #0f1b2a;
                color: {TEXT};
                gridline-color: {BORDER};
                border: 1px solid {BORDER};
                border-radius: 10px;
            }}
            QHeaderView::section {{
                background-color: #13263d;
                color: {TEXT};
                padding: 8px 10px;
                border: none;
            }}
        """)
        root = QtWidgets.QVBoxLayout(self); root.setContentsMargins(12, 10, 12, 12); root.setSpacing(8)

        # Header with filter chips
        hdr = QtWidgets.QHBoxLayout(); hdr.setSpacing(8)
        lbl = QtWidgets.QLabel("DATA STRUCTURES")
        lbl.setStyleSheet("font-weight: 700; letter-spacing: .5px;")
        self.btnPit = PillButton("PIT", checkable=True)
        self.btnFib = PillButton("FIB", checkable=True)
        self.btnCs = PillButton("CS", checkable=True)
        self.btnFaces = PillButton("FACES", checkable=True)
        self.btnPit.setChecked(True)
        hdr.addWidget(lbl); hdr.addStretch(1)
        hdr.addWidget(self.btnPit); hdr.addWidget(self.btnFib); hdr.addWidget(self.btnCs); hdr.addWidget(self.btnFaces)
        root.addLayout(hdr)

        # Stat cards grid
        grid = QtWidgets.QGridLayout(); grid.setHorizontalSpacing(12); grid.setVerticalSpacing(12)
        self.cardPit = StatCard("PIT ENTRIES", "4")
        self.cardFib = StatCard("FIB ROUTES", "3")
        self.cardCs = StatCard("CS ENTRIES", "6")
        self.cardFaces = StatCard("FACES", "3")
        grid.addWidget(self.cardPit, 0, 0)
        grid.addWidget(self.cardFib, 0, 1)
        grid.addWidget(self.cardCs, 1, 0)
        grid.addWidget(self.cardFaces, 1, 1)
        root.addLayout(grid)

        # Table
        self.table = QtWidgets.QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["NAME", "SIZE", "CACHED TIME"])
        self.table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        root.addWidget(self.table, 1)

        # Seed with PIT data by default
        self.populate_table(self.get_pit_data())

        # Hooks for filter buttons
        self.btnPit.toggled.connect(lambda checked: self.on_filter_changed("pit", checked))
        self.btnFib.toggled.connect(lambda checked: self.on_filter_changed("fib", checked))
        self.btnCs.toggled.connect(lambda checked: self.on_filter_changed("cs", checked))
        self.btnFaces.toggled.connect(lambda checked: self.on_filter_changed("faces", checked))

    def on_filter_changed(self, data_type, checked):
        if checked:
            if data_type == "pit":
                self.populate_table(self.get_pit_data())
            elif data_type == "fib":
                self.populate_table(self.get_fib_data())
            elif data_type == "cs":
                self.populate_table(self.get_cs_data())
            elif data_type == "faces":
                self.populate_table(self.get_faces_data())

    def get_pit_data(self):
        return ui_interface.get_pit_data()

    def get_fib_data(self):
        return ui_interface.get_fib_data()

    def get_cs_data(self):
        return ui_interface.get_cs_data()

    def get_faces_data(self):
        return ui_interface.get_faces_data()

    def populate_table(self, rows):
        self.table.setRowCount(0)
        for name, size, t in rows:
            r = self.table.rowCount()
            self.table.insertRow(r)
            for c, val in enumerate([name, size, t]):
                item = QtWidgets.QTableWidgetItem(val)
                item.setFlags(item.flags() ^ QtCore.Qt.ItemIsEditable)
                self.table.setItem(r, c, item)

class CommandBar(QtWidgets.QFrame):
    executeCommand = QtCore.pyqtSignal(str)
    quickAction = QtCore.pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {PANEL_BG};
                border: 1px solid {BORDER};
                border-radius: 12px;
            }}
            QLabel {{ color: {TEXT}; }}
            QLineEdit {{
                color: {TEXT};
                background-color: #0f1b2a;
                border: 1px solid {BORDER};
                border-radius: 10px;
                padding: 10px;
            }}
            QPushButton#exec {{
                color: black;
                background-color: {ACCENT};
                border-radius: 10px;
                padding: 10px 14px;
                font-weight: 700;
            }}
            QPushButton#exec:hover {{ filter: brightness(0.9); }}
        """)
        root = QtWidgets.QVBoxLayout(self); root.setContentsMargins(12, 8, 12, 12); root.setSpacing(8)
        title = QtWidgets.QLabel("COMMAND INPUT")
        title.setStyleSheet("font-weight: 700; letter-spacing: .5px;")
        root.addWidget(title)

        row = QtWidgets.QHBoxLayout(); row.setSpacing(8)
        self.edit = QtWidgets.QLineEdit()
        self.edit.setPlaceholderText("Enter command (e.g., show pit, show fib, show cs, show faces, clear logs)")
        self.execBtn = QtWidgets.QPushButton("EXECUTE"); self.execBtn.setObjectName("exec")
        self.execBtn.setCursor(QtCore.Qt.PointingHandCursor)
        row.addWidget(self.edit, 1); row.addWidget(self.execBtn)
        root.addLayout(row)

        # Quick actions row
        chips = QtWidgets.QHBoxLayout(); chips.setSpacing(8)
        for label in ["show pit", "show fib", "show cs", "show faces", "clear logs", "send interest", "stats"]:
            b = PillButton(label)
            b.clicked.connect(lambda _, t=label: self.quickAction.emit(t))
            chips.addWidget(b)
        chips.addStretch(1)
        root.addLayout(chips)

        self.execBtn.clicked.connect(lambda: self.executeCommand.emit(self.edit.text().strip()))
        self.edit.returnPressed.connect(lambda: self.execBtn.click())

class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("NDN Debug Console (PyQt)")
        self.resize(1150, 700)
        self.setStyleSheet(f"QMainWindow {{ background-color: {DARK_BG}; }}")

        central = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(central); v.setContentsMargins(16, 16, 16, 16); v.setSpacing(12)

        # Splitter for top: logs (left) and data (right)
        top = QtWidgets.QSplitter()
        top.setOrientation(QtCore.Qt.Horizontal)
        self.logs = LogsPanel()
        self.data = DataPanel()
        top.addWidget(self.logs)
        top.addWidget(self.data)
        top.setSizes([480, 680])
        v.addWidget(top, 1)

        # Command bar bottom
        self.cmd = CommandBar()
        v.addWidget(self.cmd, 0)

        self.setCentralWidget(central)

        # Wire events
        self.cmd.executeCommand.connect(self.on_execute)
        self.cmd.quickAction.connect(self.on_quick)

        # Load initial stats
        self.load_stats()

        # Periodic refresh for logs and data
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.refresh_ui)
        self.timer.start(5000)  # every 5 seconds

    def load_stats(self):
        stats = ui_interface.get_stats()
        self.data.cardPit.setValue(stats["pit"])
        self.data.cardFib.setValue(stats["fib"])
        self.data.cardCs.setValue(stats["cs"])
        self.data.cardFaces.setValue(stats["faces"])

    def refresh_ui(self):
        # Refresh logs
        self.logs.load_logs()
        # Refresh stats
        self.load_stats()
        # Refresh table if PIT is selected
        if self.data.btnPit.isChecked():
            self.data.populate_table(self.data.get_pit_data())

    def on_quick(self, label):
        self.handle_command(label)

    def on_execute(self, cmd):
        if not cmd:
            return
        self.handle_command(cmd)

    def handle_command(self, cmd):
        c = cmd.lower()
        if c in ("show pit", "pit", "showpit"):
            self.logs.add_log("INFO", "", "Showing PIT entries")
            self.data.cardPit.setValue(len(ui_interface.get_pit_data()))
            self.data.populate_table(ui_interface.get_pit_data())
        elif c in ("show fib", "fib"):
            self.logs.add_log("INFO", "", "Showing FIB routes")
            self.data.cardFib.setValue(len(ui_interface.get_fib_data()))
            self.data.populate_table(ui_interface.get_fib_data())
        elif c in ("show cs", "cs"):
            self.logs.add_log("INFO", "", "Showing CS entries")
            self.data.cardCs.setValue(len(ui_interface.get_cs_data()))
            self.data.populate_table(ui_interface.get_cs_data())
        elif c in ("show faces", "faces"):
            self.logs.add_log("INFO", "", "Showing faces")
            self.data.cardFaces.setValue(len(ui_interface.get_faces_data()))
            self.data.populate_table(ui_interface.get_faces_data())
        elif c in ("clear logs", "clear"):
            ui_interface.clear_logs()
            self.logs.load_logs()
        elif c in ("send interest", "interest"):
            path = f"/dlsu/goks/img{random.randint(10,60)}"
            ui_interface.send_interest(path)
            self.logs.add_log("INFO", path, "Interest sent")
        elif c in ("stats", "show stats"):
            stats = ui_interface.get_stats()
            self.data.cardPit.setValue(stats["pit"])
            self.data.cardFib.setValue(stats["fib"])
            self.data.cardCs.setValue(stats["cs"])
            self.data.cardFaces.setValue(stats["faces"])
            self.logs.add_log("SUCCESS", "", "Stats updated")
        else:
            self.logs.add_log("ERROR", "", f"Unknown command '{cmd}'")

def main():
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("NDN Debug Console")
    # Enable high-DPI scaling
    QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_EnableHighDpiScaling, True)
    QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_UseHighDpiPixmaps, True)
    w = MainWindow()
    w.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
