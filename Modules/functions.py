import os 
# Suppress TensorFlow info/warning logs
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'  # 0=all, 1=info, 2=warning, 3=error
import sys

from mtcnn.mtcnn import MTCNN
import numpy as np
from PIL import Image
from io import BytesIO
  
TARGET_SIZE = (112, 112)  # Width x Height - Standard size for MobileFaceNet

def resize(image_bytes: bytes) -> bytes:
    """
    Resize an image (bytes) to TARGET_SIZE and return encoded bytes.
    
    Args:
        image_bytes (bytes): Input image data (JPEG/PNG/etc.)
    
    Returns:
        bytes: Resized image as encoded bytes.
    """
    try:
        # Decode image
        img = Image.open(BytesIO(image_bytes))
        format = img.format or "JPG"

        # Resize
        resized_img = img.resize(TARGET_SIZE, Image.Resampling.LANCZOS)

        # Encode back to bytes
        buf = BytesIO()
        resized_img.save(buf, format=format)
        return buf.getvalue()

    except Exception as e:
        print(f"[ERROR] Resize failed: {e}")
        return image_bytes  # fallback

# Redirect stderr to null temporarily
stderr_fileno = sys.stderr
sys.stderr = open(os.devnull, "w")


detector = None

def load_mtcnn():
    global detector
    try:
        print("[INFO] Loading face detector model...")
        detector = MTCNN()
        print("[INFO] Face detector model loaded successfully.")
    except Exception as e:
        print(f"[ERROR] Could not load MTCNN model: {e}")


def detect(image_bytes: bytes) -> bytes:
    """
    Detects a face and returns the cropped whole face as encoded image bytes.
    
    Args:
        image_bytes (bytes): Input image data (JPEG/PNG/etc.)
    
    Returns:
        bytes: Cropped face as encoded bytes (same format as input), or original bytes if no face detected.
    """
    if detector is None:
        print("[ERROR] Face detector not available")
        return image_bytes

    try:
        # Decode image
        img = Image.open(BytesIO(image_bytes))
        format = img.format or "PNG"
        img = img.convert("RGB")  # ensure 3-channel

        # Convert to numpy for MTCNN
        image_np = np.asarray(img)

        # detect face
        faces = detector.detect_faces(image_np)
        if not faces:
            print("[INFO] No face detected, returning original")
            return image_bytes  # No face detected

        face_data = faces[0]  # Assume one face per image for simplicity
        x, y, width, height = [int(abs(v)) for v in face_data['box']]

        # Ensure box coordinates are within image bounds
        x, y = max(0, x), max(0, y)
        x2 = min(x + width, img.width)
        y2 = min(y + height, img.height)

        # Crop face
        cropped_face = img.crop((x, y, x2, y2))

        # Encode back to bytes
        buf = BytesIO()
        cropped_face.save(buf, format=format)
        return buf.getvalue()

    except Exception as e:
        print(f"[ERROR] Face processing failed: {e}")
        return image_bytes  # fallback
    

def grayscale(image_bytes: bytes) -> bytes:
    """
    Convert an image (bytes) to grayscale and return new image bytes.
    
    Args:
        image_bytes (bytes): Input image data (e.g., reassembled JPEG/PNG).
        output_format (str): Format to encode output ("JPEG", "PNG", etc.).
    
    Returns:
        bytes: Grayscaled image as encoded bytes.
    """
    try:
        # Decode from bytes
        img = Image.open(BytesIO(image_bytes))
        format = img.format

        # Convert to grayscale
        gray_img = img.convert("L")   # "L" = 8-bit grayscale

        # Encode back to bytes
        buf = BytesIO()
        gray_img.save(buf, format=format)
        return buf.getvalue()
    except Exception as e:
        print(f"[ERROR] Grayscale conversion failed: {e}")
        return image_bytes  # fallback: return original
    

