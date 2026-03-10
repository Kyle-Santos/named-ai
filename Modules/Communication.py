import threading
import time
import socket
import serial
import Packet_Structure as packetStruct


class Communication:
    """Abstract base class for all communication backends."""

    def create_interface(self, interfaces: list) -> dict:
        raise NotImplementedError

    def send_packet(self, sock, addr, packet_bytes: bytes):
        raise NotImplementedError

    def receive_packet(self, sock, buf: list):
        raise NotImplementedError

    # ------------------------------------------------------------------ #
    # Shared packet-extraction logic (works for both backends)            #
    # ------------------------------------------------------------------ #
    @staticmethod
    def extract_packet(buf: list):
        """
        Given a raw byte buffer (buf[0]), strip any leading garbage,
        then return the first complete PREAMBLE…POSTAMBLE packet or None.
        Mutates buf[0] in place so leftover bytes are preserved.
        """
        # Discard anything before the first preamble
        start = buf[0].find(packetStruct.PREAMBLE)
        if start == -1:
            buf[0] = b""
            return None
        if start > 0:
            buf[0] = buf[0][start:]

        # Return the first complete packet if postamble is present
        end = buf[0].find(packetStruct.POSTAMBLE, len(packetStruct.PREAMBLE))
        if end == -1:
            return None

        end += len(packetStruct.POSTAMBLE)
        packet, buf[0] = buf[0][:end], buf[0][end:]
        return packet


# ------------------------------------------------------------------ #
# XBee serial backend                                                 #
# ------------------------------------------------------------------ #

BAUD_RATE = 115200


class XBeeCom(Communication):
    """Communication over an XBee radio via a serial port."""

    def __init__(self, port: str):
        self.port = port
        self._interfaces: dict = {}
        self._lock = threading.Lock()
        self._sending = threading.Event()

    # -- interface setup ------------------------------------------------

    def _create_serial_connection(self):
        ser = serial.Serial(self.port, BAUD_RATE, timeout=0, rtscts=True)
        time.sleep(1)   # XBee warmup
        return ser

    def create_interface(self, interfaces: list) -> dict:
        ser = self._create_serial_connection()

        for iface in interfaces:
            face = iface["face"]
            self._interfaces[face] = {
                "sock":     ser,
                "face":     face,
                "port":     iface["port"],
                "dst_port": iface["dst_port"],
            }

        return self._interfaces

    # -- send / receive -------------------------------------------------

    def send_packet(self, sock, addr, packet_bytes: bytes):
        """Write packet_bytes to the XBee serial port (addr is unused)."""
        try:
            self._sending.set()
            with self._lock:
                sock.write(packet_bytes)
                sock.flush()
        finally:
            self._sending.clear()

    def receive_packet(self, sock, buf: list):
        """
        Non-blocking read from XBee serial; return next complete packet or None.
        Backs off briefly if a send is in progress to avoid collisions.
        """
        if self._sending.is_set():
            time.sleep(0.001)
            return None

        with self._lock:
            buf[0] += sock.read(1024)   # non-blocking (timeout=0)

        return self.extract_packet(buf)


# ------------------------------------------------------------------ #
# UDP socket backend                                                  #
# ------------------------------------------------------------------ #

class SocketCom(Communication):
    """Communication over local UDP sockets (simulation / testing)."""

    def __init__(self, bind_ip: str = "127.0.0.1"):
        self.bind_ip = bind_ip
        self._interfaces: dict = {}

    # -- interface setup ------------------------------------------------

    def create_interface(self, interfaces: list) -> dict:
        for iface in interfaces:
            face = iface["face"]
            port = iface["port"]
            dst_port = iface["dst_port"]

            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setblocking(False)
            sock.bind((self.bind_ip, port))

            self._interfaces[face] = {
                "sock": sock,
                "face": face,
                "port": port,
                "dst_port": dst_port,
            }

        return self._interfaces

    # -- send / receive -------------------------------------------------

    def send_packet(self, sock, addr, packet_bytes: bytes):
        sock.sendto(packet_bytes, addr)

    def receive_packet(self, sock, buf: list):
        """
        Drain all pending UDP datagrams into the shared buffer,
        then extract and return the next complete packet (or None).
        """
        try:
            while True:
                data, _ = sock.recvfrom(2048)
                buf[0] += data
        except BlockingIOError:
            pass    # no more data right now

        return self.extract_packet(buf)