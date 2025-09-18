import socket
import struct
import Packet_Structure as packetStruct
import random
import re
import os
import time

#########################
# Communication Module  #
#########################

def create_udp_socket(bind_addr="127.0.0.1", bind_port=9000):
    """Create and bind a UDP socket for communication."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((bind_addr, bind_port))
    return sock


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
NODE_ADDR = None
STORAGE_PATH = ""
INTEREST_LIFETIME = 5  # seconds

PIT = {}  # Pending Interest Table
CS = {}   # Content Store
FIB = {}   # Forwarding Information Base 
FUNCTIONS_TABLE = {}   # Functions Table
FRAG_BUFFER = {}

def store_interest(name, addr, funcs=None, waiting_for=None):
    if name in PIT:
        PIT[name]["addr"].add(addr)
    else:
        PIT[name] = { 
            "addr": {addr}, 
            "time": time.time(),
            "funcs": funcs,
            "waiting_for": waiting_for,
        }

def store_data(name, data):
    CS[name] = data

def lookup_content(name):
    return CS.get(name, None)


#####################
# Processing Module #
#####################

def process_interest(packet, addr, sock):
    """Process Interest: check CS or forward."""
    name = packet["name"]

    # First check Content Store
    cached_data = lookup_content(name)
    if cached_data:
        response = build_data_packet(name, cached_data["data"])
        for resp in response:
            send_packet(sock, addr, resp)
        return

    # If this Interest is meant for this node
    if name.startswith(NODE_NAME):
        # /dlsu/goks/detect() -> detect()
        requested_name = name[len(NODE_NAME)+1:]
        
        # NFN case
        if re.search(r"[a-zA-Z]+\(.*\)", requested_name):
            # the NFN is for this node
            base_name, funcs = parse_nfn_expression(requested_name)

            # Store NFN interest in PIT
            store_interest(name, addr, funcs, base_name)

            process_interest({ "name" : base_name }, NODE_ADDR, sock)
            return

        # Local content request
        if not "/" in requested_name:
            # no further hierarchy -> can process the interest 
            # get the requested name
            bytes = process_name_request(requested_name)
            response = build_data_packet(name, bytes)
            for resp in response:
                send_packet(sock, addr, resp)
                time.sleep(0.001)  # slight delay to avoid UDP packet loss
            return

        # Forwarding case
        if name not in PIT:
            # query FIB
            node_to_find = NODE_NAME + "/" + requested_name.split("/")[0]

            # forward interest to satisfy it
            port = FIB[node_to_find]

            # Build Interest packet
            interest_packet = build_interest_packet(name)
            print(f"\n[DEBUG] Raw Interest Packet: {interest_packet}")
            print(f"[DEBUG] Packet Size: {len(interest_packet)} bytes")

            print(f"[Client] Sending Interest for '{name}'")
            send_packet(sock, ("127.0.0.1", port), interest_packet)
        
        # store interest to PIT
        store_interest(name, addr)
        print(f"\n\n{PIT}")
    else:
        store_interest(name, addr)
        # Forwarding could go here (not implemented yet)


def process_data(packet, raw_packet, sock):
    """Process Data Packet"""
    name = packet["name"]
    data = packet["data"]

    frag_num = packet.get("frag_num")
    frag_total = packet.get("frag_total")

    if name not in PIT:
        print(f"[WARN] No PIT entry for {name}, dropping")
        return
    
    pit_entry = PIT[name]
    
    for addr in pit_entry["addr"]:
        # Check if this node requested the data
        if addr == NODE_ADDR: 
            # if node did request -> handle reassembly (if fragmented) -> process
            if frag_total:  # fragmented packet
                if name not in FRAG_BUFFER:
                    FRAG_BUFFER[name] = {"frags": {}, "expected": None}

                FRAG_BUFFER[name]["frags"][frag_num] = data

                if len(FRAG_BUFFER[name]["frags"]) == frag_total:
                    # Reassemble
                    full_data = b"".join(FRAG_BUFFER[name]["frags"][i] for i in range(1, frag_total+1))

                    # print(full_data)
                    # print(FRAG_BUFFER[name]["frags"].keys())
                    
                    # how would i know that this name will be used for another request
                    if name in PIT:
                        # for now it will be inefficient, needs optimization
                        for pit_name, entry in list(PIT.items()):
                            if entry["waiting_for"] == name:
                                for func_name in entry["funcs"]:
                                    func = FUNCTIONS_TABLE[func_name]
                                    full_data = func(full_data)

                                response = build_data_packet(pit_name, full_data)
                                for resp in response:
                                    for forward_addr in entry["addr"]:
                                        send_packet(sock, forward_addr, resp)
                                        time.sleep(0.001)  # slight delay to avoid UDP packet loss
                        # PIT.pop(name)

                    # save to file
                    filename = name[1:].replace('/', '_')
                    with open(filename, "wb") as f:
                        f.write(full_data)
                    print(f"[INFO] Reassembled image written to {filename}")

                    # cleanup buffer
                    del FRAG_BUFFER[name]

            else:  
                # Non-fragmented packet, node did request -> process
                requester = PIT.pop(name)

        # === Forwarding case ===
        # This node didn’t request → just forward (fragment untouched)
        else:
            print(f"[Forwarding to {addr}] Packet for {name}, not requested here")
        
            # send 
            send_packet(sock, addr, raw_packet)
    
        # store_data(name, full_data.decode()) # i think need to reassemble for caching or no?
        if frag_total:
            if name not in FRAG_BUFFER:
                FRAG_BUFFER[name] = {"frags": {}, "expected": None}

            if frag_num not in FRAG_BUFFER[name]["frags"]:
                FRAG_BUFFER[name]["frags"][frag_num] = 1

            if frag_total == len(FRAG_BUFFER[name]["frags"]):
                PIT.pop(name)
                del FRAG_BUFFER[name]
        else:
            PIT.pop(name)


def process_name_request(name) -> bytes:
    # use STORAGE_PATH to get to the dir storage and get the requested name
    full_path = os.path.join(STORAGE_PATH, name)

    # Read file contents as raw bytes
    with open(full_path, "rb") as f:
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
