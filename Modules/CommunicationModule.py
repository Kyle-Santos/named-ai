import socket
import threading
import queue
from ParsingModule import PacketParser

class CommunicationModule:
    def __init__(self, host="127.0.0.1", port=9000):
        self.host = host
        self.port = port
        self.server_socket = None
        self.clients = []

        # FIFO Buffers
        self.receive_buffer = queue.Queue()   # Stores raw incoming packets
        self.send_buffer = queue.Queue()      # Stores outgoing packets 

    def start_server(self):
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.bind((self.host, self.port))
        self.server_socket.listen(5)
        print(f"[SERVER] Listening on {self.host}:{self.port}")

        while True:
            client_socket, addr = self.server_socket.accept()
            print(f"[SERVER] Connection from {addr}")
            self.clients.append(client_socket)
            threading.Thread(target=self.handle_client, args=(client_socket,), daemon=True).start()
            threading.Thread(target=self.process_buffer, daemon=True).start()

    def handle_client(self, client_socket):
        try:
            while True:
                data = client_socket.recv(4096)
                if not data:
                    break
                # Push to FIFO buffer
                self.receive_buffer.put(data)
        except Exception as e:
            print(f"[SERVER] Error: {e}")
        finally:
            client_socket.close()

    def process_buffer(self):
        while True:
            raw_packet = self.receive_buffer.get()  # FIFO pop
            try:
                parsed = PacketParser.parse(raw_packet)
                print(f"[SERVER] Parsed Packet: {parsed}")
            except Exception as e:
                print(f"[SERVER] Parsing Error: {e}")
            finally:
                self.receive_buffer.task_done()

    def send_packet(self, client_socket, packet_bytes):
        self.send_buffer.put(packet_bytes)  # Log into FIFO buffer
        client_socket.sendall(packet_bytes)

    def connect_to_server(self):
        client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client_socket.connect((self.host, self.port))
        return client_socket

if __name__ == "__main__":
    import sys
    mode = sys.argv[1] if len(sys.argv) > 1 else "server"

    comm = CommunicationModule()

    if mode == "server":
        comm.start_server()
    else:
        client = comm.connect_to_server()
        # Send Interest packet
        pkt1 = PacketParser.build_interest("/dlsu/goks/cam(img1)")
        comm.send_packet(client, pkt1)

        # Send Data packet
        pkt2 = PacketParser.build_data("/dlsu/andrew/detect",
                                       {"label": "Person", "confidence": 0.92})
        comm.send_packet(client, pkt2)
