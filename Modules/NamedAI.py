import struct
import Packet_Structure as packetStruct
import random
import re
import os
import time
import threading
import serial
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
# IP_ADDR = "127.0.0.1"
BAUD_RATE = 115200
XBEE_PORT = None
SERIAL_LOCK = threading.Lock()
SENDING = threading.Event()

def create_serial_connection():
    ser = serial.Serial(XBEE_PORT, BAUD_RATE, timeout=0, rtscts=True)
    time.sleep(1)  # XBee warmup
    return ser

def create_interface(interfaces):
    """
    Given an interfaces list from the config, create UDP sockets for each face.

    Args:
        interfaces (list): Example:
            [
                {"face": "face0", "port": 9010, "dst_port": 9000},
                {"face": "face1", "port": 9011, "dst_port": 9020}
            ]
        bind_ip (str): IP to bind (default: localhost)

    Returns:
        dict: { face: { "sock": socket, "face": face, "port": port, "dst_port": dst_port } }
    """
    ser = create_serial_connection()
    
    for interface in interfaces:
        face = interface["face"]
        port = interface["port"] 
        dst_port = interface["dst_port"] 

        INTERFACES[face] = {
            "sock": ser,          # keep key name 'sock' so rest of code works
            "face": face,
            "port": port,
            "dst_port": dst_port
        }

        log("INFO", f"Opened XBee interface {face} on {port}")

    return INTERFACES


def send_packet(sock, addr, packet_bytes):
    """Send packet via XBee serial (addr unused but kept for compatibility)."""
    try:
        SENDING.set()
        with SERIAL_LOCK:
            sock.write(packet_bytes)  
            sock.flush()
        SENDING.clear()
        log("DEBUG", f"Sent {len(packet_bytes)} bytes over XBee")
    except Exception as e:
        log("ERROR", f"XBee send failed: {e}")

def receive_packet(sock, buf: list):
    """
    Receive raw bytes, buffer them, and return the next complete packet or None.
    buf is a single-element list [b""] used as a mutable reference.
    """
    try:
        if SENDING.is_set():
            time.sleep(0.001)
            return None
        
        with SERIAL_LOCK:
            buf[0] +=  sock.read(1024)  # read available bytes (non-blocking due to timeout=0)

        # Discard anything before the first preamble
        start = buf[0].find(packetStruct.PREAMBLE)
        if start == -1:
            buf[0] = b""
            return None
        if start > 0:
            # print(buf[0])
            buf[0] = buf[0][start:]

        # Return the first complete packet if one exists
        end = buf[0].find(packetStruct.POSTAMBLE, len(packetStruct.PREAMBLE))
        if end == -1:
            return None
        end += len(packetStruct.POSTAMBLE)
        packet, buf[0] = buf[0][:end], buf[0][end:]
        return packet

    except TimeoutError:
        return None

##################
# Parsing Module #
##################

def compute_checksum(data_bytes):
    """Simple checksum: sum of bytes modulo 256."""
    return sum(data_bytes) % 256


def parse_packet(packet_bytes):
    """Parse and validate a raw packet into structured fields."""
    # Minimum header = PREAMBLE + IDENTIFIER + ADDRESS + LENs + CHECKSUM + POSTAMBLE
    if len(packet_bytes) < 6:
        return None, "Packet too short"

    # Verify preamble and postamble
    if not (packet_bytes.startswith(packetStruct.PREAMBLE) and 
            packet_bytes.endswith(packetStruct.POSTAMBLE)):
        return None, "Invalid delimiters"

    # Remove preamble and postamble
    core = packet_bytes[len(packetStruct.PREAMBLE):-len(packetStruct.POSTAMBLE)]

    # Extract adress
    address = struct.unpack(packetStruct.ADDRESS_FORMAT, core[1:2])[0]
    # first 4 bits src, last 4 bits dst
    src = ((address >> 4) & 0b1111) + 9000
    dst = (address & 0b1111) + 9000

    if dst not in [INTERFACES[face]["port"] for face in INTERFACES]:  # if dst is 0 or matches this node's port, it's for us
        # log("WARN", f"Packet received for dst port {dst}, which does not match this node's interfaces")
        return None, f"Packet not addressed to this node, Packet received for dst port {dst}"

    # Check packet integrity through checksum
    checksum = core[-1]
    valid = compute_checksum(core[:-1]) == checksum
    # print(core)
    # print("checksum:", compute_checksum(core[:-1]), "==", checksum)
    if not valid:
        return None, "Checksum mismatch"
    
    # Extract identifier
    identifier = struct.unpack(packetStruct.IDENTIFIER_FORMAT, core[0:1])[0]
  

    # Decide packet type
    pkt_type = (identifier >> 4) & 0b11  # extract PP bits
    
    if pkt_type == packetStruct.PACKET_TYPE_INTEREST:
        name_len = struct.unpack(packetStruct.NAME_LENGTH_FORMAT, core[2:3])[0]
        name = core[3:3+name_len].decode()
        parsed = {"type": "interest", "name": name, "valid": valid, "src": src, "dst": dst}
        log("SUCCESS", f"Parsed interest packet '{name}'")
        return parsed, None

    elif pkt_type == packetStruct.PACKET_TYPE_DATA:
        name_len = struct.unpack(packetStruct.NAME_LENGTH_FORMAT, core[2:3])[0]
        data_len = struct.unpack(packetStruct.DATA_LENGTH_FORMAT, core[3:4])[0]

        start_idx = 4
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
            "src": src,
            "dst": dst,
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


