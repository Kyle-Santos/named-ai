import NamedAI as NN  

def run_node(bind_port=9000):
    sock = NN.create_udp_socket(bind_port=bind_port)
    print(f"Node running on UDP port {bind_port}")

    while True:
        raw_packet, addr = NN.receive_packet(sock)
        parsed, err = NN.parse_packet(raw_packet)

        print(f'\nPacket Received From {addr}')
        print(parsed)
        if err:
            print(f"Error: {err}")
            continue
        
        if parsed["type"] == "interest":
            NN.process_interest(parsed, addr, sock)
        elif parsed["type"] == "data":
            NN.process_data(parsed, sock)
        else:
            print("Unknown packet type received")


if __name__ == "__main__":
    run_node()
