import os 
# Suppress TensorFlow info/warning logs
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'  # 0=all, 1=info, 2=warning, 3=error
import sys

from mtcnn.mtcnn import MTCNN
import numpy as np
from PIL import Image
from io import BytesIO

# for INSIGHTFACE
import cv2
import torch
import json
from insightface.app import FaceAnalysis

#for facenet
import joblib
from collections import Counter
from facenet_pytorch import InceptionResnetV1

#for MFN
from MobileFaceNet.mobilefacenet import MobileFaceNet

# TARGET_SIZE = (112, 112)  # Width x Height - Standard size for MobileFaceNet
TARGET_SIZE = (640, 640)  # Width x Height - Standard size for INSIGHT FACE

CHOSEN_MODEL = None

FACEBANKS = {
    "insightface": None,
    "facenet": None,
    "mobilefacenet": None,
}

# create a function that will allow functions.get_function(func_name)
def get_function(func_name: str):
    """Retrieve function by name."""
    functions_map = {
        "resize": resize,
        "detect": detect,
        "grayscale": grayscale,
        "orchestrate": orchestrate,
        "normalize": normalize,
        "insightface_embedding": insightface_embedding,
        "recognize": recognize,
    }
    return functions_map.get(func_name, None)

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


def normalize(image_bytes: bytes) -> bytes:
    """
    Preprocess image for face embedding models (InsightFace, OpenFace, MobileFaceNet).
    Converts to RGB and normalizes to [-1, 1].

    Args:
        image_bytes (bytes): Input image (JPEG/PNG).
    
    Returns:
        bytes: Normalized image re-encoded as bytes (for inspection) or numpy array (for inference).
    """
    try:
        img = Image.open(BytesIO(image_bytes)).convert("RGB")

        # Convert to NumPy array (HWC)
        np_img = np.asarray(img).astype(np.float32) / 255.0
        np_img = (np_img - 0.5) / 0.5  # normalize to [-1, 1]

        # Re-encode back to bytes (optional visualization)
        np_img_disp = ((np_img + 1) * 127.5).astype(np.uint8)
        buf = BytesIO()
        Image.fromarray(np_img_disp).save(buf, format=img.format or "JPEG")
        return buf.getvalue()
    except Exception as e:
        print(f"[ERROR] Normalization failed: {e}")
        return image_bytes
    

def orchestrate(name: str, model, PIT, functions_mapping) -> str:
    """Build an NFN Interest string for the requested recognition pipeline."""
    global CHOSEN_MODEL
    model = (model or "").lower()
    CHOSEN_MODEL = model

    model_pipelines = {
        "insightface": ["resize", "normalize", "insightface_embedding"],
        "openface": ["detect", "resize", "openface_embedding"],
        "mobilefacenet": ["detect", "grayscale", "resize", "normalize", "mfn_embedding"],
    }

    # order of nearest to camera
    inorder_priority_nodes = ["/dlsu/goks", "/dlsu/andrew", "/dlsu/velasco"]

    if model not in model_pipelines:
        raise ValueError(f"Unsupported model '{model}'")

    required_functions = model_pipelines[model]

    function_to_nodes = {}
    for node_name, funcs in functions_mapping.items():
        for func in funcs:
            function_to_nodes.setdefault(func, []).append(node_name)

    assignments = []
    for func in required_functions:
        candidates = function_to_nodes.get(func, [])
        if not candidates:
            raise ValueError(f"No available node provides '{func}'")
        chosen_node = _select_node_for_function(candidates, func, PIT or {})
        assignments.append((func, chosen_node))

    # Group functions by node
    node_to_funcs = {}
    for func, node in assignments:
        node_to_funcs.setdefault(node, []).append(func)

    # Build expression following priority order (innermost to outermost)
    interest_expr = name
    for node in inorder_priority_nodes:
        if node in node_to_funcs:
            interest_expr = _build_segment_expression(node, node_to_funcs[node], interest_expr)

    return interest_expr


def _select_node_for_function(candidates, func, PIT):
    for node in candidates:
        if not _is_node_busy(node, func, PIT):
            return node
    return candidates[0]


def _is_node_busy(node, func, PIT):
    indicator = f"{node}/{func}"
    for interest_name, entry in PIT.items():
        if indicator in interest_name:
            return True
        funcs = entry.get("funcs") if isinstance(entry, dict) else None
        if funcs and func in funcs and interest_name.startswith(node):
            return True
    return False


def _build_segment_expression(node, funcs, inner_expr):
    if not node:
        raise ValueError("Node assignment missing for function segment")
    if not funcs:
        return inner_expr

    segment_expr = inner_expr
    for func in funcs:
        segment_expr = f"{func}({segment_expr})"

    return f"{node}/{segment_expr}"