def parse_frag_suffix(name: str):
    """
    If name ends with [x:y], return (base_name, frag_num, frag_total).
    Otherwise return (name, None, None).

    Examples
    --------
    parse_frag_suffix("/dlsu/goks/cam/img[66:70]")
        → ("/dlsu/goks/cam/img", 66, 70)
    parse_frag_suffix("/dlsu/goks/cam/img")
        → ("/dlsu/goks/cam/img", None, None)
    """
    match = re.search(r"\[(\d+):(\d+)\]$", name)
    if match:
        base      = name[:match.start()]
        frag_num  = int(match.group(1))
        frag_total = int(match.group(2))
        return base, frag_num, frag_total
    return name, None, None

def _forward_retransmit_interest(name, base_name, incoming_interface,
                                  sock, SEND_QUEUE):
    """
    Forward a fragment-specific retransmit interest upstream via FIB.

    Uses base_name for the FIB lookup so [x:y] suffix doesn't break matching,
    but forwards the full name (with [x:y]) so the upstream node knows which
    specific fragment is being requested.

    Suppresses forwarding if the upstream face is the same as the incoming
    interface (direction check — prevents loops in XBee broadcast topology).
    """
    route = lookup_fib(base_name)   # ← base_name, not name with [x:y]
    if not route:
        log("WARN",
            f"[RetransmitFwd] No FIB route for '{base_name}', "
            f"cannot forward '{name}'")
        return

    forward_face, dest_port = route

    # Direction check: don't forward back toward the requester
    if forward_face == incoming_interface:
        log("DEBUG",
            f"[RetransmitFwd] Suppressing '{name}' — upstream face "
            f"'{forward_face}' == incoming '{incoming_interface}' (loop prevention)")
        return

    src_port = INTERFACES[forward_face]["port"]
    pkt = build_interest_packet(name, dest_port, src_port)  # full name with [x:y]
    SEND_QUEUE.put((INTERFACES[forward_face]["sock"], None, [pkt]))
    log("SUCCESS",
        f"[RetransmitFwd] Forwarded '{name}' via {forward_face} → port {dest_port}")
    update_metrics("interests_sent")

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
                "parsing_time",
                "processing_time",
                "send_time",
                "functions"
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
            f"{metrics['parsing_time'] * 1000:.2f}",
            f"{metrics['processing_time'] * 1000:.2f}",
            f"{metrics['send_time'] * 1000:.2f}",
            METRICS["functions"]
        ])

        # reset to 0
        METRICS["interest_sent_time"] = 0
        METRICS["interest_receive_time"] = 0
        METRICS["data_sent_time"] = 0
        METRICS["data_receive_time"] = 0
        set_metrics("parsing_time", 0)
        set_metrics("processing_time", 0)
        set_metrics("send_time", 0)
        set_metrics("functions", [])


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
    "data_receive_time": 0,

    "local_int_rcv_time": 0,
    "local_int_sent_time": 0,
    "local_data_rcv_time": 0,
    "local_data_sent_time": 0,
    "parsing_time": 0,
    "processing_time": 0,
    
    "func_start_time": 0,
    "func_end_time": 0,

    "send_time": 0,
    #"receive_time": 0,
    "functions":[]

}

def update_metrics(metric_name, value=1):
    """ Update a specific metric counter."""
    if metric_name not in METRICS:
        log("WARN", f"Unknown metric '{metric_name}'")
        return
    METRICS[metric_name] += value

def set_metrics(metric_name, value =1):
    """Set a specific metric counter (time)."""
    if metric_name not in METRICS:
        log("WARN", f"Unknown metric, '{metric_name}'")
        return
    METRICS[metric_name] = value

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
INTEREST_LIFETIME = 180  # seconds

INTERFACES = {}  # port -> face, sock, port 

PIT = {}  # Pending Interest Table
PIT_LOCK = threading.Lock()
PIT_MAPPING = {}  # receiving_face -> addr of sender

CS = {}   # Content Store
CS_MAX_BYTES = 10 * 1024 * 1024  # default 10 MB; overridden per node via config
CS_CURRENT_BYTES = 0   # running total of cached data size in bytes

def set_cs_max_storage(max_mb: float):
    """Configure the CS size cap (in megabytes) loaded from node_config."""
    global CS_MAX_BYTES
    CS_MAX_BYTES = int(max_mb * 1024 * 1024)
    log("INFO", f"CS max storage set to {max_mb} MB ({CS_MAX_BYTES} bytes)")

FIB = {}   # Forwarding Information Base
FACES = []  # List of faces

FUNCTIONS_TABLE = {}   # Functions Table
NODE_FUNCTIONS_MAPPING = {}

