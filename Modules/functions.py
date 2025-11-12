import os 
# Suppress TensorFlow info/warning logs
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'  # 0=all, 1=info, 2=warning, 3=error
import sys

from mtcnn.mtcnn import MTCNN
import numpy as np
from PIL import Image
from io import BytesIO
  
TARGET_SIZE = (112, 112)  # Width x Height - Standard size for MobileFaceNet

# create a function that will allow functions.get_function(func_name)
def get_function(func_name: str):
    """Retrieve function by name."""
    functions_map = {
        "resize": resize,
        "detect": detect,
        "grayscale": grayscale,
        "orchestrate": orchestrate,
        "normalize": normalize,
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
    model = (model or "").lower()

    model_pipelines = {
        "insightface": ["detect", "resize", "normalize"],
        "openface": ["detect", "resize"],
        "mobilefacenet": ["detect", "grayscale", "resize", "normalize"],
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




#  testing
# node_functions_mapping =  {
#         "/dlsu/goks": ["detect", "resize"],
#         "/dlsu/andrew": ["grayscale", "resize"],
#         "/dlsu/velasco": ["embedding", "normalize"]
#     }
# interest_name = orchestrate("/dlsu/goks/cam/capture1.jpg", "openface", {}, node_functions_mapping)
# print("Generated Interest Name:", interest_name)