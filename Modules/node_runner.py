# node_runner.py
import os, sys, socket, json, time, threading, queue
import NamedAI as NN  

send_queue = queue.Queue()

# -----------------------------
# Define a root path for configs
# -----------------------------
ROOT_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), ""))  
CONFIG_PATH = os.path.join(ROOT_PATH, "node_config.json")



def load_node_config(config_path: str, node_name: str):
    """Load node configuration by node_name."""
    with open(config_path, "r") as f:
        config = json.load(f)
    node_config = next(n for n in config["nodes"] if n["name"] == node_name)

    NN.set_ip_addr(config.get("ip", "127.0.0.1"))
    
    NN.NODE_NAME = node_config["name"]
    NN.STORAGE_PATH = node_config.get("storage", "")  # default "" if not present
    NN.FIB = node_config.get("FIB", {})
    return node_config


def create_interfaces(node_config):
    return NN.create_interface(node_config["interfaces"])  # {face: {sock, face, port}}


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
                send_queue.put(("interest", parsed, addr, sock, face))
            elif parsed["type"] == "data":
                send_queue.put(("data", parsed, raw_packet, sock))
        except Exception as e:
            print(f"[Receiver {face}] Error: {e}")


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


def run_node(node_name: str, config_path=CONFIG_PATH):
    node_config = load_node_config(config_path, node_name)
    interfaces = create_interfaces(node_config)

    print(f"\033[92m{NN.NODE_NAME}\033[0m running with faces: {list(interfaces.keys())}")

    # Start receiver threads
    for face, entry in interfaces.items():
        t = threading.Thread(target=receiver, args=(face, entry), daemon=True)
        t.start()

    # Start sender thread
    threading.Thread(target=sender, daemon=True).start()

    # Keep alive
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down node...")



def run_client(node_name: str, interest_name: str, config_path=CONFIG_PATH):
    node_config = load_node_config(config_path, node_name)
    interfaces = create_interfaces(node_config)

    print(f"\033[92m{NN.NODE_NAME}\033[0m running with faces: {list(interfaces.keys())}")

    entry = interfaces["face0"]
    sock = entry["sock"]

    # Build Interest packet
    interest_packet = NN.build_interest_packet(interest_name)
    print(f"[DEBUG] Raw Interest Packet: {interest_packet}")
    print(f"[DEBUG] Packet Size: {len(interest_packet)} bytes")

    send_time = time.time()
    print(f"[Client] Sending Interest for '{interest_name}' at {time.strftime('%H:%M:%S', time.localtime(send_time))}")
    face, dest_port = NN.lookup_fib(interest_name)
    sock.sendto(interest_packet, (NN.IP_ADDR, dest_port))

    NN.store_interest(interest_name, None, (NN.IP_ADDR, entry["port"]))


    result_queue = queue.Queue()

    # Start receiver threads
    for face, entry in interfaces.items():
        t = threading.Thread(target=receiver_client, 
                             args=(face, entry, send_time, result_queue))
        t.start()


    try:
        rtt = result_queue.get(timeout=5)   # wait max 5s
        print(f"[Client] Interest satisfied, RTT: {rtt:.4f}s")
    except queue.Empty:
        print("[Client] Timeout, no Data received")


def receiver_client(face, entry, send_time, result_queue):
    sock = entry["sock"]
    while True:
        try:
            raw_packet, addr = NN.receive_packet(sock)
            parsed, err = NN.parse_packet(raw_packet)

            if err:
                print(f"[ERROR] {err}")
                continue

            print(f"\nPacket received on {face} from {addr}")

            if parsed["type"] == "data":
                recv_time = time.time()
                print(f"[Client] Got fragment from {addr} at {time.strftime('%H:%M:%S', time.localtime(recv_time))}")
                complete = NN.process_data(parsed, raw_packet, sock)  # NN module will handle reassembly

                # If full image assembled, break the loop   
                frag_total = parsed.get("frag_total", 0)
                
                if complete and frag_total != 0 and parsed.get("name") not in NN.FRAG_BUFFER:
                    rtt = recv_time - send_time
                    result_queue.put(rtt)
                    return
        except Exception as e:
            print(f"[Receiver {face}] Error: {e}")