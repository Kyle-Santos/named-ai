import sys
import os
import time

# Add parent directory to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import NamedAI as NN  

NN.NODE_NAME = "/dlsu/goks"
# NN.STORAGE_PATH = "captures/"

# name, port, time
NN.FIB = { 
    "/dlsu/goks/cam": { "port": 9000, "time": time.time() }
}

def run_node(bind_port=9001):

    sock = NN.create_udp_socket(bind_port=bind_port)
    print(f"\033[92m{NN.NODE_NAME}\033[0m running on UDP port {bind_port}")

    while True:
        raw_packet, addr = NN.receive_packet(sock)
        parsed, err = NN.parse_packet(raw_packet)

        print(f'\nPacket Received From {addr}')
        # print(parsed)

        if err:
            print(f"Error: {err}")
            continue
        
        if parsed["type"] == "interest":
            NN.process_interest(parsed, addr, sock)
        elif parsed["type"] == "data":
            NN.process_data(parsed, raw_packet, sock)
        else:
            print("Unknown packet type received")


if __name__ == "__main__":
    run_node()
