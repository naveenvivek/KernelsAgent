"""Minimal code-running agent. `generate_code` is a stub standing in for the LLM;
swap it for a real model call later. The sandbox is the part under test."""
import argparse, subprocess
from sandbox import DockerSandbox
from llm import write_code

# Stand-in for model-written code. The last one is what an injected prompt might produce.
TASKS = {
    "kernel": "import platform; print('kernel seen by code:', platform.release())",
    "sum":    "print(sum(i*i for i in range(10**6)))",
    "files":  "import os\nfor p in ['/proc/version','/etc/hostname']:\n print(p, open(p).read().strip())",
    "escape-probe": ("import os,socket\n"
                     "print('uid', os.getuid())\n"
                     "try: socket.create_connection(('1.1.1.1',53),2); print('NETWORK OPEN')\n"
                     "except Exception as e: print('network blocked:', e)\n"
                     "try: open('/etc/pwned','w'); print('ROOTFS WRITABLE')\n"
                     "except Exception as e: print('rootfs read-only:', e)"),
}

def generate_code(task: str) -> str:
    return TASKS[task]

def host_kernel():
    return subprocess.run(["docker", "info", "--format", "{{.KernelVersion}}"],
                          capture_output=True, text=True).stdout.strip()

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--runtime", default="runc", choices=["runc", "gvisor", "kata"])
    ap.add_argument("--task", default="kernel", choices=TASKS)
    ap.add_argument("--ask", help="free-text request; a local LLM writes the code")
    ap.add_argument("--llm", default="ollama", choices=["ollama", "lmstudio"])
    a = ap.parse_args()
    print("docker host kernel:", host_kernel())
    code = write_code(a.ask, a.llm) if a.ask else generate_code(a.task)
    if a.ask:
        print("--- model wrote ---")
        print(code)
        print("-------------------")
    r = DockerSandbox(a.runtime).run(code)
    print(f"[{r['runtime']}] exit={r['exit']}\n{r['stdout']}\n{r['stderr']}".rstrip())
