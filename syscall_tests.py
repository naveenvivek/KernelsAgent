"""Shared test-case definitions for the syscall demo. Not run directly —
run `syscall_demo_runc.py` or `syscall_demo_gvisor.py`, each runs these same
4 cases against its own single runtime so the two results can be compared."""
import subprocess, uuid
from sandbox import DockerSandbox, DOCKER

IMAGE = "python:3.12-slim"


def host_kernel():
    return subprocess.run(["docker", "info", "--format", "{{.KernelVersion}}"],
                          capture_output=True, text=True).stdout.strip()


def run_unhardened(rt, code, timeout=15):
    """Same as DockerSandbox.run, but keeps Docker's DEFAULT capabilities
    (no --cap-drop ALL, no --read-only, no --user) so cases 3/4 show what
    each runtime blocks on its own, not what --cap-drop already blocked.
    Network stays 'none' and resources stay capped for safety."""
    cname = "sbx-unhardened-" + uuid.uuid4().hex[:8]
    cmd = [*DOCKER[rt], "run", "--rm", "-i", "--name", cname,
           "--network", "none", "--memory", "256m", "--cpus", "1",
           "--pids-limit", "128"]
    if rt == "gvisor":
        cmd += ["--runtime", "runsc"]
    cmd += [IMAGE, "python", "-"]
    try:
        p = subprocess.run(cmd, input=code, capture_output=True, text=True, timeout=timeout)
        return {"runtime": rt, "exit": p.returncode, "stdout": p.stdout.strip(), "stderr": p.stderr.strip()}
    except subprocess.TimeoutExpired:
        subprocess.run([*DOCKER[rt], "kill", cname], capture_output=True)
        return {"runtime": rt, "exit": -1, "stdout": "", "stderr": "timeout"}


def available(rt):
    try:
        cmd = [*DOCKER[rt], "info"] if rt == "runc" else [*DOCKER[rt], "info", "--format", "{{json .Runtimes}}"]
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return p.returncode == 0 and (rt == "runc" or "runsc" in p.stdout)
    except Exception:
        return False


# testcase -> (label, code, host-aware note(result, host_kernel) -> str, hardened: bool)
# hardened=True  -> runs through DockerSandbox (--cap-drop ALL, --read-only, non-root)
# hardened=False -> runs via run_unhardened (Docker's default caps/user), so the
#                    runc-vs-gVisor gap shows even when nobody hardened the container

TESTCASES = {

"testcase1_kernel_fingerprint": (
    "Kernel fingerprinting (/proc/version, platform.release)",
    "import platform\n"
    "print('uname release:', platform.release())\n"
    "print('proc/version :', open('/proc/version').read().strip())",
    lambda r, h: "matches real host kernel" if h in r["stdout"] else "does NOT match host kernel (fake/virtualized)",
    True
),

"testcase2_proc_sys_leak": (
    "/proc, /sys host info leakage (cpuinfo, meminfo, real core count)",
    "import os\n"
    "cpu = open('/proc/cpuinfo').read()\n"
    "model = next((l for l in cpu.splitlines() if 'model name' in l), 'model name: (hidden)')\n"
    "cores = cpu.count('processor\\t:')\n"
    "mem = next((l for l in open('/proc/meminfo') if l.startswith('MemTotal')), 'MemTotal: (hidden)')\n"
    "print(model.strip())\nprint('cores seen:', cores)\nprint(mem.strip())",
    lambda r, h: "informational — compare core count / model shown on each runtime below",
    True
),

"testcase3_unshare_mount": (
    "unshare() and mount() — run WITHOUT --cap-drop, to show each runtime's own limit",
    "import ctypes\n"
    "l = ctypes.CDLL(None, use_errno=True)\n"
    "u = l.unshare(0x10000000)  # CLONE_NEWNET\n"
    "print('unshare ret:', u, 'errno:', ctypes.get_errno())\n"
    "m = l.mount(b'none', b'/tmp', b'tmpfs', 0, None)\n"
    "print('mount ret  :', m, 'errno:', ctypes.get_errno())",
    lambda r, h: "both denied (-1)" if r["stdout"].count("-1") >= 2 else "one or both SUCCEEDED (default caps allowed it)",
    False
),

"testcase4_ptrace_rawsocket_iouring": (
    "ptrace-on-self, raw socket, io_uring — WITHOUT --cap-drop (optional/advanced)",
    "import ctypes, socket, os\n"
    "l = ctypes.CDLL(None, use_errno=True)\n"
    "pid = os.fork()\n"
    "if pid == 0:\n"
    "    import time; time.sleep(2); os._exit(0)\n"
    "else:\n"
    "    r = l.ptrace(16, pid, 0, 0)  # PTRACE_ATTACH\n"
    "    print('ptrace ret:', r, 'errno:', ctypes.get_errno())\n"
    "try:\n"
    "    socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP)\n"
    "    print('raw socket: OPENED')\n"
    "except Exception as e:\n"
    "    print('raw socket: denied', e)\n"
    "r2 = l.syscall(425, 1)  # io_uring_setup\n"
    "print('io_uring ret:', r2, 'errno:', ctypes.get_errno())",
    lambda r, h: "informational — see per-line result below",
    False
),

}


def run_for(rt):
    """Run all test cases for a single runtime and print the results.
    Shared by syscall_demo_runc.py and syscall_demo_gvisor.py."""
    print(f"[setup] checking whether runtime '{rt}' is reachable ...")
    if not available(rt):
        print(f"[setup] '{rt}' is NOT reachable — its dockerd is likely not running.")
        if rt == "gvisor":
            print("[setup] start it with: wsl -d Ubuntu -u root -- bash setup-gvisor.sh")
        return
    h = host_kernel()
    print(f"[setup] host kernel : {h}")
    print(f"[setup] runtime     : {rt}\n")

    for key, (label, code, note, hardened) in TESTCASES.items():
        mode = "hardened (cap-drop ALL, read-only, non-root)" if hardened else "UNHARDENED (Docker default caps/user)"
        print("=" * 70)
        print(key, "-", label)
        print("mode:", mode)
        print("=" * 70)
        print(f"[run] starting container on '{rt}' ...")
        r = DockerSandbox(rt).run(code) if hardened else run_unhardened(rt, code)
        print(f"[run] container on '{rt}' finished, exit={r['exit']}")
        print(f"\n[{rt}] stdout:")
        print(r["stdout"] or "(no stdout)")
        if r["stderr"]:
            print(f"[{rt}] stderr:", r["stderr"][:300])
        print(f"[{rt}] verdict ->", note(r, h))
        print()
