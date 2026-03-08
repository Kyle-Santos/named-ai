##############################
# Packet Structure Constants #
##############################

import struct

# Start and End Delimiters
# PREAMBLE = b'\x7E' # 1 byte
# POSTAMBLE = b'\xFF'   # 1 byte
PREAMBLE = b'\xDE\xAD' # 2 bytes for better framing
POSTAMBLE = b'\xBE\xEF'   # 2 bytes for better framing


######################################
# Identifier Field (8 bits / 1 byte) #
######################################
# Format: [VVPP RRRR]
# VV: Version (2 bits) - Version of the protocol
# PP: Packet Type (2 bits) - allows for 4 types of packet
# RRRR: Reserved (4 bits) - should be 0

# Protocol Version
PROTOCOL_VERSION = 0b01 # Current version is 1

# Packet Types (using 2 bits)
PACKET_TYPE_INTEREST = 0b00 # 0
PACKET_TYPE_DATA     = 0b01 # 1

# Reserved type 0b0000 (0) could be for a NULL/padding packet or for future uses


###########################
# Field Sizes and Formats #
###########################
# ! = Network byte order (big-endian)
# B = unsigned char (1 byte / 8 bits)
# H = unsigned short (2 bytes / 16 bits)
# I = unsigned int (4 bytes / 32 bits)

IDENTIFIER_FORMAT = '!B' # Identifier field (1 byte)
ADDRESS_FORMAT = '!B' # Address field (1 byte) SSSSDDDD (Source and Destination)
NAME_LENGTH_FORMAT = '!B' # Name Length field (1 byte)
# DATA_LENGTH_FORMAT = '!I'  # Data Length field (4 bytes)
DATA_LENGTH_FORMAT = '!B'  # Data Length field (1 byte)
CHECKSUM_FORMAT = '!B' # Checksum (FCS) field (1 byte)



# Interest Packet = Identifier + Name Length + Checksum
# Not including Name since it is variable length
FIXED_HEADER_SIZE_INTEREST = (
    struct.calcsize(IDENTIFIER_FORMAT) +
    struct.calcsize(ADDRESS_FORMAT) +
    struct.calcsize(NAME_LENGTH_FORMAT) +
    struct.calcsize(CHECKSUM_FORMAT)
)

# Data Packet = Identifier + Name Length + Data Length + Checksum
# Not including Name and Data since those are variable length
FIXED_HEADER_SIZE_DATA = (
    struct.calcsize(IDENTIFIER_FORMAT) +
    struct.calcsize(ADDRESS_FORMAT) +
    struct.calcsize(NAME_LENGTH_FORMAT) +
    struct.calcsize(DATA_LENGTH_FORMAT) +
    struct.calcsize(CHECKSUM_FORMAT) 
)