# FACEBANK MANAGEMENT
def load_facebank():
    facebanks = {
        "insightface": "facebanks\\facebank_insightface.pt",
        "facenet": None,
        "mobilefacenet": None,
    }

    for model, path in facebanks.items():
        if path is None or not os.path.exists(path):
            print(f"[ERROR] {model.upper()} Facebank not found at {path}.")
            continue
        data = torch.load(path)
        FACEBANKS[model] = {
            "names": data["names"],
            "embeddings": data["embeddings"]
        }
        print(f"[INFO] Loaded facebank with {len(FACEBANKS[model]['names'])} identities.")

# recognize
def recognize(data_bytes: bytes):
    """
    Args:
        embeddings: numpy binary
    Returns:
        bytes: JSON result with label and confidence
    """
    global CHOSEN_MODEL
    k = 3  # top-k  
    threshold = 0.65  # similarity threshold
    facebank_embeddings = FACEBANKS[CHOSEN_MODEL.lower()]["embeddings"] 
    facebank_names = FACEBANKS[CHOSEN_MODEL.lower()]["names"]

    try:
        # Deserialize embedding from bytes
        try:
            # Try JSON first (Option 1)
            embedding_dict = json.loads(data_bytes.decode('utf-8'))
            if "error" in embedding_dict:
                return json.dumps({"label": "Error", "confidence": 0.0, "error": embedding_dict["error"]}).encode('utf-8')
            embedding = np.array(embedding_dict["embedding"])
        except (json.JSONDecodeError, UnicodeDecodeError):
            # Try numpy binary format (Option 2)
            buf = BytesIO(data_bytes)
            embedding = np.load(buf)
        
        if embedding is None or len(embedding) == 0:
            return json.dumps({"label": "No embedding", "confidence": 0.0}).encode('utf-8')

        # Normalize embedding
        embedding = embedding / np.linalg.norm(embedding)

        if isinstance(facebank_embeddings, torch.Tensor):
            facebank_embeddings = facebank_embeddings.cpu().numpy()

        facebank_embeddings = facebank_embeddings / np.linalg.norm(facebank_embeddings, axis=1, keepdims=True)

        sims = np.dot(facebank_embeddings, embedding)
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
    except Exception as e:
        print(f"[ERROR] Recognition failed: {e}")
        return np.array([])


# MODELS FUNCTIONS
insight_app = None
facenet_mtcnn = None
facenet_model = None
mfn_model = None

def load_mfn():
    MODEL_PATH = 'mobilefacenet.pt'
    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    mfn_model = MobileFaceNet().to(device)
    mfn_model.load_state_dict(torch.load(MODEL_PATH, map_location=device))
    mfn_model.eval

def mfn_embedding(image_bytes: bytes) -> bytes:
    try:
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            print("[WARN] Failed to decode resized image.")
            return b''
        with torch.no_grad():
            emb = mfn_model(img.unsqueeze(0)).cpu().numpy()[0]
        buf = BytesIO()
        np.save(buf, emb)
        return buf.getvalue()
    
    except Exception as e:
        print(f"[ERROR] mfn_embedding: {e}")
        return b''

def load_facenet():
    #initialize model
    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    facenet_mtcnn = MTCNN(image_size=160, margin=20, device = device)
    facenet_model = InceptionResnetV1(pretrained='vggface2').eval().to(device)

def facenet_embedding(image_bytes: bytes) -> bytes:
    try:
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            print("[WARN] Failed to decode resized image.")
            return b''
    
        with torch.no_grad():
            emb = facenet_model(img.unsqueeze(0)).cpu().numpy()[0]

        #normalize emb
        emb = emb / np.linalg.norm(emb)

        #serialize
        buf = BytesIO()
        np.save(buf, emb)

        return buf.getvalue()
    
    except Exception as e:
        print(f"[ERROR] facenet_embedding: {e}")
        return b''
    


    

def load_insightface():
    global insight_app  
    # ArcFace Model Initialization
    insight_app = FaceAnalysis(providers=['CUDAExecutionProvider', 'CPUExecutionProvider'])
    insight_app.prepare(ctx_id=0, det_size=(640, 640))

def insightface_embedding(image_bytes: bytes) -> bytes:
    """
    Args:
        image_bytes (bytes): input image data
    Returns:
        np.ndarray: normalized 512D embedding, or None if failed
    """
    try:
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            print("[WARN] Failed to decode resized image.")
            return b''

    
        # --- Get ArcFace embedding ---
        faces = insight_app.get(img)
        if len(faces) == 0:
            print("[WARN] No face detected in resized image.")
            return b''

        emb = np.array(faces[0]['embedding'])
        emb = emb / np.linalg.norm(emb)

        # Serialize as bytes using numpy
        buf = BytesIO()
        np.save(buf, emb)

        return buf.getvalue()
    except Exception as e:
        print(f"[ERROR] insightface_embedding: {e}")
        return b''


#  testing
# node_functions_mapping =  {
#         "/dlsu/goks": ["detect", "resize"],
#         "/dlsu/andrew": ["grayscale", "resize"],
#         "/dlsu/velasco": ["embedding", "normalize"]
#     }
# interest_name = orchestrate("/dlsu/goks/cam/capture1.jpg", "openface", {}, node_functions_mapping)
# print("Generated Interest Name:", interest_name)