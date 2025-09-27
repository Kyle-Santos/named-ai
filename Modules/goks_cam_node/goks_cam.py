import sys
import os

# Add parent directory to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from node_runner import run_node

NODE_NAME = "/dlsu/goks/cam"

if __name__ == "__main__":
    run_node(NODE_NAME)  # Use the exact name from node_config.json