FRAG_BUFFER = {}
FRAG_TIMEOUT        = 1.0   # seconds before declaring fragment(s) lost
FRAG_MAX_RETRIES    = 5     # give up after this many retransmit attempts

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

def _get_storage_filename(name):
    """Derive the on-disk filename for a CS entry — mirrors save_data_to_file naming.
    Strips any existing extension first to avoid double-extensions (e.g. .jpg.jpg)
    when the CS key itself was loaded from a filename that already had an extension.
    """
    if not STORAGE_PATH:
        return None
    # Strip leading slash, replace path separators with underscores
    base = name[1:].replace("/", "_")
    # Remove any existing file extension so we never produce e.g. .jpg.jpg
    base = os.path.splitext(base)[0]
    if "recognize" in name:
        return os.path.join(STORAGE_PATH, base) + ".txt"
    elif "embedding" in name:
        return os.path.join(STORAGE_PATH, base) + ".npy"
    else:
        return os.path.join(STORAGE_PATH, base) + ".jpg"


def _evict_lfu():
    """
    Evict one CS entry using LFU policy.
    Ties in hit_count are broken by least-recently-used (oldest timestamp).
    Also deletes the corresponding file from disk so storage stays in sync.
    """
    global CS_CURRENT_BYTES
    if not CS:
        return
    # Pick the entry with the lowest hit_count; break ties by oldest timestamp
    victim = min(CS.keys(), key=lambda k: (CS[k]["hit_count"], CS[k]["timestamp"]))
    freed      = CS[victim]["size"]
    hit        = CS[victim]["hit_count"]
    ts         = CS[victim]["timestamp"]

    # Determine if this was a hit_count eviction or a timestamp tiebreak
    min_hits   = min(CS[k]["hit_count"] for k in CS)
    tied       = sum(1 for k in CS if CS[k]["hit_count"] == min_hits)
    if tied > 1:
        reason = f"hit_count={hit} (timestamp tiebreak — oldest among {tied} tied entries)"
    else:
        reason = f"hit_count={hit} (least frequently used)"

    CS.pop(victim)
    CS_CURRENT_BYTES -= freed

    # Delete from disk — keep storage directory in sync with CS
    filepath = _get_storage_filename(victim)
    if filepath and os.path.isfile(filepath):
        try:
            os.remove(filepath)
            log("SUCCESS",
                f"[LFU] Evicted '{victim}' from CS and disk — {reason} "
                f"(freed {freed} bytes, CS now {CS_CURRENT_BYTES} bytes)")
        except OSError as e:
            log("WARN",
                f"[LFU] Evicted '{victim}' from CS but failed to delete file: {e}")
    else:
        log("SUCCESS",
            f"[LFU] Evicted '{victim}' from CS (no disk file) — {reason} "
            f"(freed {freed} bytes, CS now {CS_CURRENT_BYTES} bytes)")


def store_data(name, data):
    """Store data in the Content Store (CS) with LFU eviction when over capacity."""
    global CS_CURRENT_BYTES
    entry_size = len(data)

    # Reject immediately if the entry alone exceeds the entire CS capacity
    if entry_size > CS_MAX_BYTES:
        log("WARN",
            f"Image over size: '{name}' ({entry_size} B) exceeds CS capacity "
            f"({CS_MAX_BYTES} B) — not cached")
        return

    # If already cached, update data/size/timestamp but preserve hit_count
    if name in CS:
        old_size = CS[name]["size"]
        CS[name]["data"] = data
        CS[name]["size"] = entry_size
        CS[name]["timestamp"] = time.time()
        # hit_count intentionally preserved
        CS_CURRENT_BYTES += entry_size - old_size
        log("SUCCESS", f"Updated '{name}' in CS (size: {entry_size} bytes, hit_count preserved={CS[name]['hit_count']})")
        return

    # Evict until there is room for the new entry (LFU, tie-break by LRU)
    while CS_CURRENT_BYTES + entry_size > CS_MAX_BYTES and CS:
        _evict_lfu()

    CS[name] = {
        "data": data,
        "timestamp": time.time(),
        "hit_count": 0,    # cache-hit tally (incremented on each lookup_content hit)
        "size": entry_size,
    }
    CS_CURRENT_BYTES += entry_size
    log("SUCCESS",
        f"Cached '{name}' into CS (entry_size={entry_size} B, "
        f"CS total={CS_CURRENT_BYTES} B / {CS_MAX_BYTES} B, entries={len(CS)})")

def lookup_content(name):
    """Look up content in the Content Store (CS). Increments hit_count on a cache hit."""
    entry = CS.get(name, None)
    if entry is not None:
        entry["hit_count"] += 1
        log("SUCCESS",
            f"CS hit for '{name}' (hit_count={entry['hit_count']})")
    return entry

def update_CS_timestamp(name):
    """Update the timestamp of a CS entry to mark it as recently used (LRU touch)."""
    if name in CS:
        CS[name]["timestamp"] = time.time()
        log("SUCCESS",
            f"Refreshed CS timestamp for '{name}' (hit_count={CS[name]['hit_count']})")

