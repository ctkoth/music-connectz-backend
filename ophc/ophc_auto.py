import os
import subprocess
import time

LOG_FILE = os.path.join(os.path.dirname(__file__), 'ophc.log')

# --- Config ---
BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
GIT_CMDS = [
    'git status',
    'git add .',
    'git commit -am "OPHC auto-commit"',
    'git pull --rebase',
    'git push'
]

# --- Logging ---
def log(msg):
    with open(LOG_FILE, 'a') as f:
        f.write(f"[{time.ctime()}] {msg}\n")
    print(msg)

# --- Main Automation ---
def run_git_automation():
    os.chdir(BACKEND_DIR)
    # Ensure ophc.log is not staged or committed
    if os.path.exists('ophc/ophc.log'):
        subprocess.run('git update-index --assume-unchanged ophc/ophc.log', shell=True)
    for cmd in GIT_CMDS:
        # Skip ophc.log from add/commit
        if 'git add' in cmd:
            cmd = 'git add . && git reset ophc/ophc.log'
        if 'git commit' in cmd:
            cmd = 'git commit -am "OPHC auto-commit" || echo "Nothing to commit"'
        log(f"Running: {cmd}")
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        log(result.stdout)
        if result.stderr:
            log(f"ERROR: {result.stderr}")
        if result.returncode != 0:
            log(f"Command failed: {cmd}")
            break
    log("--- OPHC git automation complete ---")

if __name__ == "__main__":
    run_git_automation()
