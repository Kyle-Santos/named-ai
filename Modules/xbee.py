import serial
import time

# === SERIAL PORT CONFIG ===
# PORT = "/dev/tty.usbserial-00000000"   # Mac/Linux
PORT = "/dev/tty.usbserial-AI02Z6GL"
# PORT = "COM10"                       # Windows example

BAUD_RATE = 9600
BYTESIZE = serial.EIGHTBITS
PARITY = serial.PARITY_NONE
STOPBITS = serial.STOPBITS_ONE
TIMEOUT = 0  # seconds

def open_serial():
    ser = serial.Serial(
        port=PORT,
        baudrate=BAUD_RATE,
        bytesize=BYTESIZE,
        parity=PARITY,
        stopbits=STOPBITS,
        timeout=TIMEOUT
    )
    return ser

def send_command(ser, command, delay=1):
    """
    Sends AT command and prints response
    """
    full_command = command + "\r"
    ser.write(full_command.encode())
    time.sleep(delay)

    response = ser.read_all().decode(errors="ignore")
    print(f"Sent: {command}")
    print(f"Received: {response.strip()}\n")

def main():
    try:
        ser = open_serial()
        print(f"Connected to {PORT}\n")

        # Enter AT command mode for XBee
        print("Entering AT mode...")
        time.sleep(1)
        for i in range(1, 6):
            ser.write(b" Hello World! This is test file for testing the capability of the NamedAI protocol using Xbee Transceivers"
            # b"Hello World! This is test file for testing the capability of the NamedAI protocol using Xbee Transceivers"
            b"Hello World! This is test file for testing the capability of the NamedAI protocol using Xbee Transceivers\n" + str(i).encode())
            time.sleep(0.01)

        # Example AT commands
        # send_command(ser, "AT")        # Check communication
        # send_command(ser, "ATVR")      # Firmware version
        # send_command(ser, "ATMY")      # Device address
        # send_command(ser, "ATDL")      # Destination address

        # # Exit AT mode
        # send_command(ser, "ATCN")

        ser.close()
        print("Serial connection closed.")

    except serial.SerialException as e:
        print(f"Serial error: {e}")

if __name__ == "__main__":
    main()