def initialize_content_store(storage_path):
    """Load existing content from storage into the Content Store (CS)."""
    global STORAGE_PATH, CS_CURRENT_BYTES
    STORAGE_PATH = storage_path
    CS_CURRENT_BYTES = 0  # reset on (re)init

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
            if name in FRAG_BUFFER:
                del FRAG_BUFFER[name] 
        
    return len(expired_names)

def get_PIT_entry(name):
    with PIT_LOCK:
        return PIT.get(name)



#####################
# Processing Module #
#####################
PAYLOAD_SIZE = 100

def process_interest(packet, addr, sock, SEND_QUEUE, interface):
    """Process Interest: check CS or forward."""
    name = packet["name"]
    update_metrics("interests_received")

    if METRICS["test_start_time"] == 0.0:
        METRICS["test_start_time"] = time.time()

    # ── NEW: detect fragment-specific retransmit request ──────────────────
    base_name, req_frag_num, req_frag_total = parse_frag_suffix(name)
    is_frag_retransmit = req_frag_num is not None
    # Look up content using the base name (CS never stores [x:y] suffixes)
    cs_lookup_name = base_name if is_frag_retransmit else name
    # ──────────────────────────────────────────────────────────────────────

    sent_time = datetime.now()
    METRICS["interest_receive_time"] = sent_time.timestamp() # for easier readability in CSV
    log(
        "DEBUG",
        f"Interest '{name}' received at {sent_time.strftime('%H:%M:%S.%f')}"  # HH:MM:SS.mmm
        # f"Interest '{name}' received at {sent_time.timestamp()}, serving from CS"
    )
    
    # First check Content Store
    cached_data = lookup_content(cs_lookup_name)
    if cached_data:
        sent_time = datetime.now()
        METRICS["interest_receive_time"] = sent_time.timestamp() # for easier readability in CSV
        log(
            "DEBUG",
            f"Interest '{name}' received at {sent_time.strftime('%H:%M:%S.%f')}"  # HH:MM:SS.mmm
            # f"Interest '{name}' received at {sent_time.timestamp()}, serving from CS"
        )

        update_CS_timestamp(name)
        data_bytes = cached_data["data"]
        
        if is_frag_retransmit:
            # ── Serve only the requested fragment ─────────────────────────
            log("INFO",
                f"Retransmit request for fragment {req_frag_num}/{req_frag_total} "
                f"of '{base_name}' — serving from CS")

            # Re-derive the same fragmentation the original build used
            max_payload = PAYLOAD_SIZE - (12 + len(base_name))
            fragments   = fragment_data(data_bytes, max_payload=max_payload)

            if req_frag_num < 1 or req_frag_num > len(fragments):
                log("ERROR",
                    f"Requested fragment {req_frag_num} out of range "
                    f"(have {len(fragments)}) for '{base_name}'")
                return

            # Build a single-fragment data packet for just this fragment
            frag_payload = fragments[req_frag_num - 1]   # list is 0-indexed
            frag_name    = f"{base_name}[{req_frag_num}:{req_frag_total}]"

            identifier = (packetStruct.PROTOCOL_VERSION << 6) | (packetStruct.PACKET_TYPE_DATA << 4)
            src_port   = packet["dst"] - 9000   # we are the data source
            dst_port   = packet["src"] - 9000

            header  = struct.pack(packetStruct.IDENTIFIER_FORMAT, identifier)
            header += struct.pack(packetStruct.ADDRESS_FORMAT, (src_port << 4) | dst_port)
            header += struct.pack(packetStruct.NAME_LENGTH_FORMAT, len(frag_name.encode()))
            header += struct.pack(packetStruct.DATA_LENGTH_FORMAT, len(frag_payload))

            core      = header + frag_name.encode() + frag_payload
            checksum  = compute_checksum(core).to_bytes(1, "big")
            pkt_bytes = packetStruct.PREAMBLE + core + checksum + packetStruct.POSTAMBLE

            SEND_QUEUE.put((sock, addr, [pkt_bytes]))
            log("SUCCESS",
                f"Sent retransmit fragment {req_frag_num}/{req_frag_total} "
                f"for '{base_name}' ({len(pkt_bytes)} bytes)")
            update_metrics("data_packets_sent")

        else:
            # ── Normal CS hit: send all fragments as before ────────────────
            sent_time = datetime.now()
            METRICS["interest_receive_time"] = sent_time.timestamp()
            log("DEBUG", f"Interest '{name}' received at {sent_time.strftime('%H:%M:%S.%f')}")

            response = build_data_packet(name, data_bytes, packet["src"], packet["dst"])
            update_metrics("data_total_sent")
            SEND_QUEUE.put((sock, addr, response))
            log("INFO", f"Served '{name}' from CS to {sock}")

            sent_time = datetime.now()
            METRICS["data_sent_time"] = sent_time.timestamp()
            log("DEBUG", f"Data '{name}' sent at {sent_time.timestamp()} to {addr}")

            update_metrics("data_packets_sent", len(response))

        return   # ← both branches return here; rest of function unchanged
    
    # Use base_name for lookup so '/8.jpg[16:881]' matches PIT entry '/8.jpg'
    pit_lookup_name = base_name if is_frag_retransmit else name
    if pit_lookup_name in PIT:
        log("INFO", f"Interest '{name}' aggregated into PIT entry '{pit_lookup_name}'")
        store_interest(pit_lookup_name, interface, addr)
        if is_frag_retransmit:
            # This node has a PIT entry but not the data (not in CS).
            # Forward the fragment request upstream toward the data source.
            _forward_retransmit_interest(name, base_name, interface,
                                          sock, SEND_QUEUE)
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
            log("DEBUG", f"Parsed In-Network Function Interest: base_name='{base_name}', funcs={funcs}")

            if "recognize" in funcs:
                model, recognize = funcs # ['openface', 'recognize']
                log("INFO", f"Received In-Network Function Interest for recognition pipeline: '{name}'")
                func = FUNCTIONS_TABLE["orchestrate"]
                interest_expr = func(base_name, model, PIT, NODE_FUNCTIONS_MAPPING)
                log("DEBUG", f"Orchestrated Interest Expression: '{interest_expr}'")
                store_interest(name, interface, addr, [recognize], interest_expr)
                base_name = interest_expr
            else:
                # Store NFN interest in PIT
                store_interest(name, interface, addr, funcs, base_name)

            cached_data = lookup_content(base_name)
            if cached_data:
                update_CS_timestamp(base_name)
                bytes = cached_data["data"]
                response = build_data_packet(name, bytes, packet["src"], packet["dst"])
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
                # set_metrics("local_int_sent_time", time.time())
                # interest_delay = (
                #     METRICS["local_int_sent_time"] - METRICS["local_int_rcv_time"]
                # )
                # log("DEBUG",
                #     f"Interest '{name}' processing delay: {interest_delay * 1000:.4f} ms")
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
                interest_packet = build_interest_packet(name, dest_port, INTERFACES[forward_face]["port"])
                log("INFO", f"Forwarding Interest for '{name}' to {forward_face}")

                # store interest to PIT
                store_interest(name, interface, addr)
                # log("INFO", f"PIT: {PIT}")

                if METRICS["interest_sent_time"] == 0:
                    METRICS["interest_sent_time"] = datetime.now().timestamp()

                # send
                set_metrics("local_int_sent_time", time.time())
                interest_delay = (
                    METRICS["local_int_sent_time"] - METRICS["local_int_rcv_time"]
                )
                # log("DEBUG",
                #     f"Interest '{name}' processing delay: {interest_delay * 1000:.4f} ms")
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
            set_metrics("local_int_sent_time", time.time())
            interest_delay = (
                METRICS["local_int_sent_time"] - METRICS["local_int_rcv_time"]
            )
            # log("DEBUG",
            #     f"Interest '{name}' processing delay: {interest_delay * 1000:.4f} ms")
            SEND_QUEUE.put((INTERFACES[forward_face]["sock"], dest_addr, [build_interest_packet(name, dest_port, INTERFACES[forward_face]["port"])]))

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
    # if METRICS["local_data_rcv_time"] == 0:
    #     METRICS["local_data_rcv_time"] = time.time()
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
                    new_packet = modify_packet(raw_packet, face)
                    SEND_QUEUE.put((sock, PIT_MAPPING[face], [new_packet]))
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
                    # set_metrics("local_data_sent_time", time.time())
                    # data_delay = (
                    #     METRICS["local_data_sent_time"] - METRICS["local_data_rcv_time"]
                    #     )
                    # log("DEBUG",
                    #     f"Data '{name}' processing delay: {data_delay * 1000:.4f} ms")
                    new_packet = modify_packet(raw_packet, face)
                    SEND_QUEUE.put((sock, PIT_MAPPING[face], [new_packet]))
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
            # set_metrics("local_data_sent_time", time.time())

            # data_delay = (
            #     METRICS["local_data_sent_time"] - METRICS["local_data_rcv_time"]
            #     )
            # log("DEBUG",
            #     f"Data '{name}' processing delay: {data_delay * 1000:.4f} ms")
            pit_entry = PIT[original_name]
            rtt = time.time() - pit_entry["time"]
            METRICS["ave_RTT"] = 0.0
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
                # log("DEBUG", f"Test completed in {time.strftime('%H:%M:%S', time.gmtime(elapsed_time))}")
                average_throughput = METRICS["total_data_overhead_bytes_received"] / 1024 / elapsed_time if elapsed_time > 0 else 0.0
                average_goodput = METRICS["total_data_bytes_received"] / 1024 / elapsed_time if elapsed_time > 0 else 0.0
                METRICS["throughput"] = average_throughput  # in KB/s
                METRICS["goodput"] = average_goodput  # in KB/s

            # if original_name in METRICS["data_packets_to_receive_buffer"]:
            #     update_metrics("data_packets_to_receive", METRICS["data_packets_to_receive_buffer"][original_name])
            #     del METRICS["data_packets_to_receive_buffer"][original_name]

            # log("DEBUG", f"Parsing time for '{original_name}': {METRICS['parsing_time'] * 1000:.4f} milliseconds")
            # log("DEBUG", f"Processing time for '{original_name}': {METRICS['processing_time'] * 1000:.4f} milliseconds")
            # set_metrics("parsing_time", 0)
            # set_metrics("processing_time", 0)
            
            receive_time = datetime.now()
            METRICS["data_receive_time"] = receive_time.timestamp()
            
            """log("DEBUG",
                f"sending_time for '{original_name}': {METRICS['send_time'] * 1000:.4f} milliseconds")
            set_metrics("send_time", 0) """
            # send interest /dlsu/goks/cam/capture8.jpg
            
            # append_metrics_to_csv({
            #     "name": original_name,
            #     "RTT": rtt_ms,
            #     "interest_sent_time": METRICS["interest_sent_time"], # make this float
            #     "interest_receive_time": METRICS["interest_receive_time"],
            #     "data_sent_time": METRICS["data_sent_time"],
            #     "data_receive_time": METRICS["data_receive_time"]
            # })

            # log( "DEBUG", f"Data '{name}' received at {receive_time.strftime('%H:%M:%S.%f')}")  # HH:MM:SS.mmm

        return cleanup_flags["delete_pit"]

