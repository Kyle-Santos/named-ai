import sys
import os
import socket
from functions import detect_face, grayscale, resize
import time
import json
import threading, queue

send_queue = queue.Queue()

# Add parent directory to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import NamedAI as NN  

# -----------------------------
# Load Config
# -----------------------------
with open("../node_config.json", "r") as f:
    config = json.load(f)

NODE_NAME = "/dlsu/goks"
node_config = next(n for n in config["nodes"] if n["name"] == NODE_NAME)

NN.NODE_NAME = node_config["name"]
NODE_IP = node_config["ip"]

# Build FIB from config (if it exists)
NN.FIB = node_config.get("FIB", {})


# Create UDP sockets for each face/interface
INTERFACES = NN.create_interface(node_config["interfaces"])  # { face: { "sock": socket, "face": face, "port": port } }

print(f"\033[92m{NN.NODE_NAME}\033[0m running with faces: {list(INTERFACES.keys())}") 

# -----------------------------
# Run node loop
# -----------------------------
def run_node():
    while True:
        for face, entry in INTERFACES.items():
            # Wait for incoming packet
            try:
                raw_packet, addr = NN.receive_packet(entry["sock"])
            except socket.timeout:
                continue

            parsed, err = NN.parse_packet(raw_packet)

            print(f'\nPacket Received on {face} (from {addr})')

            if err:
                print(f"Error: {err}")
                continue

            if parsed["type"] == "interest":
                NN.process_interest(parsed, addr, entry["sock"], interface=face)
            elif parsed["type"] == "data":
                NN.process_data(parsed, raw_packet, entry["sock"])
            else:
                print("Unknown packet type received")


# -----------------------------
# Receiver (one per interface)
# -----------------------------
def receiver(face, entry):
    sock = entry["sock"]
    while True:
        try:
            raw_packet, addr = NN.receive_packet(sock)
            parsed, err = NN.parse_packet(raw_packet)

            if err:
                print(f"[ERROR] {err}")
                continue

            print(f"\nPacket received on {face} from {addr}")

            if parsed["type"] == "interest":
                # queue up response instead of sending directly
                send_queue.put(("interest", parsed, addr, sock, face))
            elif parsed["type"] == "data":
                send_queue.put(("data", parsed, raw_packet, sock))
        except Exception as e:
            print(f"[Receiver {face}] Error: {e}")



# -----------------------------
# Sender (shared across all)
# -----------------------------
def sender():
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
            print(f"[Sender] Error: {e}")



if __name__ == "__main__":
    try:
        # Start a receiver thread for each interface
        for face, entry in INTERFACES.items():
            t = threading.Thread(target=receiver, args=(face, entry), daemon=True)
            t.start()

        # Start the sender thread
        threading.Thread(target=sender, daemon=True).start()

        # Keep main alive
        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        print("\nShutting down node...")
