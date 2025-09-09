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

    # Extract identifier
    identifier = struct.unpack(packetStruct.IDENTIFIER_FORMAT, core[0:1])[0]

    # Decide packet type
    pkt_type = (identifier >> 4) & 0b11  # extract PP bits

    if pkt_type == packetStruct.PACKET_TYPE_INTEREST:
        name_len = struct.unpack(packetStruct.NAME_LENGTH_FORMAT, core[1:2])[0]
        name = core[2:2+name_len].decode()

        checksum = core[-1]
        valid = compute_checksum(core[:-1]) == checksum

        return {"type": "interest", "name": name, "valid": valid}, None

    elif pkt_type == packetStruct.PACKET_TYPE_DATA:
        name_len = struct.unpack(packetStruct.NAME_LENGTH_FORMAT, core[1:2])[0]
        data_len = struct.unpack(packetStruct.DATA_LENGTH_FORMAT, core[2:6])[0]

        frag_field = struct.unpack(packetStruct.FRAGMENTATION_FORMAT, core[6:8])[0]
        frag_flag = (frag_field >> 15) & 0b1
        frag_id   = (frag_field >> 8) & 0x7F
        offset    = frag_field & 0xFF

        start_idx = 8
        name = core[start_idx:start_idx+name_len].decode()
        data_field = core[start_idx+name_len:start_idx+name_len+data_len]

        checksum = core[-1]
        valid = compute_checksum(core[:-1]) == checksum
        return {
            "type": "data",
            "name": name,
            "data": data_field,
            "frag_flag": frag_flag,
            "frag_id": frag_id,
            "offset": offset,
            "valid": valid
        }, None


    return None, "Unknown packet type"



##################
# Storage Module #
##################
NODE_NAME = None
STORAGE_PATH = ""
INTEREST_LIFETIME = 5  # seconds


PIT = {}  # Pending Interest Table

# Content Store
CS = {}   
FIB = {}   # Forwarding Information Base 
FT = {}   # Functions Table
FRAG_BUFFER = {}