def modify_packet(packet_bytes, face):
    """Modify the src, destination, checksu, address in the packet bytes."""
    packet = bytearray(packet_bytes)

    src_port = INTERFACES[face]["port"] - 9000
    dst_port = INTERFACES[face]["dst_port"] - 9000
    packet[3] = (src_port << 4) | dst_port # 4 bits src_port, 4 bits dst_port
    
    core = packet[2:-3]  
    new_checksum = compute_checksum(core)
    packet[-3] = new_checksum

    return bytes(packet)  # Return modified packet bytes


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
        FRAG_BUFFER[name] = {
            "frags": {},
            "expected": frag_total,
            "last_updated": time.time(),   # NEW — watchdog uses this
            "retransmit_count": 0,         # NEW — give-up counter
        }
        log("SUCCESS", f"Initialized fragment buffer for '{name}' expecting {frag_total} parts")

    FRAG_BUFFER[name]["frags"][frag_num] = data
    FRAG_BUFFER[name]["last_updated"] = time.time()   # NEW — refresh on every arrival

    if len(FRAG_BUFFER[name]["frags"]) == frag_total:
        log("INFO", f"Node requested the data - processing locally")
        log("INFO", f"All fragments received for '{name}', reassembling (total={frag_total})")
        full_data = reassemble_fragments(name, frag_total)

        if full_data is None:                          # NEW — guard against gaps
            log("WARN", f"Reassembly failed for '{name}', watchdog will retry")
            return None

        if waiting_for_name:
            return process_nfn_request(
                name, waiting_for_name, full_data,
                pit_entry, SEND_QUEUE, cleanup_flags
            )
        else:
            cleanup_flags["delete_pit"] = True
            return full_data

    return None  # not all fragments received yet


