import socket
import struct
import Packet_Structure as packetStruct
import random
import re
import os
import time
import threading

LOGS = []

def log(level, message, path=""):
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    entry = {"level": level, "message": message, "path": path, "timestamp": timestamp}
    LOGS.append(entry)
    print(f"\n[{timestamp}] [{level}] {message}" + (f" {path}" if path else ""))



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

        sock = create_udp_socket(bind_port=port)

        INTERFACES[face] = {
            "sock": sock,
            "face": face,
            "port": port
        }

        log("INFO", f"Created socket for {face} on {IP_ADDR}:{port}")

    return INTERFACES


def send_packet(sock, addr, packet_bytes):
    """Send a packet to a specific address via UDP."""
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

        return {"type": "interest", "name": name, "valid": valid}, None

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

        return {
            "type": "data",
            "name": name,
            "data": data_field,
            "frag_num": frag_num,
            "frag_total": frag_total,
            "valid": valid
        }, None


    return None, "Unknown packet type"







##################
# Storage Module #
##################
NODE_NAME = None
STORAGE_PATH = ""
INTEREST_LIFETIME = 30  # seconds

INTERFACES = {}  # port -> face, sock, port 

PIT = {}  # Pending Interest Table
PIT_LOCK = threading.Lock()
PIT_MAPPING = {}  # receiving_face -> addr of sender

CS = {}   # Content Store
CS_SIZE = 100  # max number of entries in CS

FIB = {}   # Forwarding Information Base
FACES = []  # List of faces
FUNCTIONS_TABLE = {}   # Functions Table
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
        else:
            PIT[name] = { 
                "interface": {face}, 
                "time": current_time,
                "funcs": funcs,
                "waiting_for": waiting_for,
            }

def store_data(name, path):
    if len(CS) >= CS_SIZE:
        # Evict the oldest entry
        oldest_name = min(CS.keys(), key=lambda k: CS[k]["timestamp"])
        CS.pop(oldest_name)

    CS[name] = {"path": path, "timestamp": time.time()}

def lookup_content(name):
    return CS.get(name, None)

def initialiaze_content_store(storage_path):
    global STORAGE_PATH
    STORAGE_PATH = storage_path

    if STORAGE_PATH != "" and not os.path.exists(STORAGE_PATH):
        os.makedirs(STORAGE_PATH)

    if STORAGE_PATH != "":
        for filename in os.listdir(STORAGE_PATH):
            full_path = os.path.join(STORAGE_PATH, filename)
            if os.path.isfile(full_path):
                content_name = "/" + filename.replace('_', '/')[:-4]  # remove .ext
                store_data(content_name, full_path)
                log("INFO", f"Cached '{content_name}' from storage")

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
                print(f"[PIT Timeout] Interest '{name}' expired after {age:.2f}s")

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

    # First check Content Store
    cached_data = lookup_content(name)
    if cached_data:
        bytes = process_name_request(cached_data["path"])
        response = build_data_packet(name, bytes)

        SEND_QUEUE.put((sock, addr, response))
        log("INFO", f"Served '{name}' from CS to {addr}")
        return 

    # If this Interest is meant for this node
    if name.startswith(NODE_NAME):
        # /dlsu/goks/detect() -> detect()
        requested_name = name[len(NODE_NAME)+1:]
        
        # NFN case
        if re.search(r"^[a-zA-Z]+\(.*\)", requested_name):
            # the NFN is for this node
            base_name, funcs = parse_nfn_expression(requested_name)

            # Store NFN interest in PIT
            store_interest(name, interface, addr, funcs, base_name)
            log("INFO", f"\n\nthis\n{PIT}\n\n")

            cached_data = lookup_content(base_name)
            if cached_data:
                bytes = process_name_request(cached_data["path"])
                response = build_data_packet(base_name, bytes)
                log("INFO", f"Cached content found for base name '{base_name}'")
                for resp in response:
                    parsed, _ = parse_packet(resp)
                    process_data(parsed, resp, sock, SEND_QUEUE)
                return

            # Forward Interest for base content (not recursive call)
            route = lookup_fib(base_name)
            if route:
                forward_face, dest_port = route
                source_port = INTERFACES[forward_face]["port"]
                source_addr = ("127.0.0.1", source_port)
                process_interest({ "name" : base_name }, source_addr, INTERFACES[forward_face]["sock"], SEND_QUEUE, None)
            return


        # Forwarding case
        if name not in PIT:
            # query FIB
            node_to_find = NODE_NAME + "/" + requested_name.split("/")[0]

            # forward interest to satisfy it
            route = lookup_fib(node_to_find)

            if route:
                forward_face, dest_port = route
                source_port = INTERFACES[forward_face]["port"]
                dest_addr = ("127.0.0.1", dest_port)

                # Build Interest packet
                interest_packet = build_interest_packet(name)
                print(f"\n[DEBUG] Raw Interest Packet: {interest_packet}")
                print(f"[DEBUG] Packet Size: {len(interest_packet)} bytes")

                # store interest to PIT
                store_interest(name, interface, addr)
                print(f"\n\n{PIT}")

                # send
                log("INFO", f"Sending Interest for '{name}'")
                SEND_QUEUE.put((INTERFACES[forward_face]["sock"], dest_addr, [interest_packet]))
                return
    else:
        store_interest(name, interface, addr)
        # Forwarding could go here (not implemented yet)


