import sys
import os
import socket
from functions import detect_face, grayscale, resize
import time
import json

# Add parent directory to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import NamedAI as NN  

# -----------------------------
# Load Config
# -----------------------------
with open("node_config.json", "r") as f:
    config = json.load(f)

NODE_NAME = "/dlsu/goks"
node_config = next(n for n in config["nodes"] if n["name"] == NODE_NAME)

NN.NODE_NAME = node_config["name"]
NODE_IP = node_config["ip"]

# Build FIB from config (if it exists)
NN.FIB = node_config.get("FIB", {})

# multiple interfaces supported
# CLI interaction


# Create UDP sockets for each face/interface
INTERFACES = NN.create_interface(node_config["interfaces"])  # list of {"face": "face_name", "port": port_number}

print(f"\033[92m{NN.NODE_NAME}\033[0m running with faces:")

# -----------------------------
# Run node loop
# -----------------------------
def run_node():
    while True:
        for face, sock in INTERFACES.items():
            # Wait for incoming packet
            try:
                raw_packet, addr = NN.receive_packet(sock)
            except socket.timeout:
                continue

            parsed, err = NN.parse_packet(raw_packet)

            print(f'\nPacket Received on {face} (from {addr})')

            if err:
                print(f"Error: {err}")
                continue

            if parsed["type"] == "interest":
                NN.process_interest(parsed, addr, sock, incoming_face=face)
            elif parsed["type"] == "data":
                NN.process_data(parsed, raw_packet, sock, incoming_face=face)
            else:
                print("Unknown packet type received")

if __name__ == "__main__":
    try:
        run_node()
    except KeyboardInterrupt:
        print("\nShutting down node...")
