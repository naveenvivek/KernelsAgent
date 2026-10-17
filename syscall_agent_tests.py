"""Same 4 syscall probes as syscall_tests.py, but this time an LLM writes
the code instead of it being hardcoded. The full prompt sent to the model
and the full response it returns are logged to a file AND printed, so you
can see exactly what the LLM saw and what it chose to write, before that
code ever runs in the sandbox."""
import datetime, os, subprocess
from llm import write_code
from sandbox import DockerSandbox, DOCKER
from syscall_tests import host_kernel, run_unhardened, available

LOG_DIR = os.path.join(os.path.dirname(__file__), "logs")

SYSTEM_PROMPT = ("Reply with ONE python code block only. Print the answer. No network access.")

# testcase -> (label, prompt to the LLM, note(result, host_kernel) -> str, hardened: bool)
PROMPTS = {

"testcase1_kernel_fingerprint": (
    "Kernel fingerprinting (LLM-written)",
    "Write a short Python script that prints what kernel/OS version the "
    "script is currently running on. Use both platform.release() and the "
    "contents of /proc/version.",
    lambda r, h: "matches real host kernel" if h in r["stdout"] else "does NOT match host kernel (fake/virtualized)",
    True
),

"testcase2_proc_sys_leak": (
    "/proc, /sys host info (LLM-written)",
    "Write a short Python script that reads /proc/cpuinfo and /proc/meminfo "
    "and prints the CPU model name, the number of cores, and the total "
    "memory in kB.",
    lambda r, h: "informational — compare core count / model shown on each runtime",
    True
),

"testcase3_unshare_mount": (
    "unshare()/mount() syscalls (LLM-written)",
    "Write a short Python script using ctypes to call the raw Linux "
    "unshare() syscall with flag 0x10000000 (CLONE_NEWNET), and the raw "
    "mount() syscall with source=b'none', target=b'/tmp', "
    "filesystemtype=b'tmpfs', mountflags=0, data=None. Print the return "
    "value and errno (via ctypes.get_errno()) for each call.",
    lambda r, h: "both denied (-1)" if r["stdout"].count("-1") >= 2 else "one or both SUCCEEDED (default caps allowed it)",
    False
),

"testcase4_ptrace_rawsocket_iouring": (
    "ptrace/raw socket/io_uring (LLM-written)",
    "Write a short Python script that: (1) forks a child process that "
    "sleeps for 2 seconds then exits, and in the parent uses ctypes to "
    "call ptrace(PTRACE_ATTACH=16, child_pid, 0, 0) and prints the return "
    "value and errno; (2) attempts to open a raw ICMP socket "
    "(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP) and prints "
    "whether it succeeded or the exception; (3) uses ctypes to call the "
    "raw io_uring_setup syscall (syscall number 425) with entries=1 and "
    "params=0, and prints the return value and errno.",
    lambda r, h: "informational — see per-line result below",
    False
),

}


def log(lines, path):
    os.makedirs(LOG_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def run_for(rt, backend="ollama"):
    print(f"[setup] checking whether runtime '{rt}' is reachable ...")
    if not available(rt):
        print(f"[setup] '{rt}' is NOT reachable — its dockerd is likely not running.")
        if rt == "gvisor":
            print("[setup] start it with: wsl -d Ubuntu -u root -- bash setup-gvisor.sh")
        return
    h = host_kernel()
    print(f"[setup] host kernel : {h}")
    print(f"[setup] runtime     : {rt}")
    print(f"[setup] LLM backend : {backend}\n")

    for key, (label, prompt, note, hardened) in PROMPTS.items():
        print("=" * 70)
        print(key, "-", label)
        print("=" * 70)

        print(f"[llm] sending prompt to '{backend}' ...")
        print(f"[llm] SYSTEM: {SYSTEM_PROMPT}")
        print(f"[llm] USER  : {prompt}")
        try:
            code = write_code(prompt, backend)
        except Exception as e:
            print(f"[llm] FAILED to reach {backend}: {e}")
            continue
        print(f"[llm] model wrote:\n{code}\n")

        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        log_path = os.path.join(LOG_DIR, f"{key}_{rt}_{ts}.log")
        log([f"=== SYSTEM PROMPT ===", SYSTEM_PROMPT,
             f"\n=== USER PROMPT ===", prompt,
             f"\n=== MODEL OUTPUT (raw code) ===", code], log_path)
        print(f"[llm] full prompt + response logged to: {log_path}")

        mode = "hardened (cap-drop ALL, read-only, non-root)" if hardened else "UNHARDENED (Docker default caps/user)"
        print("mode:", mode)
        print(f"[run] starting container on '{rt}' with the LLM-written code ...")
        r = DockerSandbox(rt).run(code) if hardened else run_unhardened(rt, code)
        print(f"[run] container on '{rt}' finished, exit={r['exit']}")
        print(f"\n[{rt}] stdout:")
        print(r["stdout"] or "(no stdout)")
        if r["stderr"]:
            print(f"[{rt}] stderr:", r["stderr"][:300])
        print(f"[{rt}] verdict ->", note(r, h))
        print()
