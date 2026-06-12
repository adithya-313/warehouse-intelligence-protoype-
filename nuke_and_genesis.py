import os
import shutil
import subprocess

def run_cmd(cmd):
    print(f"> {cmd}")
    subprocess.run(cmd, shell=True, check=True)

def execute_genesis_commit():
    print("NUKING REPOSITORY HISTORY...")
    if os.path.exists(".git"):
        def remove_readonly(func, path, excinfo):
            os.chmod(path, 0o777)
            func(path)
        shutil.rmtree(".git", onerror=remove_readonly)

    print("INITIATING GENESIS COMMIT...")
    run_cmd("git init")
    run_cmd("git remote add origin https://github.com/adithya-313/prv3.git")
    run_cmd("git add .")
    run_cmd('git commit -F V1_RELEASE_COMMIT.txt')
    run_cmd("git branch -M main")

    print("PUSHING TO GITHUB...")
    run_cmd("git push -u origin main --force")

    os.remove("V1_RELEASE_COMMIT.txt")
    print("V1 GENESIS DEPLOYMENT COMPLETE.")

if __name__ == "__main__":
    execute_genesis_commit()
