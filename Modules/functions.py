import os

import joblib 
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
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../ML-models/model3_mfn')))
from mobilefacenet import MobileFaceNet
import torchvision.transforms as transforms

MFN_SIZE = (112, 112)  # Width x Height - Standard size for MobileFaceNet
INSIGHTFACE_SIZE = (640, 640)  # Width x Height - Standard size for INSIGHT FACE
FACENET_SIZE = (160, 160) # Width x Height - Standard size for FaceNet
TARGET_SIZE = (160, 160)
# TARGET_SIZE = {
#    "insightface": (640, 640),
#   "facenet": (160, 160),
#   "mobilefacenet": (112, 112),
#}
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
        "detect": detect,
        "grayscale": grayscale,
        "orchestrate": orchestrate,
        "normalize": normalize,
        "insightface_embedding": insightface_embedding,
        "facenet_embedding": facenet_embedding,
        "mfn_embedding": mfn_embedding,
        "recognize": recognize,
    }
    return functions_map.get(func_name, None)
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
        np_img = img.astype(np.float32)
        np_img = (img - 127.5) / 128.0 
        #np_img = np.asarray(img).astype(np.float32) / 255.0
        #np_img = (np_img - 0.5) / 0.5  # normalize to [-1, 1]
        #np_img = np.asarray(img).astype(np.float32)
        #np_img = np_img / 255.0
        

        # Re-encode back to bytes (optional visualization)
        #np_img_disp = (np_img * 255).astype(np.uint8)
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
        "facenet": ["detect", "resize", "normalize", "facenet_embedding"],
        "mobilefacenet": ["detect","resize","normalize", "grayscale", "mfn_embedding"],
    }

    # Priority tiers:
    # Tier 1: goks (closest to camera)
    # Tier 2: andrew & velasco (same priority)
    priority_tiers = [
        ["/dlsu/goks"],            # Tier 1 (highest)
        ["/dlsu/andrew", "/dlsu/velasco"],  # Tier 2 (same priority)
    ]

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


    # Adjust tiers dynamically
    adjusted_priority_tiers = []
    for tier in priority_tiers:
        # Copy tier so we can modify
        new_tier = tier.copy()
        
        # Find node(s) in this tier that provide the embedding function
        nodes_with_embedding = [
            node for node in tier
            if node in function_to_nodes.get(model_pipelines[model][-1], [])
        ]
        # Move them to the end of the tier
        for node in nodes_with_embedding:
            new_tier.remove(node)
            new_tier.append(node)
        
        adjusted_priority_tiers.append(new_tier)

    priority_tiers = adjusted_priority_tiers

    # Group functions by node
    node_to_funcs = {}
    for func, node in assignments:
        node_to_funcs.setdefault(node, []).append(func)

    interest_expr = name  # start from base name
    # Build expression following priority order (innermost to outermost)
    for tier in priority_tiers:
        tier_functions = []

        # collect functions from nodes in this tier
        for node in tier:
            if node in node_to_funcs:
                tier_functions.extend([(node, func) for func in node_to_funcs[node]])

        # Group tier functions by node
        tier_node_groups = {}
        for node, func in tier_functions:
            tier_node_groups.setdefault(node, []).append(func)
        
        # Build nested functions per node (each node only wraps once)
        for node, funcs in tier_node_groups.items():
            # Nest functions inside this node
            segment = interest_expr
            for func in funcs:
                segment = f"{func}({segment})"

            # Apply the node wrapper ONCE
            interest_expr = f"{node}/{segment}"

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



# FACEBANK MANAGEMENT
def load_facebank():
    facebanks = {
        "insightface": "facebanks\\facebank_insightface.pt",
        "facenet": "facebanks\\facebank_facenet.pkl",
        "mobilefacenet": "facebanks\\facebank_mobilefacenet1.pkl",
    }

    for model, path in facebanks.items():
        if path is None or not os.path.exists(path):
            print(f"[ERROR] {model.upper()} Facebank not found at {path}.")
            continue

        if ".pkl" in path:
            data = joblib.load(path)
        else:
            data = torch.load(path)

        FACEBANKS[model] = {
            "names": data["names"],
            "embeddings": data["embeddings"]
        }
        print(f"[INFO] Loaded {model} facebank with {len(FACEBANKS[model]['names'])} identities.")

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

        result = {"label": best_label, "confidence": f"{round(confidence * 100, 2)}%"}
        return json.dumps(result).encode('utf-8')
    except Exception as e:
        print(f"[ERROR] Recognition failed: {e}")
        return np.array([])


