import socket
import time
import sys
import os

# Add parent directory to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import NamedAI as NN


def run_client(server_addr="127.0.0.1", server_port=9001, interest_name="/dlsu/goks/cam/capture5.jpg"):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    # Build Interest packet
    interest_packet = NN.build_interest_packet(interest_name)
    print(f"[DEBUG] Raw Interest Packet: {interest_packet}")
    print(f"[DEBUG] Packet Size: {len(interest_packet)} bytes")

    send_time = time.time()
    print(f"[Client] Sending Interest for '{interest_name}' at {time.strftime('%H:%M:%S', time.localtime(send_time))}")
    sock.sendto(interest_packet, (server_addr, server_port))

    # Collect responses (could be fragmented)
    sock.settimeout(5)  # 5 seconds timeout
    try:
        while True:
            raw_packet, addr = sock.recvfrom(4096)  # allow large UDP payloads
            recv_time = time.time()

            parsed, err = NN.parse_packet(raw_packet)
            # print(parsed)

            if err:
                print(f"[Client] Error parsing response: {err}")
                continue

            if parsed["type"] == "data":
                print(f"[Client] Got fragment from {addr} at {time.strftime('%H:%M:%S', time.localtime(recv_time))}")
                NN.process_data(parsed, raw_packet, sock)  # NN module will handle reassembly

                # If full image assembled, break 
                frag_flag = parsed.get("frag_flag", 0)
                frag_id = parsed.get("frag_id", 0)
                # if frag_flag == 0 or frag_id not in NN.FRAG_BUFFER:
                if frag_id not in NN.FRAG_BUFFER:
                    rtt = recv_time - send_time
                    print(f"[Client] Round Trip Time (RTT): {rtt:.3f} seconds")
                    break

    except socket.timeout:
        print("[Client] No Data received (timeout)")

    sock.close()


if __name__ == "__main__":
    run_client()
