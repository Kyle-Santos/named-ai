import subprocess

commands = [
    ["python", ".\\node_runner.py", "--node", "/dlsu/goks/cam"],
    ["python", ".\\node_runner.py", "--node", "/dlsu/goks"],
    ["python", ".\\node_runner.py", "--node", "/dlsu"],
    # ["python", ".\\node_runner.py", "--node", "/dlsu/andrew"],
    # ["python", ".\\node_runner.py", "--node", "/dlsu/velasco"],
    ["python", ".\\node_runner.py", "--client", "user", "--auto-send"],
    ["python", ".\\node_runner.py", "--client", "user2", "--auto-send"],
    ["python", ".\\node_runner.py", "--client", "user3", "--auto-send"],
    ["python", ".\\node_runner.py", "--client", "user4", "--auto-send"]
]

# List to keep track of running processes
processes = []

for cmd in commands:
    print(f"Starting: {' '.join(cmd)}")
    # Start the process without waiting
    proc = subprocess.Popen(cmd)
    processes.append(proc)

# Wait for all processes to finish
for proc in processes:
    proc.wait()

print("All scripts finished.")




# import subprocess

# commands = [
#     ["python", ".\\node_runner.py", "--node", "/dlsu/goks/cam"],
#     ["python", ".\\node_runner.py", "--node", "/dlsu/goks"],
#     ["python", ".\\node_runner.py", "--node", "/dlsu"],
#     ["python", ".\\node_runner.py", "--node", "/dlsu/andrew"],
#     ["python", ".\\node_runner.py", "--node", "/dlsu/velasco"],
#     ["python", ".\\node_runner.py", "--client", "user"],
# ]

# for cmd in commands:
#     # Join command into a string
#     cmd_str = " ".join(cmd)
#     print(f"Spawning terminal: {cmd_str}")
    
#     # Use 'start' to open a new cmd window and run the command
#     subprocess.Popen(f'start cmd /k {cmd_str}', shell=True)
