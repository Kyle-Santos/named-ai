import sys
import os
from datetime import datetime

sys.path.append(os.path.join(os.path.dirname(__file__), 'Modules'))
from NamedAI import PIT, FIB, CS, INTERFACES, LOGS, log

def get_pit_data():
    data = []
    for name, entry in PIT.items():
        interfaces = ", ".join(str(face) for face in entry["interface"])
        time_str = datetime.fromtimestamp(entry["time"]).strftime("%I:%M:%S %p")
        data.append((name, interfaces, time_str))
    return data

def get_fib_data():
    data = []
    for prefix, entry in FIB.items():
        data.append((prefix, entry["face"], str(entry["port"])))
    return data

def get_cs_data():
    data = []
    for name, entry in CS.items():
        size = f"{len(entry['data'])} bytes" if 'data' in entry else "N/A"
        cached_time = datetime.now().strftime("%I:%M:%S %p")
        data.append((name, size, cached_time))
    return data

def get_faces_data():
    data = []
    for face, info in INTERFACES.items():
        status = "Active"
        data.append((face, str(info["port"]), status))
    return data

def send_interest(name):
    log("INFO", f"Interest sent for {name}")

def get_logs():
    return [(entry["timestamp"], entry["level"], entry["message"], entry["path"]) for entry in LOGS[-50:]]

def clear_logs():
    LOGS.clear()
    log("SUCCESS", "Logs cleared")

def get_stats():
    return {
        "pit": len(PIT),
        "fib": len(FIB),
        "cs": len(CS),
        "faces": len(INTERFACES)
    }