# Reassemble fragments
def reassemble_fragments(name, frag_total):
    """Reassemble fragments for a given name. Returns None if any fragment is missing."""
    frags   = FRAG_BUFFER[name]["frags"]
    missing = [i for i in range(1, frag_total + 1) if i not in frags]

    if missing:
        log("WARN", f"Cannot reassemble '{name}': missing fragments {missing}")
        return None   # caller must handle None; watchdog will re-request

    full_data = b"".join(frags[i] for i in range(1, frag_total + 1))
    log("INFO", f"Fragment assembly complete for '{name}', final_size={len(full_data)} bytes")
    return full_data


def frag_watchdog(SEND_QUEUE):
    """
    Periodically scans FRAG_BUFFER for stalled assemblies.

    For each stalled buffer:
      - Identifies which fragment numbers are missing.
      - Re-issues an Interest packet for each missing fragment.
      - Gives up after FRAG_MAX_RETRIES attempts and removes the buffer.
    """
    while True:
        time.sleep(1.0)
        now = time.time()
        
        for name in list(FRAG_BUFFER.keys()):
            buf = FRAG_BUFFER.get(name)
            if buf is None:
                continue
            
            # ── skip if this name is part of an NFN orchestration ──
            with PIT_LOCK:
                pit_entry = PIT.get(name)
                if pit_entry and pit_entry.get("waiting_for"):
                    # This entry is waiting on a sub-interest (e.g., recognize → embedding).
                    # Don't retransmit — the orchestration pipeline is still in progress.
                    continue

                # Also check if any OTHER PIT entry is waiting_for this name
                is_dependency = any(
                    e.get("waiting_for") == name
                    for e in PIT.values()
                )
                if is_dependency:
                    continue
            # ─────────────────────────────────────────────────────────────

            # Dynamic timeout based on retry count
            dynamic_timeout = FRAG_TIMEOUT + (buf["retransmit_count"] * 2)

            # Skip buffers that are still receiving data
            if (now - buf["last_updated"]) < dynamic_timeout:
                continue

            expected = set(range(1, buf["expected"] + 1))
            received = set(buf["frags"].keys())
            missing  = sorted(expected - received)

            if not missing:
                continue  # complete — process_data will clean up

            # Give up if we've retried too many times
            if buf["retransmit_count"] >= FRAG_MAX_RETRIES:
                log("ERROR",
                    f"[FragWatcher] Giving up on '{name}' after "
                    f"{FRAG_MAX_RETRIES} retries — dropping buffer. "
                    f"Still missing: {missing}")
                FRAG_BUFFER.pop(name, None)
                # Also clean up the dangling PIT entry so it doesn't linger
                with PIT_LOCK:
                    if name in PIT:
                        PIT.pop(name)
                        log("WARN", f"[FragWatcher] Removed stale PIT entry for '{name}'")
                continue

            buf["retransmit_count"] += 1
            buf["last_updated"] = now   # reset timer for next retry window

            log("WARN",
                f"[FragWatchdog] Fragment timeout for '{name}' "
                f"(attempt {buf['retransmit_count']}/{FRAG_MAX_RETRIES}): "
                f"re-requesting fragments {missing}")

            route = lookup_fib(name)
            if not route:
                log("WARN", f"[FragWatchdog] No route for '{name}', cannot retransmit")
                continue

            forward_face, dest_port = route
            src_port = INTERFACES[forward_face]["port"]

            for frag_idx in missing:
                # Re-request the specific fragment using the [x:y] notation
                frag_name = f"{name}[{frag_idx}:{buf['expected']}]"
                pkt = build_interest_packet(frag_name, dest_port, src_port)
                SEND_QUEUE.put((INTERFACES[forward_face]["sock"], None, [pkt]))
                log("INFO", f"[FragWatchdog] Re-issued interest for '{frag_name}'")


