import os 
# Suppress TensorFlow info/warning logs
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'  # 0=all, 1=info, 2=warning, 3=error
import sys
import cv2
import torch
import json
import insightface
from insightface.app import FaceAnalysis
from collections import Counter
from mtcnn.mtcnn import MTCNN
import numpy as np
from PIL import Image
from io import BytesIO
  
TARGET_SIZE = (640, 640)  # Width x Height - Standard size for MobileFaceNet

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

print("[INFO] Loading face detector model...")
# Redirect stderr to null temporarily
stderr_fileno = sys.stderr
sys.stderr = open(os.devnull, "w")

try:
    detector = MTCNN()
    print("[INFO] Face detector model loaded successfully.")
except Exception as e:
    print(f"[ERROR] Could not load MTCNN model: {e}")
    detector = None
finally:
    sys.stderr.close()
    sys.stderr = stderr_fileno

def detect_face(image_bytes: bytes) -> bytes:
    """
    Detects a face and returns the cropped whole face as encoded image bytes.
    
    Args:
        image_bytes (bytes): Input image data (JPEG/PNG/etc.)
    
    Returns:
        bytes: Cropped face as encoded bytes (same format as input), or original bytes if no face detected.
    """
    
    if detector is None:
        print("[ERROR] Detector not available. Cannot process image.")
        return None
    try:
        # Decode image
        img = Image.open(BytesIO(image_bytes)).convert("RGB")
        format = img.format or "PNG"

         # Convert to numpy for MTCNN
        image_np = np.asarray(img)

        # detect face
        faces = detector.detect_faces(image_np)
        if not faces:
            print("[INFO] No face detected, returning original")
            return None  # No face detected

        face_data = faces[0]  # Assume one face per image for simplicity
        x, y, width, height = face_data['box']

        # Ensure box coordinates are within image bounds
        x, y = max(0, x), max(0, y)

        # Crop face
        cropped_face = img.crop((x, y, x + width, y + height))

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
    

# ArcFace Model Initialization
app = FaceAnalysis(providers=['CUDAExecutionProvider', 'CPUExecutionProvider'])
app.prepare(ctx_id=0, det_size=(640, 640))

# FACEBANK MANAGEMENT

def load_facebank(path="facebank.pt"):
    if not os.path.exists(path):
        print(f"[ERROR] Facebank not found at {path}.")
        return None, None
    data = torch.load(path)
    print(f"[INFO] Loaded facebank with {len(data['names'])} identities.")
    return data["names"], data["embeddings"]


#embedding extraction
def extract_arcface_embedding(image_bytes):
    """
    Args:
        image_bytes (bytes): input image data
    Returns:
        np.ndarray: normalized 512D embedding, or None if failed
    """

    try:
        resized_bytes = resize(image_bytes)
        if resized_bytes is None:
            print("[WARN] Resize preprocessing failed.")
            return None

        nparr = np.frombuffer(resized_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            print("[WARN] Failed to decode resized image.")
            return None

        # --- Step 3: Get ArcFace embedding ---
        faces = app.get(img)
        if len(faces) == 0:
            print("[WARN] No face detected in resized image.")
            return None

        emb = np.array(faces[0]['embedding'])
        emb = emb / np.linalg.norm(emb)
        return emb

    except Exception as e:
        print(f"[ERROR] extract_arcface_embedding_resized: {e}")
        return None
    
#recog
def recognize_from_embedding(test_emb, facebank_names, facebank_embeddings, k=3, threshold=0.5):
    if test_emb is None:
        return json.dumps({"label": "No embedding", "confidence": 0.0}).encode('utf-8')

    if isinstance(facebank_embeddings, torch.Tensor):
        facebank_embeddings = facebank_embeddings.cpu().numpy()

    facebank_embeddings = facebank_embeddings / np.linalg.norm(facebank_embeddings, axis=1, keepdims=True)

    sims = np.dot(facebank_embeddings, test_emb)
    topk_idxs = np.argsort(sims)[-k:][::-1]
    topk_labels = [facebank_names[i] for i in topk_idxs]
    topk_sims = sims[topk_idxs]

    from collections import Counter
    best_label = Counter(topk_labels).most_common(1)[0][0]
    confidence = float(np.mean([s for s, l in zip(topk_sims, topk_labels) if l == best_label]))

    if confidence < threshold:
        best_label = "Unknown"

    result = {"label": best_label, "confidence": confidence}
    return json.dumps(result).encode('utf-8')

def resized_recog(image_bytes, facebank_names, facebank_embeddings, k=3, threshold = 0.5):
    emb = extract_arcface_embedding(image_bytes)
    return recognize_from_embedding(emb, facebank_names, facebank_embeddings, k=k, threshold=threshold)


if __name__ == "__main__":
    names, embeddings = load_facebank()

    with open("test_images/Akshay_Kumar_44.jpg", "rb") as f:
        img_bytes = f.read()

    result_bytes = resized_recog(img_bytes, names, embeddings)
    print(result_bytes.decode('utf-8'))