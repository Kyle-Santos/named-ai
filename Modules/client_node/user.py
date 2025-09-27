import socket
import time
import sys
import os
import json

# Add parent directory to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import NamedAI as NN

interest_name="/dlsu/goks/cam/capture8.jpg"
# interest_name="/dlsu/goks/detect(/dlsu/goks/cam/capture8.jpg)"

# -----------------------------
# Load Config
# -----------------------------
with open("../node_config.json", "r") as f:
    config = json.load(f)

NODE_NAME = "client"
node_config = next(n for n in config["nodes"] if n["name"] == NODE_NAME)

NN.NODE_NAME = node_config["name"]
NODE_IP = node_config["ip"]

# Build FIB from config (if it exists)
NN.FIB = node_config.get("FIB", {})

# Create UDP sockets for each face/interface
INTERFACES = NN.create_interface(node_config["interfaces"])  # { face: { "sock": socket, "face": face, "port": port } }

print(f"\033[92m{NN.NODE_NAME}\033[0m running with faces: {list(INTERFACES.keys())}") 


def run_client():
    entry = INTERFACES["face0"]
    sock = entry["sock"]

    # Build Interest packet
    interest_packet = NN.build_interest_packet(interest_name)
    print(f"[DEBUG] Raw Interest Packet: {interest_packet}")
    print(f"[DEBUG] Packet Size: {len(interest_packet)} bytes")

    send_time = time.time()
    print(f"[Client] Sending Interest for '{interest_name}' at {time.strftime('%H:%M:%S', time.localtime(send_time))}")
    face, dest_port = NN.lookup_fib(interest_name)
    sock.sendto(interest_packet, ("127.0.0.1", dest_port))

    NN.store_interest(interest_name, None, ("127.0.0.1", entry["port"]))

    # Collect responses (could be fragmented)
    sock.settimeout(5)  # 5 seconds timeout
    try:
        while True:
            raw_packet, addr = NN.receive_packet(sock)

            parsed, err = NN.parse_packet(raw_packet)
            # print(parsed)

            if err:
                print(f"[Client] Error parsing response: {err}")
                continue

            if parsed["type"] == "data":
                recv_time = time.time()
                print(f"[Client] Got fragment from {addr} at {time.strftime('%H:%M:%S', time.localtime(recv_time))}")
                NN.process_data(parsed, raw_packet, sock)  # NN module will handle reassembly

                # If full image assembled, break 
                frag_num = parsed.get("frag_num", 0)
                frag_total = parsed.get("frag_total", 0)

                if frag_total != 0 and parsed.get("name") not in NN.FRAG_BUFFER:
                    rtt = recv_time - send_time
                    print(f"[Client] Round Trip Time (RTT): {rtt:.3f} seconds")
                    break

    except socket.timeout:
        print("[Client] No Data received (timeout)")

    sock.close()


if __name__ == "__main__":
    run_client()