def save_data_to_file(name, data_bytes):
    """Save data bytes to a file and store in CS."""
    log("INFO", f"Saving processed output for '{name}' to CS")
    if "recognize" in name:
        filename = os.path.join(STORAGE_PATH, name[1:].replace('/', '_')) + ".txt"
    elif name.endswith(".txt"):
        filename = os.path.join(STORAGE_PATH, name[1:].replace('/', '_'))
    elif "embedding" in name:
        filename = os.path.join(STORAGE_PATH, name[1:].replace('/', '_')) + ".npy"
    else:
        filename = os.path.join(STORAGE_PATH, name[1:].replace('/', '_'))

    # Always go through store_data — it handles both new entries and updates,
    # and keeps CS_CURRENT_BYTES accurate. hit_count is preserved for existing entries.
    store_data(name, data_bytes)

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
    # Save the original data (use direct CS check — lookup_content would falsely increment hit_count)
    if waiting_for_name not in CS:
        save_data_to_file(waiting_for_name, full_data)
    cleanup_flags["delete_waiting_for"] = True

    # Apply functions in the pipeline
    processed_data = apply_function_pipeline(name, full_data, pit_entry)
    log("INFO", f"In-Network Function pipeline complete for '{name}', size={len(processed_data)} bytes")
    # log("INFO", f"Building final In-Network Function Data packet for '{name}'")

    pit_entry, original_name, waiting_for_name = find_pit_entry(name)  # refresh PIT entry in case it was modified during processing 
    log("DEBUG", f"Current PIT entry: {pit_entry}")
    if waiting_for_name == name and len(pit_entry.get("funcs", [])) == 1 and pit_entry["funcs"][0] == "recognize":
        processed_data = apply_function_pipeline(original_name, processed_data, pit_entry)
        log("DEBUG", f"Applied final recognition function for '{processed_data}'")
        response = build_data_packet(original_name, processed_data)
        
        forward_face = pit_entry["interface"].copy().pop()  # get the single face to forward to
        SEND_QUEUE.put((INTERFACES["face0"]["sock"],"",response))

        PIT.pop(waiting_for_name)
        cleanup_flags["delete_pit"] = True

        sent_time = datetime.now()
        METRICS["data_sent_time"] = sent_time.timestamp()
        log(
            "DEBUG",
            # f"Data '{name}' sent at {sent_time.strftime('%H:%M:%S.%f')}"  # HH:MM:SS.mmm
            f"Data '{original_name}' sent at {sent_time.timestamp()}"
        )

        append_metrics_to_csv({
            "name": f"{original_name}",
            "RTT": 0,
            "interest_sent_time": METRICS["interest_sent_time"], # make this float
            "interest_receive_time": METRICS["interest_receive_time"],
            "data_sent_time": METRICS["data_sent_time"],
            "data_receive_time": METRICS["data_receive_time"]
        })
        
        return processed_data
        
    # Send processed results back

    for forward_face in pit_entry["interface"]:
        if forward_face is not None and forward_face in INTERFACES:
            SEND_QUEUE.put((
                INTERFACES[forward_face]["sock"],
                PIT_MAPPING.get(forward_face),
                build_data_packet(name, processed_data, INTERFACES[forward_face]["dst_port"], INTERFACES[forward_face]["port"])
            ))
    
    update_metrics("data_packets_sent", len(build_data_packet(name, processed_data)))
    log("DEBUG", f"Processed In-Network Function '{name}' and sent to {pit_entry['interface']}")

    cleanup_flags["delete_pit"] = True
    return processed_data


