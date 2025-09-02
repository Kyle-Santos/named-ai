import struct
import json

class PacketType:
    INTEREST = 0
    DATA = 1

class PacketParser:
    @staticmethod
    def build_interest(name: str):
        version = 1        # 2 bits
        packet_type = 0    # 1 bit → Interest
        frag_flag = 0      # 1 bit
        reserved = 0       # 4 bits

        identifier = (version << 6) | (packet_type << 5) | (frag_flag << 4) | reserved

        name_bytes = name.encode("ascii")
        name_len = len(name_bytes)

        # XOR checksum
        checksum = 0
        for b in bytes([identifier, name_len]) + name_bytes:
            checksum ^= b

        return struct.pack(f"!BB{name_len}sB", identifier, name_len, name_bytes, checksum)

    @staticmethod
    def build_data(name: str, data: dict):
        version = 1
        packet_type = 1   # Data
        frag_flag = 0
        reserved = 0

        identifier = (version << 6) | (packet_type << 5) | (frag_flag << 4) | reserved

        name_bytes = name.encode("ascii")
        name_len = len(name_bytes)

        data_bytes = json.dumps(data).encode("utf-8")
        data_len = len(data_bytes)

        checksum = 0
        for b in bytes([identifier, name_len]) + name_bytes + bytes([data_len]) + data_bytes:
            checksum ^= b

        return struct.pack(f"!BB{name_len}sB{data_len}sB",
                           identifier, name_len, name_bytes,
                           data_len, data_bytes, checksum)

    @staticmethod
    def parse(raw_bytes: bytes):
        identifier = raw_bytes[0]
        version = (identifier >> 6) & 0b11
        ptype = (identifier >> 5) & 0b1

        name_len = raw_bytes[1]
        offset = 2
        name = raw_bytes[offset:offset + name_len].decode("ascii")
        offset += name_len

        if ptype == PacketType.INTEREST:
            checksum = raw_bytes[offset]
            calc = 0
            for b in raw_bytes[:-1]:
                calc ^= b
            if checksum != calc:
                raise ValueError("Checksum mismatch in Interest packet")
            return {"type": "Interest", "version": version, "name": name}

        elif ptype == PacketType.DATA:
            data_len = raw_bytes[offset]
            offset += 1
            data_bytes = raw_bytes[offset:offset + data_len]
            offset += data_len
            checksum = raw_bytes[offset]

            calc = 0
            for b in raw_bytes[:-1]:
                calc ^= b
            if checksum != calc:
                raise ValueError("Checksum mismatch in Data packet")

            return {
                "type": "Data",
                "version": version,
                "name": name,
                "data": json.loads(data_bytes.decode("utf-8"))
            }