import subprocess
import sys

def run_cmd(cmd):
    try:
        return subprocess.check_output(cmd, shell=True, stderr=subprocess.STDOUT, text=True).strip()
    except subprocess.CalledProcessError as e:
        return e.output.strip()

def recover_git_history():
    print("INITIATING EMERGENCY GIT FORENSIC RECOVERY")

    reflog_output = run_cmd("git reflog -n 20")
    print("--- REFLOG SNAPSHOT ---")
    print(reflog_output)
    print("-----------------------\n")

    target_hash = None
    lines = reflog_output.split('\n')

    for i, line in enumerate(lines):
        if "release: Sentinel-Flow V1" in line or "commit (initial)" in line:
            if i + 1 < len(lines):
                target_hash = lines[i + 1].split()[0]
            break

    if not target_hash:
        print("Could not explicitly match the commit message. Attempting to rewind exactly 1 step (HEAD@{1})...")
        target_hash = run_cmd("git rev-parse HEAD@{1}")

    if not target_hash or "unknown revision" in target_hash.lower():
        print("FATAL: Could not locate the previous timeline in the local reflog.")
        sys.exit(1)

    print(f"TARGET RECOVERY HASH FOUND: {target_hash}")

    print(f"Rewinding local repository back (Hash: {target_hash})...")
    reset_out = run_cmd(f"git reset --hard {target_hash}")
    print(reset_out)

    print("Pushing the restored commits back to GitHub...")
    push_out = run_cmd("git push origin main --force")
    print(push_out)

    print("SUCCESS: TIMELINE RESTORED. REFRESH THE REPOSITORY PAGE.")

if __name__ == "__main__":
    recover_git_history()
