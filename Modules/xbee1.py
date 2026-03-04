import serial

PORT = "/dev/tty.usbserial-AI02Z6GL"  # Change to the OTHER XBee
BAUD_RATE = 9600

ser = serial.Serial(PORT, BAUD_RATE, timeout=1)
print("Listening for wireless data...\n")

try:
    while True:
        if ser.in_waiting:
            data = ser.readline().decode(errors="ignore").strip()
            print("Received:", data)
except KeyboardInterrupt:
    ser.close()
    print("\nSerial closed.")
