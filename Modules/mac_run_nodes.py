import sys
import subprocess

python = sys.executable  # automatically uses Python 3.11 if that's what you ran

commands = [
    # [python, "./node_runner.py", "--node", "/dlsu/goks/cam"],
    # [python, "./node_runner.py", "--node", "/dlsu/goks"],
    # [python, "./node_runner.py", "--node", "/dlsu"],
    # [python, "./node_runner.py", "--node", "/dlsu/andrew"],
    # [python, "./node_runner.py", "--node", "/dlsu/velasco"],
    [python, "./node_runner.py", "--client", "user", "--auto-send"],
    # [python, "./node_runner.py", "--client", "user2", "--auto-send"],
    # [python, "./node_runner.py", "--client", "user3", "--auto-send"],
    # [python, "./node_runner.py", "--client", "user4", "--auto-send"],
]

processes = []
for cmd in commands:
    print(f"Starting: {' '.join(cmd)}")
    proc = subprocess.Popen(cmd)
    processes.append(proc)

for proc in processes:
    proc.wait()

print("All scripts finished.")