def store_interest(name, addr):
    if name in PIT:
        PIT[name]["addr"].add(addr)
    else:
        PIT[name] = { 
            "addr": {addr}, 
            "time": time.time() 
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
    cached_data = lookup_content(name)
    if cached_data:
        response = build_data_packet(name, cached_data["data"])
        for resp in response:
            send_packet(sock, addr, resp)
    elif name.startswith(NODE_NAME):
        requested_name = name.replace(NODE_NAME, "")[1:]

        if re.search(r"\(.?\)", name):
            # this is an NFN
            return
        elif not "/" in requested_name:
            # no further hierarchy -> can process the interest 
            # get the requested name
            bytes = process_name_request(requested_name)
            response = build_data_packet(name, bytes)
            for resp in response:
                send_packet(sock, addr, resp)
        else:
            if name in PIT:
                # store interest to PIT
                store_interest(name, addr)
                print(PIT)
            else:
                store_interest(name, addr)
                print(f"\n\n{PIT}")
                
                # query FIB
                node_to_find = NODE_NAME + "/" + requested_name.split("/")[0]

                # forward interest to satisfy it
                port = FIB[node_to_find]

                # Build Interest packet
                interest_packet = build_interest_packet(name)
                print(f"\n[DEBUG] Raw Interest Packet: {interest_packet}")
                print(f"[DEBUG] Packet Size: {len(interest_packet)} bytes")

                print(f"[Client] Sending Interest for '{name}'")
                sock.sendto(interest_packet, ("127.0.0.1", port))
    else:
        store_interest(name, addr)
        # Forwarding could go here (not implemented yet)


def process_data(packet, raw_packet, sock):
    """Process Data Packet"""
    name = packet["name"]
    frag_id = packet.get("frag_id")
    offset = packet.get("offset")
    more_frags = packet.get("frag_flag", 0)

    data = packet["data"]
    expected_size = 0
    received_data_size = 0

    # Check if this node requested the data
    if name in PIT:
        # This node didn’t request → just forward (fragment untouched)
        for addr in PIT[name]["addr"]:
            print(f"[Forwarding to {addr}] Packet for {name}, not requested here")
            
            # send 
            send_packet(sock, addr, raw_packet)
        
        # store_data(name, full_data.decode()) # i think need to reassemble for caching or no?
        if frag_id != 0:
            if more_frags == 0:
                expected_size = offset * 4000 + len(data)
            else:
                received_data_size += len(data)

            if expected_size is not None and received_data_size == expected_size:
                PIT.pop(name)
        else:
            PIT.pop(name)

    # else if node did request -> handle reassembly (if fragmented) -> process
    elif frag_id != 0:  # fragmented packet
        if frag_id not in FRAG_BUFFER:
            FRAG_BUFFER[frag_id] = {"name": name, "frags": {}, "expected": None}

        FRAG_BUFFER[frag_id]["frags"][offset] = data

        if more_frags == 0:
            FRAG_BUFFER[frag_id]["expected"] = offset * 4000 + len(data)

        total_len = FRAG_BUFFER[frag_id]["expected"]
        if total_len is not None:
            received = sum(len(v) for v in FRAG_BUFFER[frag_id]["frags"].values())
            if received == total_len:
                # Reassemble
                ordered_offsets = sorted(FRAG_BUFFER[frag_id]["frags"].keys())
                full_data = b"".join(FRAG_BUFFER[frag_id]["frags"][o] for o in ordered_offsets)

                print(full_data)

                # save to file
                filename = f"{FRAG_BUFFER[frag_id]['name'][1:].replace('/', '_')}"
                with open(filename, "wb") as f:
                    f.write(full_data)
                print(f"[INFO] Reassembled image written to {filename}")

                # cleanup buffer
                del FRAG_BUFFER[frag_id]

    else:  
        # Non-fragmented packet, node did request -> process
        requester = PIT.pop(name)


def process_name_request(name) -> bytes:
    # use STORAGE_PATH to get to the dir storage and get the requested name
    full_path = os.path.join(STORAGE_PATH, name)

    # Read file contents as raw bytes
    with open(full_path, "rb") as f:
        file_bytes = f.read()

    return file_bytes


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
    name_bytes = name.encode()
    data_bytes = data

    packets = []
    fragments = fragment_data(data_bytes)  

    for frag in fragments:
        # Identifier field
        identifier = (packetStruct.PROTOCOL_VERSION << 6) | (packetStruct.PACKET_TYPE_DATA << 4)
        header = struct.pack(packetStruct.IDENTIFIER_FORMAT, identifier)

        # Name length + data length
        header += struct.pack(packetStruct.NAME_LENGTH_FORMAT, len(name_bytes))
        header += struct.pack(packetStruct.DATA_LENGTH_FORMAT, len(frag["chunk"]))

        # Fragmentation field: (F << 15) | (FragID << 8) | Offset
        frag_field = ((frag["frag_flag"] & 0b1) << 15) | ((frag["frag_id"] & 0x7F) << 8) | (frag["offset"] & 0xFF)
        header += struct.pack(packetStruct.FRAGMENTATION_FORMAT, frag_field)

        # Core packet
        core = header + name_bytes + frag["chunk"]

        # Add checksum
        checksum = compute_checksum(core).to_bytes(1, 'big')

        packet = packetStruct.PREAMBLE + core + checksum + packetStruct.POSTAMBLE
        packets.append(packet)

    return packets


def fragment_data(data_bytes, max_payload=4000):
    """
    Splits data into fragments if > max_payload.
    Returns a list of (frag_flag, frag_id, offset, chunk).
    """
    total_len = len(data_bytes)

    if total_len > max_payload:
        frag_id = random.randint(1, 0x7F)  # random FragID
    else: 
        frag_id = 0

    fragments = []
    offset = 0
    chunk_index = 0

    while offset < total_len:
        chunk = data_bytes[offset:offset + max_payload]
        frag_flag = 1 if (offset + max_payload) < total_len else 0  # 1=more, 0=last

        fragments.append({
            "frag_flag": frag_flag,
            "frag_id": frag_id,
            "offset": chunk_index,
            "chunk": chunk
        })

        offset += max_payload
        chunk_index += 1

    return fragments
