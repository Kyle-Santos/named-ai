import sys
import os

# Add parent directory to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from node_runner import run_client

NODE_NAME = "client"
interest_name="/dlsu/goks/cam/capture8.jpg"
# interest_name="/dlsu/goks/detect(/dlsu/goks/cam/capture8.jpg)"

if __name__ == "__main__":
    run_client(NODE_NAME, interest_name)  # Use the exact name from node_config.json