def process_data(packet, raw_packet, sock, SEND_QUEUE):
    """Process Data Packet"""
    name = packet["name"]
    data = packet["data"]

    frag_num = packet.get("frag_num")
    frag_total = packet.get("frag_total")


    pit_entry = None
    waiting_for_name = None
    if name in PIT:
        pit_entry = PIT[name]
    else:
        # find the entry that is waiting for this data
        for entry_name, entry in PIT.items():
            if entry["waiting_for"] == name:
                pit_entry = entry
                waiting_for_name = name
                name = entry_name  # use the NFN name for forwarding
                break
        if pit_entry is None:
            log("WARN", f"No PIT entry for {name}, dropping")
            return
    
    # Track if we should delete PIT entry at the end
    should_delete_pit = False
    
    for face in pit_entry["interface"]:
        # Check if this node requested the data
        if face == None or waiting_for_name: 
            # if node did request -> handle reassembly (if fragmented) -> process
            if frag_total:  # fragmented packet
                # Thread-safe fragment buffer access
                if name not in FRAG_BUFFER:
                    FRAG_BUFFER[name] = {"frags": {}, "expected": None}

                FRAG_BUFFER[name]["frags"][frag_num] = data

                if len(FRAG_BUFFER[name]["frags"]) == frag_total:
                    # Reassemble
                    full_data = reassemble_fragments(name, frag_total)

                    # how would i know that this name will be used for another request
                    # for now it will be inefficient, needs optimization
                    if waiting_for_name:
                        entry = get_PIT_entry(name)
                        for func_name in entry["funcs"]:
                            log("INFO", f"Applying function: {func_name}")

                            if func_name not in FUNCTIONS_TABLE:
                                log("ERROR", f"Function '{func_name}' not found in FUNCTIONS_TABLE")
                                continue

                            func = FUNCTIONS_TABLE[func_name]
                            full_data = func(full_data)

                        response = build_data_packet(name, full_data)
                        for forward_face in entry["interface"]:
                            SEND_QUEUE.put((
                                INTERFACES[forward_face]["sock"], 
                                PIT_MAPPING[forward_face], 
                                response
                            ))

                        log("INFO", f"Processed NFN '{name}' and sent to {entry['interface']}")
                        save_data_to_file(name, full_data)
                        should_delete_pit = True
                        continue

        # === Forwarding case ===
        # This node didn’t request → just forward (fragment untouched)
        else:
            # send
            SEND_QUEUE.put((sock, PIT_MAPPING[face], [raw_packet]))
            log("INFO", f"Forwarding packet for {name} to {PIT_MAPPING[face]}")
    
        # store_data(name, full_data.decode()) # i think need to reassemble for caching or no?
        if frag_total:
            if name not in FRAG_BUFFER:
                FRAG_BUFFER[name] = {"frags": {}, "expected": None}

            if frag_num not in FRAG_BUFFER[name]["frags"]:
                FRAG_BUFFER[name]["frags"][frag_num] = data

            if frag_total == len(FRAG_BUFFER[name]["frags"]):
                reassembled_data = reassemble_fragments(name, frag_total)
                save_data_to_file(name, reassembled_data)

                should_delete_pit = True
        else:
            should_delete_pit = True

    # Clean up PIT entry after processing ALL faces
    if should_delete_pit and name in PIT:
        # cleanup buffer
        del FRAG_BUFFER[name] 

        PIT.pop(name)
        log("INFO", f"Removed PIT entry for '{name}' after processing.")

    return should_delete_pit


# Reassemble fragments
def reassemble_fragments(name, frag_total):
    full_data = b"".join(FRAG_BUFFER[name]["frags"][i] for i in range(1, frag_total+1))
    log("INFO", f"Reassembled data for '{name}'")
    return full_data


def save_data_to_file(name, data_bytes):
    filename = os.path.join(STORAGE_PATH, name[1:].replace('/', '_')) + ".jpg"
    with open(filename, "wb") as f:
        f.write(data_bytes)
    log("INFO", f"Data written to {filename}")


def process_name_request(name) -> bytes:
    # Read file contents as raw bytes
    with open(name, "rb") as f:
        file_bytes = f.read()

    return file_bytes


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
        raise ValueError(f"Invalid NFN expression: {expr}")

    func, arg = match.groups()
    base_name, funcs = parse_nfn_expression(arg)  # recurse inside
    return base_name, funcs + [func]


# def process_node_function(name):
    # if re.search(r"\(.?\)", name):
        # 




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
    return packetStruct.PREAMBLE + core + checksum + packetStruct.POSTAMBLE


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

    return packets


def fragment_data(data_bytes, max_payload=4000):
    """
    Splits data into fragments if > max_payload.
    Returns a list of fragments
    """
    return [data_bytes[i:i+max_payload] for i in range(0, len(data_bytes), max_payload)]
