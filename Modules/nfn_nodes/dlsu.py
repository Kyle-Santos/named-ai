import sys
import os
import socket

# Add parent directory to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import NamedAI as NN  

NODE_PORT=9000
NN.NODE_NAME = "/dlsu"

# name, port, time
NN.FIB = { 
    "/dlsu/goks": 9001,
    "/dlsu/andrew": 9002,
    "/dlsu/velasco": 9003  
}

def run_node():

    sock = NN.create_udp_socket(bind_port=NODE_PORT)
    print(f"\033[92m{NN.NODE_NAME}\033[0m running on UDP port {NODE_PORT}")
    sock.settimeout(1.0)  # 1 second timeout

    while True:
        try:
            raw_packet, addr = NN.receive_packet(sock)
        except socket.timeout:
            continue  # loop back and check for Ctrl + C
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
    try:
        run_node()
    except KeyboardInterrupt:
        print("\nShutting down node...")