# MODELS FUNCTIONS
insight_app = None
facenet_model = None
mfn_model = None

def resize_mfn(image_bytes: bytes) -> bytes:
    try:
        img = Image.open(BytesIO(image_bytes))
        format = img.format or "JPG"

        resized_img = img.resize(MFN_SIZE, Image.Resampling.LANCZOS)

        #encode back to bytes
        buf = BytesIO
        resized_img.save(buf, format=format)
        return buf.getvalue
    except Exception as e:
        print(f"[ERROR] Resized failed: {e}")
        return image_bytes #fallback
def resize_facenet(image_bytes: bytes) -> bytes:
    try:
        img = Image.open(BytesIO(image_bytes))
        format = img.format or "JPG"

        resized_img = img.resize(FACENET_SIZE, Image.Resampling.LANCZOS)

        #encode back to bytes
        buf = BytesIO
        resized_img.save(buf, format=format)
        return buf.getvalue
    except Exception as e:
        print(f"[ERROR] Resized failed: {e}")
        return image_bytes #fallback
def resize_insightface(image_bytes: bytes) -> bytes:
    try:
        img = Image.open(BytesIO(image_bytes))
        format = img.format or "JPG"

        resized_img = img.resize(INSIGHTFACE_SIZE, Image.Resampling.LANCZOS)

        #encode back to bytes
        buf = BytesIO
        resized_img.save(buf, format=format)
        return buf.getvalue
    except Exception as e:
        print(f"[ERROR] Resized failed: {e}")
        return image_bytes #fallback


def load_mfn():
    global mfn_model
    filename = "weights/mobilefacenet.pt"
    mfn_model = MobileFaceNet()
    mfn_model.load_state_dict(torch.load(filename, map_location="cpu"))
    mfn_model.eval()

def mfn_embedding(image_bytes: bytes) -> bytes:
    global mfn_model
    try:
        # Decode with OpenCV
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            print("[WARN] Failed to decode resized image.")
            return b''

        # BGR → RGB
        #img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

        # Resize
        #img = cv2.resize(img, (112, 112))

        img = img.astype(np.float32) / 255.0  
        img = (img - 0.5) / 0.5                

        # HWC → CHW
        img = np.transpose(img, (2, 0, 1))

        tensor = torch.from_numpy(img).unsqueeze(0).to(
            next(mfn_model.parameters()).device
        )

        # Forward pass
        with torch.no_grad():
            emb = mfn_model(tensor).cpu().numpy()[0]

        # L2 norm
        emb = emb / np.linalg.norm(emb)

        # Serialize
        buf = BytesIO()
        np.save(buf, emb)
        return buf.getvalue()

    except Exception as e:
        print(f"[ERROR] mfn_embedding: {e}")
        return b''




def load_facenet():
    #initialize model
    global facenet_model
    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    facenet_model = InceptionResnetV1(pretrained='vggface2').eval().to(device)

def facenet_embedding(image_bytes: bytes) -> bytes:
    global facenet_model, mt
    try:
        cropped_bytes = detect(image_bytes)
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            print("[WARN] Failed to decode resized image.")
            return b''
        #img = cv2.resize(img, (160, 160))
        #img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        img = img.astype(np.float32)
        img = (img - 127.5) / 128.0

        # 5. HWC → CHW
        img = np.transpose(img, (2, 0, 1))

        # 6. Add batch dimension and convert to tensor
        face_tensor = torch.from_numpy(img).unsqueeze(0).to(
            next(facenet_model.parameters()).device
        )

        # 7. Run through FaceNet
        with torch.no_grad():
            emb = facenet_model(face_tensor).cpu().numpy()[0]

        # 8. Normalize embedding
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
#         "/dlsu/andrew": ["mfn_embedding", "grayscale", "resize"],
#         "/dlsu/velasco": ["insightface_embedding", "facenet_embedding", "normalize"]
#     }

# interest_name = orchestrate("/dlsu/goks/cam/capture1.jpg", "insightface", {}, node_functions_mapping)
# print("Generated Interest Name:", interest_name)

