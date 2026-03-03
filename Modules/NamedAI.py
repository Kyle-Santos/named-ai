import socket
import struct
import Packet_Structure as packetStruct
import random
import re
import os
import time
import threading
import csv
from datetime import datetime

LOGS = []
GUI_CALLBACK = None

def log(level, message, path=""):
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    level_upper = level.upper()
    if level_upper not in ["INFO", "WARN", "ERROR", "SUCCESS", "DEBUG"]:
        level_upper = "INFO"  # default to INFO if invalid level
    entry = {"level": level_upper, "message": message, "path": path, "timestamp": timestamp}
    LOGS.append(entry)

    # if GUI_CALLBACK:
    if GUI_CALLBACK and level_upper not in ["INFO", "SUCCESS"]:
        GUI_CALLBACK(level_upper, message)
    # GUI_QUEUE.put((level, message))   # put into thread-safe queue

    print(f"\n[{timestamp}] [{level_upper}] {message}" + (f" {path}" if path else ""))



#########################
# Communication Module  #
#########################
IP_ADDR = "127.0.0.1"

def set_ip_addr(ip_addr):
    """Set the IP address for all interfaces (if needed)."""
    global IP_ADDR
    IP_ADDR = ip_addr

def create_udp_socket(bind_addr=IP_ADDR, bind_port=9000):
    """Create and bind a UDP socket for communication."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((bind_addr, bind_port))
    return sock


def create_interface(interfaces):
    """
    Given an interfaces list from the config, create UDP sockets for each face.

    Args:
        interfaces (list): Example:
            [
                {"face": "face0", "port": 9010},
                {"face": "face1", "port": 9011}
            ]
        bind_ip (str): IP to bind (default: localhost)

    Returns:
        dict: { face: { "sock": socket, "face": face, "port": port } }
    """
    for interface in interfaces:
        face = interface["face"]
        port = interface["port"]

        sock = create_udp_socket(bind_addr=IP_ADDR, bind_port=port)

        INTERFACES[face] = {
            "sock": sock,
            "face": face,
            "port": port
        }

        log("INFO", f"Created socket for {face} on {IP_ADDR}:{port}")
    return INTERFACES


def send_packet(sock, addr, packet_bytes):
    """Send a packet to a specific address via UDP."""
    # log("DEBUG", f"Sending packet to {addr[0]}:{addr[1]}, Size: {len(packet_bytes)} bytes")
    sock.sendto(packet_bytes, addr)


def receive_packet(sock, buffer_size=4096):
    """Receive a packet (blocking)."""
    data, addr = sock.recvfrom(buffer_size)
    return data, addr






##################
# Parsing Module #
##################

def compute_checksum(data_bytes):
    """Simple checksum: sum of bytes modulo 256."""
    return sum(data_bytes) % 256


def parse_packet(packet_bytes):
    """Parse and validate a raw packet into structured fields."""
    # Minimum header = PREAMBLE + IDENTIFIER + LENs + CHECKSUM + POSTAMBLE
    if len(packet_bytes) < 6:
        return None, "Packet too short"

    # Verify preamble and postamble
    if not (packet_bytes.startswith(packetStruct.PREAMBLE) and 
            packet_bytes.endswith(packetStruct.POSTAMBLE)):
        return None, "Invalid delimiters"

    # Remove preamble and postamble
    core = packet_bytes[len(packetStruct.PREAMBLE):-len(packetStruct.POSTAMBLE)]

    # Check packet integrity through checksum
    checksum = core[-1]
    valid = compute_checksum(core[:-1]) == checksum
    if not valid:
        return None, "Checksum mismatch"
    
    # Extract identifier
    identifier = struct.unpack(packetStruct.IDENTIFIER_FORMAT, core[0:1])[0]

    # Decide packet type
    pkt_type = (identifier >> 4) & 0b11  # extract PP bits
    
    if pkt_type == packetStruct.PACKET_TYPE_INTEREST:
        name_len = struct.unpack(packetStruct.NAME_LENGTH_FORMAT, core[1:2])[0]
        name = core[2:2+name_len].decode()
        parsed = {"type": "interest", "name": name, "valid": valid}
        log("SUCCESS", f"Parsed interest packet '{name}'")
        return parsed, None

    elif pkt_type == packetStruct.PACKET_TYPE_DATA:
        name_len = struct.unpack(packetStruct.NAME_LENGTH_FORMAT, core[1:2])[0]
        data_len = struct.unpack(packetStruct.DATA_LENGTH_FORMAT, core[2:6])[0]

        start_idx = 6
        name = core[start_idx:start_idx+name_len].decode()
        data_field = core[start_idx+name_len:start_idx+name_len+data_len]

        # check if name has frag notation like /dlsu/goks/cam[1:10]
        frag_num, frag_total = None, None
        match = re.search(r"\[(\d+):(\d+)\]$", name)
        if match:
            frag_num, frag_total = int(match.group(1)), int(match.group(2))
            name = name[:match.start()]  # strip [x:y]

        parsed = {
            "type": "data",
            "name": name,
            "data": data_field,
            "frag_num": frag_num,
            "frag_total": frag_total,
            "valid": valid
        }
        if frag_total:
            frag_note = f"fragment {frag_num}/{frag_total}"
        else:
            frag_note = "unfragmented payload"
        log("SUCCESS", f"Parsed data packet '{name}' ({frag_note})")
        return parsed, None


    return None, "Unknown packet type"




#######################
# Metrics Calculation #
#######################

CSV_FILE = "results.csv"

def append_metrics_to_csv(metrics):
    file_exists = os.path.isfile(CSV_FILE)

    with open(CSV_FILE, mode="a", newline="") as f:
        writer = csv.writer(f)

        # write header only once
        if not file_exists:
            writer.writerow([
                "node",
                "name",
                "RTT_ms",
                "interest_receive_time",                
                "interest_sent_time",
                "interest_latency",
                "data_receive_time",
                "data_sent_time",
                "data_latency",
            ])

        writer.writerow([
            NODE_NAME,
            metrics["name"],
            f"{metrics['RTT']:.6f}",
            f"{metrics['interest_receive_time'] % 1000000}",
            f"{metrics['interest_sent_time'] % 1000000}",
            "",
            f"{metrics['data_receive_time'] % 1000000}",
            f"{metrics['data_sent_time'] % 1000000}",
            "",
        ])

        # reset to 0
        METRICS["interest_sent_time"] = 0
        METRICS["interest_receive_time"] = 0
        METRICS["data_sent_time"] = 0
        METRICS["data_receive_time"] = 0

# metrics
METRICS = {
    "interests_sent": 0,
    "interests_received": 0,

    "data_packets_received": 0, # total data packets received (including fragments)
    "data_packets_to_receive": 0, # total data packets expected to be received
    "data_packets_to_receive_buffer": {}, # buffer to track received packets for each name
    "data_packets_sent": 0,
    "data_total_sent": 0,
    "data_total_received": 0,

    "failed_packets": 0,

    "total_data_bytes_received": 0,
    "total_data_overhead_bytes_received": 0,

    "data_overhead_bytes_received_per_name": 0, 
    "data_bytes_received_per_name": 0, # data bytes per name
    
    "ave_RTT": 0.0,  # in milliseconds
    "PDR": 0.0, 
    "latency": 0.0,
    "throughput": 0.0,
    "goodput": 0.0,
    "test_start_time": 0.0,
    "test_end_time": 0.0,

    "interest_sent_time": 0,
    "interest_receive_time": 0,
    "data_sent_time": 0,
    "data_receive_time": 0
}

def update_metrics(metric_name, value=1):
    """ Update a specific metric counter."""
    if metric_name not in METRICS:
        log("WARN", f"Unknown metric '{metric_name}'")
        return
    METRICS[metric_name] += value

def get_metrics():
    """Retrieve current metrics."""
    # Calculate PDR
    if not FRAG_BUFFER:
        added_to_receive = sum(METRICS["data_packets_to_receive_buffer"].values()) 
        METRICS["data_packets_to_receive_buffer"] = {}  # reset buffer after calculating total
        update_metrics("data_packets_to_receive", added_to_receive)  # update total expected to receive

    if METRICS["data_packets_to_receive"] > 0:
        METRICS["PDR"] = (METRICS["data_total_received"] / METRICS["interests_sent"]) * 100.0
    return METRICS 



##################
# Storage Module #
##################
NODE_NAME = None
STORAGE_PATH = ""
INTEREST_LIFETIME = 360  # seconds

INTERFACES = {}  # port -> face, sock, port 

PIT = {}  # Pending Interest Table
PIT_LOCK = threading.Lock()
PIT_MAPPING = {}  # receiving_face -> addr of sender

CS = {}   # Content Store
CS_SIZE = 100  # max number of entries in CS

FIB = {}   # Forwarding Information Base
FACES = []  # List of faces

FUNCTIONS_TABLE = {}   # Functions Table
NODE_FUNCTIONS_MAPPING = {}

FRAG_BUFFER = {}

def store_interest(name, face, addr, funcs=None, waiting_for=None):
    """Store an Interest in the PIT."""
    PIT_MAPPING[face] = addr

    current_time = time.time()

    with PIT_LOCK:
        if name in PIT:
            # Interest aggregation: add new face to existing entry
            PIT[name]["interface"].add(face)

            # Update timestamp to the most recent Interest
            PIT[name]["time"] = current_time
            face_label = face if face is not None else "local"
            log("SUCCESS", f"Aggregated Interest '{name}' onto PIT via face '{face_label}'")
        else:
            PIT[name] = { 
                "interface": {face}, 
                "time": current_time,
                "funcs": funcs,
                "waiting_for": waiting_for,
            }
            log("SUCCESS", f"Stored Interest '{name}' in PIT")

def store_data(name, data):
    """Store data in the Content Store (CS)."""
    if len(CS) >= CS_SIZE:
        # Evict the oldest entry
        oldest_name = min(CS.keys(), key=lambda k: CS[k]["timestamp"])
        CS.pop(oldest_name)
        log("SUCCESS", f"Evicted '{oldest_name}' to maintain CS capacity")

    CS[name] = {"data": data, "timestamp": time.time()}
    log("SUCCESS", f"Cached '{name}' into CS (size: {len(CS)})")

def lookup_content(name):
    """Look up content in the Content Store (CS)."""
    entry = CS.get(name, None)
    if entry is not None:
        log("SUCCESS", f"CS hit for '{name}'")
    return entry

def update_CS_timestamp(name):
    """Update the timestamp of a CS entry to mark it as recently used."""
    if name in CS:
        CS[name]["timestamp"] = time.time()
        log("SUCCESS", f"Updated CS entry for '{name}'")

def initialize_content_store(storage_path):
    """Load existing content from storage into the Content Store (CS)."""
    global STORAGE_PATH
    STORAGE_PATH = storage_path

    if STORAGE_PATH != "" and not os.path.exists(STORAGE_PATH):
        os.makedirs(STORAGE_PATH)

    if STORAGE_PATH != "":
        for filename in os.listdir(STORAGE_PATH):
            full_path = os.path.join(STORAGE_PATH, filename)
            if os.path.isfile(full_path):
                content_name = "/" + filename.replace('_', '/')
                # Read file contents into memory
                with open(full_path, "rb") as f:
                    file_data = f.read()
                store_data(content_name, file_data)
                log("INFO", f"Cached '{content_name}' from storage ({len(file_data)} bytes)")


def clear_content_store():
    """Delete all entries in the Content Store (CS) and clear all stored files."""
    global STORAGE_PATH

    # Clear files on disk
    if STORAGE_PATH and NODE_NAME != "/dlsu/goks/cam" and os.path.exists(STORAGE_PATH):
        for filename in os.listdir(STORAGE_PATH):
            full_path = os.path.join(STORAGE_PATH, filename)
            if os.path.isfile(full_path):
                os.remove(full_path)

        log("SUCCESS", "Content store has been fully cleared.")



def lookup_fib(name: str):
    """
    Perform longest prefix matching on FIB
    
    Args:
        name: Full NDN name like "/dlsu/ccs/image1"
        
    Returns:
       Tuple of (face, port) for the best matching entry
    """
    if not name.startswith('/'):
        name = '/' + name
    
    # Find all matching prefixes
    interface_to_forward = None
    best_match_length = -1

    for prefix, entry in FIB.items():
        if entry["face"] == "face0":
            interface_to_forward = (entry["face"], entry["port"])
            
        # Check if name matches this prefix
        if name.startswith(prefix) or prefix == "/":  # "/" matches everything
            prefix_length = len(prefix)

            # Only keep entries with longest match
            if prefix_length > best_match_length:
                best_match_length = prefix_length
                interface_to_forward = (entry["face"], entry["port"])
    
    return interface_to_forward


def is_interest_expired(name):
    """Check if an Interest has expired."""
    if name not in PIT:
        return True
    
    elapsed = time.time() - PIT[name]["time"]
    remaining = INTEREST_LIFETIME - elapsed
    return max(0, remaining) <= 0

def cleanup_expired_pit_entries():
    """Remove PIT entries that have exceeded their lifetime."""
    current_time = time.time()
    expired_names = []

    with PIT_LOCK:
        for name, entry in PIT.items():
            age = current_time - entry["time"]
            
            if age > INTEREST_LIFETIME:
                expired_names.append(name)
                log("INFO", f"Interest '{name}' expired after {age:.2f}s")

        for name in expired_names:
            PIT.pop(name)
        
    return len(expired_names)

def get_PIT_entry(name):
    with PIT_LOCK:
        return PIT.get(name)



#####################
# Processing Module #
#####################

def process_interest(packet, addr, sock, SEND_QUEUE, interface):
    """Process Interest: check CS or forward."""
    name = packet["name"]
    update_metrics("interests_received")

    if METRICS["test_start_time"] == 0.0:
        METRICS["test_start_time"] = time.time()

    # First check Content Store
    cached_data = lookup_content(name)
    if cached_data:
        sent_time = datetime.now()
        METRICS["interest_receive_time"] = sent_time.timestamp() # for easier readability in CSV
        log(
            "DEBUG",
            f"Interest '{name}' received at {sent_time.strftime('%H:%M:%S.%f')}"  # HH:MM:SS.mmm
            # f"Interest '{name}' received at {sent_time.timestamp()}, serving from CS"
        )

        update_CS_timestamp(name)
        bytes = cached_data["data"]
        response = build_data_packet(name, bytes)
        update_metrics("data_total_sent") 
        SEND_QUEUE.put((sock, addr, response))
        log("INFO", f"Served '{name}' from CS to {addr}")


        sent_time = datetime.now()
        METRICS["data_sent_time"] = sent_time.timestamp()
        log(
            "DEBUG",
            # f"Data '{name}' sent at {sent_time.strftime('%H:%M:%S.%f')}"  # HH:MM:SS.mmm
            f"Data '{name}' sent at {sent_time.timestamp()} to {addr}"
        )

        append_metrics_to_csv({
            "name": f"{name}",
            "RTT": 0,
            "interest_sent_time": METRICS["interest_sent_time"], # make this float
            "interest_receive_time": METRICS["interest_receive_time"],
            "data_sent_time": METRICS["data_sent_time"],
            "data_receive_time": METRICS["data_receive_time"]
        })
        
        update_metrics("data_packets_sent", len(response))

        return 
    
    if name in PIT:
        log("INFO", f"Interest '{name}' already in PIT, aggregating")
        store_interest(name, interface, addr)
        return

    # If this Interest is meant for this node
    if NODE_NAME and (name == NODE_NAME or name.startswith(NODE_NAME + "/")):
        # /dlsu/goks/detect() -> detect()
        requested_name = name[len(NODE_NAME)+1:] if name != NODE_NAME else ""
        print(requested_name)
        # in-network function case
        if re.search(r"^[a-zA-Z_]+\(.*\)", requested_name):
            # the NFN is for this node
            base_name, funcs = parse_nfn_expression(requested_name)
            log("INFO", f"Parsed In-Network Function Interest: base_name='{base_name}', funcs={funcs}")

            if "recognize" in funcs:
                model, recognize = funcs # ['openface', 'recognize']
                log("INFO", f"Received In-Network Function Interest for recognition pipeline: '{name}'")
                func = FUNCTIONS_TABLE["orchestrate"]
                interest_expr = func(base_name, model, PIT, NODE_FUNCTIONS_MAPPING)
                log("INFO", f"Orchestrated Interest Expression: '{interest_expr}'")
                store_interest(name, interface, addr, [recognize], interest_expr)
                base_name = interest_expr
            else:
                # Store NFN interest in PIT
                store_interest(name, interface, addr, funcs, base_name)

            cached_data = lookup_content(base_name)
            if cached_data:
                update_CS_timestamp(base_name)
                bytes = cached_data["data"]
                response = build_data_packet(base_name, bytes)
                log("INFO", f"Cached content found for base name '{base_name}'")
                for resp in response:
                    parsed, _ = parse_packet(resp)
                    process_data(parsed, resp, sock, SEND_QUEUE)
                return

            # Forward Interest for base content (not recursive call)
            route = lookup_fib(base_name)
            log("INFO", f"Forwarding Interest for base content '{base_name}' via route: {route}")
            if route:
                forward_face, dest_port = route
                source_port = INTERFACES[forward_face]["port"]
                source_addr = ("127.0.0.1", source_port)
                process_interest({ "name" : base_name }, source_addr, INTERFACES[forward_face]["sock"], SEND_QUEUE, None)
                update_metrics("interests_sent")
            else:
                # Failed NFN Forwarding
                update_metrics("failed_packets")
            return


        # Forwarding case
        if name not in PIT:
            # query FIB
            node_to_find = NODE_NAME + "/" + requested_name.split("/")[0]

            # forward interest to satisfy it
            route = lookup_fib(node_to_find)

            if route:
                forward_face, dest_port = route
                dest_addr = ("127.0.0.1", dest_port)

                # Build Interest packet
                interest_packet = build_interest_packet(name)
                log("INFO", f"Forwarding Interest for '{name}' to {forward_face}")

                # store interest to PIT
                store_interest(name, interface, addr)
                # log("INFO", f"PIT: {PIT}")

                if METRICS["interest_sent_time"] == 0:
                    METRICS["interest_sent_time"] = datetime.now().timestamp()

                # send
                SEND_QUEUE.put((INTERFACES[forward_face]["sock"], dest_addr, [interest_packet]))
                update_metrics("interests_sent")
                return
            else:
                log("WARN", f"No route found for Interest '{name}', dropping")
                # Failed route lookup
                update_metrics("failed_packets")
                
    else:
        # Forwarding could go here 
        # Lets say name the node receiving is /dlsu/velasco and interest received is /dlsu/andrew/detect()
        # The node /dlsu/velasco would need to forward the interest to /dlsu/andrew

        # Find the next hop for the interest
        route = lookup_fib(name)
        if route:
            forward_face, dest_port = route
            dest_addr = ("127.0.0.1", dest_port)

            log("INFO", f"Forwarding Interest for '{name}' to {forward_face}")

            SEND_QUEUE.put((INTERFACES[forward_face]["sock"], dest_addr, [build_interest_packet(name)]))

            if METRICS["interest_sent_time"] == 0:
                METRICS["interest_sent_time"] = datetime.now().timestamp()
                log("DEBUG", f"Recorded interest_sent_time at {METRICS['interest_sent_time']} for '{name}'")

            store_interest(name, interface, addr)
            update_metrics("interests_sent")
        else:
            # drop the packet since no route found
            log("WARN", f"No route found for Interest '{name}', dropping")
            update_metrics("failed_packets")
        return  


def process_data(packet, raw_packet, sock, SEND_QUEUE):
    """Process Data Packet"""
    name = packet["name"]
    data = packet["data"]
    frag_num = packet.get("frag_num")
    frag_total = packet.get("frag_total")
    with PIT_LOCK:
        if name not in METRICS["data_packets_to_receive_buffer"]:
            METRICS["data_packets_to_receive_buffer"][name] = frag_total if frag_total else 1

        update_metrics("data_packets_received")
        update_metrics("total_data_bytes_received", len(data))
        update_metrics("total_data_overhead_bytes_received", len(raw_packet))
        update_metrics("data_overhead_bytes_received_per_name", len(raw_packet))
        update_metrics("data_bytes_received_per_name", len(data))


        # Find the relevant PIT entry
        pit_entry, original_name, waiting_for_name = find_pit_entry(name)

        if pit_entry is None:
            log("WARN", f"No PIT entry for {name}, dropping")
            update_metrics("failed_packets")
            return
        
        # Track if we should delete PIT entry at the end
        cleanup_flags = {
            "delete_pit": False,
            "delete_waiting_for": False
        }
        
        for face in pit_entry["interface"]:
            if should_process_locally(face, waiting_for_name):
                processed_data = handle_local_processing(
                    original_name, waiting_for_name, data,
                    frag_num, frag_total, pit_entry, 
                    SEND_QUEUE, cleanup_flags
                )     
            else: # Handle Packet Forwarding case
                # Fragmented data
                if frag_total:
                    if name not in FRAG_BUFFER:
                        FRAG_BUFFER[name] = {"frags": {}, "expected": frag_total}
                        log("SUCCESS", f"Initialized fragment buffer for '{name}' expecting {frag_total} parts")

                    if frag_num not in FRAG_BUFFER[name]["frags"]:
                        FRAG_BUFFER[name]["frags"][frag_num] = data
                        log("SUCCESS", f"Buffered fragment {frag_num}/{frag_total} for '{name}'")

                    # Forward the fragment
                    SEND_QUEUE.put((sock, PIT_MAPPING[face], [raw_packet]))
                    log("INFO", f"Forwarding fragment {frag_num}/{frag_total} for {name} to {PIT_MAPPING[face]}")
                    update_metrics("data_packets_sent")

                    processed_data = None

                    # Cache if all fragments received
                    if len(FRAG_BUFFER[name]["frags"]) == frag_total:
                        update_metrics("data_total_sent")
                        reassembled_data = reassemble_fragments(name, frag_total)
                        cleanup_flags["delete_pit"] = True            
                        processed_data = reassembled_data  # Return to be saved once

                # Non-fragmented data
                else:
                    SEND_QUEUE.put((sock, PIT_MAPPING[face], [raw_packet]))
                    log("INFO", f"Forwarding packet for {original_name} to {PIT_MAPPING[face]}")

                    cleanup_flags["delete_pit"] = True
                    processed_data = data
                    update_metrics("data_packets_sent")

        # Save data after all processing
        if processed_data is not None and cleanup_flags["delete_pit"]:
            save_data_to_file(original_name, processed_data)

            if "recognize" in original_name:
                log("SUCCESS", f"Recognition result for '{original_name.split('/')[-1].rstrip(')')}': {processed_data.decode()}")
            # log("INFO", f"Saved processed data for '{original_name}'")

        # Cleanup after all processing
        if cleanup_flags["delete_waiting_for"] and waiting_for_name in PIT:
            PIT.pop(waiting_for_name)

        if cleanup_flags["delete_pit"] and original_name in PIT:
            update_metrics("data_total_received")
            if original_name in FRAG_BUFFER:
                # cleanup buffer
                del FRAG_BUFFER[original_name] 

            # RTT
            pit_entry = PIT[original_name]
            rtt = time.time() - pit_entry["time"]
            if METRICS["ave_RTT"] == 0.0:
                METRICS["ave_RTT"] = rtt * 1000  # in ms
            METRICS["ave_RTT"] = (METRICS["ave_RTT"] + rtt * 1000) / 2
            rtt_ms = rtt * 1000
            log("DEBUG", f"RTT for '{original_name}': {rtt_ms:.4f}ms, Average RTT: {METRICS['ave_RTT']:.4f}ms")

            # Goodput
            data_kbytes = METRICS["data_bytes_received_per_name"] / 1024  # in KB
            overhead_data_kbytes = METRICS["data_overhead_bytes_received_per_name"] / 1024 # in KB
            log("INFO", f"Final Size of {original_name}: {data_kbytes:.2f} KB")
            log("INFO", f"Final Size with Overhead: {overhead_data_kbytes:.2f} KB")
            METRICS["data_overhead_bytes_received_per_name"] = 0  # reset for next
            METRICS["data_bytes_received_per_name"] = 0  # reset for next
            PIT.pop(original_name)
            log("INFO", f"Removed PIT entry for '{original_name}' after processing.")

            if not PIT:
                log("INFO", "PIT is now empty.")
                METRICS["test_end_time"] = time.time()
                elapsed_time = METRICS["test_end_time"] - METRICS["test_start_time"]
                log("DEBUG", f"Test completed in {time.strftime('%H:%M:%S', time.gmtime(elapsed_time))}")
                average_throughput = METRICS["total_data_overhead_bytes_received"] / 1024 / elapsed_time if elapsed_time > 0 else 0.0
                average_goodput = METRICS["total_data_bytes_received"] / 1024 / elapsed_time if elapsed_time > 0 else 0.0
                METRICS["throughput"] = average_throughput  # in KB/s
                METRICS["goodput"] = average_goodput  # in KB/s

            # if original_name in METRICS["data_packets_to_receive_buffer"]:
            #     update_metrics("data_packets_to_receive", METRICS["data_packets_to_receive_buffer"][original_name])
            #     del METRICS["data_packets_to_receive_buffer"][original_name]

            
            receive_time = datetime.now()
            METRICS["data_receive_time"] = receive_time.timestamp()

            append_metrics_to_csv({
                "name": original_name,
                "RTT": rtt_ms,
                "interest_sent_time": METRICS["interest_sent_time"], # make this float
                "interest_receive_time": METRICS["interest_receive_time"],
                "data_sent_time": METRICS["data_sent_time"],
                "data_receive_time": METRICS["data_receive_time"]
            })

            log(
                "DEBUG",
                f"Data '{name}' received at {receive_time.strftime('%H:%M:%S.%f')}"  # HH:MM:SS.mmm
            )

        return cleanup_flags["delete_pit"]


def find_pit_entry(name):
    """Find PIT entry for the given name or waiting_for relationship"""
    log("INFO", f"Searching PIT for data '{name}'")
    pit_entry = PIT[name] if name in PIT else None
    waiting_for_name = None
    original_name = name
    log("INFO", f"PIT entry found for {name}")
    # Direct match
    # if name in PIT:
    #     pit_entry = PIT[name]
    #     return pit_entry, original_name, waiting_for_name

    # Check if any entry is waiting for this data (NFN case)
    for entry_name, entry in list(PIT.items()):
        if entry.get("waiting_for") == name:
            pit_entry = entry
            waiting_for_name = name
            original_name = entry_name
            log("INFO", f"Data for '{waiting_for_name}' is awaited by Interest '{original_name}'")
            break

    return pit_entry, original_name, waiting_for_name


def should_process_locally(face, waiting_for_name):
    """Determine if data should be processed locally or forwarded"""
    return face is None or waiting_for_name is not None


def handle_local_processing(name, waiting_for_name, data, frag_num, frag_total, 
                            pit_entry, SEND_QUEUE, cleanup_flags):
    """Handle local data processing"""
    if frag_total:
        # Fragmented data
        return handle_fragmented_local_processing(
            name, waiting_for_name, data, frag_num, frag_total,
            pit_entry, SEND_QUEUE, cleanup_flags
        )
    else:
        log("INFO", f"Node requested the data - processing locally")

        # Non-fragmented data
        log("INFO", f"Received non-fragmented data for {name}")

        if waiting_for_name:
            return process_nfn_request(
                name, waiting_for_name, data,
                pit_entry, SEND_QUEUE, cleanup_flags
            )

        # no NFN
        cleanup_flags["delete_pit"] = True
        return data 


def handle_fragmented_local_processing(name, waiting_for_name, data, frag_num, 
                                       frag_total, pit_entry, SEND_QUEUE, cleanup_flags):
    """Handle fragmented data for local processing"""
    # Initialize fragment buffer
    log("INFO", f"Received fragment {frag_num}/{frag_total} for '{name}' during local processing")
    if name not in FRAG_BUFFER:
        FRAG_BUFFER[name] = {"frags": {}, "expected": frag_total}
        log("SUCCESS", f"Initialized fragment buffer for '{name}' expecting {frag_total} parts")

    FRAG_BUFFER[name]["frags"][frag_num] = data
    # log("SUCCESS", f"Buffered fragment {frag_num}/{frag_total} for '{name}'")

    # Check if all fragments received
    if len(FRAG_BUFFER[name]["frags"]) == frag_total:
        log("INFO", f"Node requested the data - processing locally")
        log("INFO", f"All fragments received for '{name}', reassembling fragments (total={frag_total})")
        full_data = reassemble_fragments(name, frag_total)

        # Save original data if this is an NFN request
        if waiting_for_name:
            return process_nfn_request(
                name, waiting_for_name, full_data,
                pit_entry, SEND_QUEUE, cleanup_flags
            )
        else:
            # Regular fragmented data (no NFN)
            cleanup_flags["delete_pit"] = True
            return full_data 
    
    return None  # Not all fragments received yet


# Reassemble fragments
def reassemble_fragments(name, frag_total):
    """Reassemble fragments for a given name."""
    full_data = b"".join(FRAG_BUFFER[name]["frags"][i] for i in range(1, frag_total+1))
    # log("INFO", f"Reassembling fragments for '{name}', total={frag_total}")
    log("INFO", f"Fragment assembly complete for '{name}', final_size={len(full_data)} bytes")
    return full_data


def save_data_to_file(name, data_bytes):
    """Save data bytes to a file and store in CS."""
    log("INFO", f"Saving processed output for '{name}' to CS")
    if "recognize" in name:
        filename = os.path.join(STORAGE_PATH, name[1:].replace('/', '_')) + ".txt"
    elif "embedding" in name:
        filename = os.path.join(STORAGE_PATH, name[1:].replace('/', '_')) + ".npy"
    else:
        filename = os.path.join(STORAGE_PATH, name[1:].replace('/', '_')) + ".jpg"

    if name not in CS:
        store_data(name, data_bytes)
    else:
        update_CS_timestamp(name)

    with open(filename, "wb") as f:
        f.write(data_bytes)
    log("SUCCESS", f"Data written to {filename}")


def parse_nfn_expression(expr: str):
    """
    Parse NFN expression like:
        grayscale(resize(detect(/dlsu/goks/cam/img1)))
    
    Returns:
        (base_name, [functions_in_order])
    """
    # Base case: if it starts with "/", it's just a content name
    if expr.startswith("/"):
        return expr, []

    # Match function pattern: func(arg)
    match = re.match(r"(\w+)\((.+)\)", expr)
    if not match:
        raise ValueError(f"Invalid In-Network Function expression: {expr}")

    func, arg = match.groups()
    base_name, funcs = parse_nfn_expression(arg)  # recurse inside
    # log("INFO", f"Parsing In-Network Function expression: {expr}")
    # log("INFO", f"In-Network Function parse result: base='{base_name}', funcs = {funcs}")
    return base_name, funcs + [func]


def process_nfn_request(name, waiting_for_name, full_data, pit_entry, 
                       SEND_QUEUE, cleanup_flags):
    """Process Named Function Networking request"""
    log("INFO", f"Starting In-Network Function processing for '{name}', waiting_for = '{waiting_for_name}'")
    log("INFO", f"Assembling workflow: funcs={pit_entry.get('funcs', [])}")
    # Save the original data
    if lookup_content(waiting_for_name) is None and waiting_for_name not in CS:
        save_data_to_file(waiting_for_name, full_data)
    cleanup_flags["delete_waiting_for"] = True

    # Apply functions in the pipeline
    processed_data = apply_function_pipeline(name, full_data, pit_entry)
    log("INFO", f"In-Network Function pipeline complete for '{name}', size={len(processed_data)} bytes")
    # log("INFO", f"Building final In-Network Function Data packet for '{name}'")

    # Send processed results back
    response = build_data_packet(name, processed_data)

    for forward_face in pit_entry["interface"]:
        if forward_face is not None and forward_face in INTERFACES:
            SEND_QUEUE.put((
                INTERFACES[forward_face]["sock"],
                PIT_MAPPING.get(forward_face),
                response
            ))
    
    update_metrics("data_packets_sent", len(response))
    log("INFO", f"Processed In-Network Function '{name}' and sent to {pit_entry['interface']}")

    cleanup_flags["delete_pit"] = True
    return processed_data


def apply_function_pipeline(name, data, pit_entry):
    """Apply all functions in the NFN pipeline"""
    processed_data = data
    log("INFO", f"Initializing ML pipeline for '{name}', stages={pit_entry.get('funcs', [])}")
    log("INFO", f"Initial payload size: {len(data)} bytes")
    for func_name in pit_entry.get("funcs", []):
        log("INFO", f"Applying function: {func_name}")

        if func_name not in FUNCTIONS_TABLE:
            log("ERROR", f"Function '{func_name}' not found in FUNCTIONS_TABLE")
            continue

        try:
            func = FUNCTIONS_TABLE[func_name]
            log("INFO", f"ML stage start: '{func_name}' on '{name}', "
            f"input={len(processed_data)} bytes")
            processed_data = func(processed_data)
            log("INFO", f"Function '{func_name}' completed successfully")
        except Exception as e:
            log("ERROR", f"Function '{func_name}' failed: {e}")
            import traceback
            traceback.print_exc()
            # Continue with unprocessed data

    return processed_data



###################
# Packet Builders #
###################

def build_interest_packet(name):
    name_bytes = name.encode()
    identifier = (packetStruct.PROTOCOL_VERSION << 6) | (packetStruct.PACKET_TYPE_INTEREST << 4)
    header = struct.pack(packetStruct.IDENTIFIER_FORMAT, identifier)
    header += struct.pack(packetStruct.NAME_LENGTH_FORMAT, len(name_bytes))
    core = header + name_bytes
    checksum = compute_checksum(core).to_bytes(1, 'big')
    packet = packetStruct.PREAMBLE + core + checksum + packetStruct.POSTAMBLE
    log("SUCCESS", f"Built interest packet for '{name}'")
    return packet


def build_data_packet(name, data):
    # name_bytes = name.encode()
    data_bytes = data

    packets = []
    fragments = fragment_data(data_bytes)  

    total_frags = len(fragments)
    for idx, frag in enumerate(fragments, start=1):
        # only add [x:y] if more than one fragment
        if total_frags > 1:
            frag_name = f"{name}[{idx}:{total_frags}]".encode()
        else:
            frag_name = name.encode()

        identifier = (packetStruct.PROTOCOL_VERSION << 6) | (packetStruct.PACKET_TYPE_DATA << 4)
        header = struct.pack(packetStruct.IDENTIFIER_FORMAT, identifier)

        header += struct.pack(packetStruct.NAME_LENGTH_FORMAT, len(frag_name))
        header += struct.pack(packetStruct.DATA_LENGTH_FORMAT, len(frag))

        core = header + frag_name + frag
        checksum = compute_checksum(core).to_bytes(1, 'big')

        packet = packetStruct.PREAMBLE + core + checksum + packetStruct.POSTAMBLE
        packets.append(packet)
        log("SUCCESS", f"Built data packet for '{name}' fragment {idx}/{total_frags}")

    return packets


def fragment_data(data_bytes, max_payload=4000):
    """
    Splits data into fragments if > max_payload.
    Returns a list of fragments
    """
    return [data_bytes[i:i+max_payload] for i in range(0, len(data_bytes), max_payload)]