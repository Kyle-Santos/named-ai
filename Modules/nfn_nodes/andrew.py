import sys
import os
from functions import detect_face, grayscale, resize

# Add parent directory to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from node_runner import run_node

if __name__ == "__main__":
    run_node("/dlsu/andrew")  # Use the exact name from node_config.json