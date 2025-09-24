import socket
import time
import sys
import os

# Add parent directory to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import NamedAI as NN

DLSU_PORT=9001
DLSU_ADDR="127.0.0.1"

CLIENT_ADDR = ("127.0.0.1", 12345)
NN.NODE_ADDR = CLIENT_ADDR

interest_name="/dlsu/goks/cam/capture8.jpg"

interest_name="/dlsu/goks/detect(/dlsu/goks/cam/capture8.jpg)"


def run_client():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(CLIENT_ADDR)  # listen on port 12345

    # Build Interest packet
    interest_packet = NN.build_interest_packet(interest_name)
    print(f"[DEBUG] Raw Interest Packet: {interest_packet}")
    print(f"[DEBUG] Packet Size: {len(interest_packet)} bytes")

    send_time = time.time()
    print(f"[Client] Sending Interest for '{interest_name}' at {time.strftime('%H:%M:%S', time.localtime(send_time))}")
    sock.sendto(interest_packet, (DLSU_ADDR, DLSU_PORT))

    NN.store_interest(interest_name, CLIENT_ADDR)

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