def apply_function_pipeline(name, data, pit_entry):
    """Apply all functions in the NFN pipeline"""
    processed_data = data
    log("INFO", f"Initializing ML pipeline for '{name}', stages={pit_entry.get('funcs', [])}")
    log("INFO", f"Initial payload size: {len(data)} bytes")
    for func_name in pit_entry.get("funcs", []):
        log("INFO", f"Applying function: {func_name}")
        set_metrics("func_start_time", time.time())
        if func_name not in FUNCTIONS_TABLE:
            log("ERROR", f"Function '{func_name}' not found in FUNCTIONS_TABLE")
            continue

        try:
            func = FUNCTIONS_TABLE[func_name]
            log("INFO", f"ML stage start: '{func_name}' on '{name}', "
            f"input={len(processed_data)} bytes")
            processed_data = func(processed_data)
            log("INFO", f"Function '{func_name}' completed successfully")
            set_metrics("func_end_time", time.time())
            process_delay = (
                METRICS["func_end_time"] - METRICS["func_start_time"]
            )
            METRICS["functions"].append((func_name, round((METRICS['func_end_time'] - METRICS['func_start_time']) * 1000, 2)))
            log("DEBUG",
            f"Processing delay for  '{func_name}': '{process_delay*1000:.4f}' ms")
        except Exception as e:
            log("ERROR", f"Function '{func_name}' failed: {e}")
            import traceback
            traceback.print_exc()
            # Continue with unprocessed data
    return processed_data



###################
# Packet Builders #
###################

def build_interest_packet(name, dest_port=None, src_port=None):
    name_bytes = name.encode()
    identifier = (packetStruct.PROTOCOL_VERSION << 6) | (packetStruct.PACKET_TYPE_INTEREST << 4)
    header = struct.pack(packetStruct.IDENTIFIER_FORMAT, identifier)
    src_port = src_port - 9000 if src_port is not None else INTERFACES["face0"]["port"] - 9000
    dst_port = dest_port - 9000 if dest_port is not None else INTERFACES["face0"]["dst_port"] - 9000
    header += struct.pack(packetStruct.ADDRESS_FORMAT, (src_port << 4) | dst_port) # 4 bits src_port, 4 bits dst_port
    header += struct.pack(packetStruct.NAME_LENGTH_FORMAT, len(name_bytes))
    core = header + name_bytes
    checksum = compute_checksum(core).to_bytes(1, 'big')
    print(f"checksum: {checksum}")
    packet = packetStruct.PREAMBLE + core + checksum + packetStruct.POSTAMBLE
    log("SUCCESS", f"Built interest packet for '{name}'")
    return packet


def build_data_packet(name, data, dest_port=None, src_port=None):
    # name_bytes = name.encode()
    data_bytes = data

    packets = []
    fragments = fragment_data(data_bytes, max_payload=PAYLOAD_SIZE-(12+len(name)))  # 5 bytes for header fields, rest for payload

    src_port = src_port - 9000 if src_port is not None else INTERFACES["face0"]["port"] - 9000
    dst_port = dest_port - 9000 if dest_port is not None else INTERFACES["face0"]["dst_port"] - 9000
    # log("DEBUG", f"Building data packet with src_port={src_port}, dest_port={dst_port}")
    
    total_frags = len(fragments)
    for idx, frag in enumerate(fragments, start=1):
        # only add [x:y] if more than one fragment
        if total_frags > 1:
            frag_name = f"{name}[{idx}:{total_frags}]".encode()
        else:
            frag_name = name.encode()

        identifier = (packetStruct.PROTOCOL_VERSION << 6) | (packetStruct.PACKET_TYPE_DATA << 4)
        header = struct.pack(packetStruct.IDENTIFIER_FORMAT, identifier)
        header += struct.pack(packetStruct.ADDRESS_FORMAT, (src_port << 4) | dst_port) # 4 bits src_port, 4 bits dst_port
        header += struct.pack(packetStruct.NAME_LENGTH_FORMAT, len(frag_name))
        header += struct.pack(packetStruct.DATA_LENGTH_FORMAT, len(frag))

        core = header + frag_name + frag
        checksum = compute_checksum(core).to_bytes(1, 'big')

        packet = packetStruct.PREAMBLE + core + checksum + packetStruct.POSTAMBLE
        packets.append(packet)
        log("SUCCESS", f"Built data packet for '{name}' fragment {idx}/{total_frags} (size={len(packet)} bytes) (namesize={len(frag_name)} bytes, payload={len(frag)} bytes)")

    return packets


def fragment_data(data_bytes, max_payload=PAYLOAD_SIZE):
    """
    Splits data into fragments if > max_payload.
    Returns a list of fragments
    """
    num_frags = str(len(data_bytes) // max_payload) if len(data_bytes) > max_payload else ""
    max_payload = max_payload - (2 * len(num_frags))
    return [data_bytes[i:i+max_payload] for i in range(0, len(data_bytes), max_payload)]