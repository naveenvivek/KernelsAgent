# KernelsAgent

Experiment: what does gVisor actually change about syscall behavior, compared to the default container runtime (`runc`, shared kernel) — without relying on a kernel CVE or container escape. One plain container at a time, run once per runtime, nothing shared between containers.

## Files

| File | Purpose |
|---|---|
| `sandbox.py` | `DockerSandbox(runtime)`: runs code in a locked-down container; the runtime is the only thing that changes |
| `syscall_tests.py` | Shared, hardcoded test-case definitions (not run directly) |
| `syscall_demo_runc.py` | Runs the hardcoded test cases against `runc` only |
| `syscall_demo_gvisor.py` | Runs the hardcoded test cases against `gvisor` only |
| `llm.py` | OpenAI-compatible client for a local LLM (Ollama or LM Studio) |
| `syscall_agent_tests.py` | Same 4 probes, but an LLM writes the code; logs the full prompt and the model's raw output before running it |
| `syscall_agent_demo_runc.py` | Runs the LLM-written probes against `runc` only |
| `syscall_agent_demo_gvisor.py` | Runs the LLM-written probes against `gvisor` only |
| `setup-gvisor.sh` | Installs gVisor and starts a second, separate dockerd in Ubuntu WSL (Docker Desktop can't take custom runtimes) |

## Setup

gVisor setup (WSL2), run once:
```
wsl -d Ubuntu -u root -- bash /mnt/d/VSCode/KernelsAgent/setup-gvisor.sh
```
(adjust the path to wherever this repo lives). This installs gVisor (`runsc`) and starts a dedicated `dockerd` on its own socket inside the Ubuntu WSL distro, separate from Docker Desktop.

## Run

Hardcoded version (deterministic, same code every run):
```
python syscall_demo_runc.py
python syscall_demo_gvisor.py
```

LLM-written version (a local model writes the probe code itself, from a plain English request — the same thing a real coding agent might be asked to do). Requires Ollama or LM Studio running locally (`--llm ollama` is the default; see `llm.py` for model names):
```
python syscall_agent_demo_runc.py
python syscall_agent_demo_gvisor.py
```
Each run prints the exact prompt sent to the model, the exact code the model wrote back, and saves both to `logs/<testcase>_<runtime>_<timestamp>.log` before that code ever runs in the sandbox — so what the LLM saw and chose to write is fully visible, not just the end result.

Run both runc and gVisor (either version) and compare the output — that comparison is the actual experiment.

## Test cases

**Test 1 — kernel fingerprinting** (`platform.release()`, `/proc/version`), hardened container (`--cap-drop ALL`, read-only, non-root, `--network none`).

**Test 2 — `/proc`/`/sys` host info leakage** (`/proc/cpuinfo`, `/proc/meminfo`), same hardened container.

**Test 3 — `unshare()` / `mount()`**, run *without* `--cap-drop` (default Docker capabilities), to see what each runtime blocks on its own, not what hardening already blocked.

**Test 4 — `ptrace`-on-self, raw socket, `io_uring`**, also without `--cap-drop`.

## Results from one run

Host kernel: `6.18.54.1-microsoft-standard-WSL2` (runc) vs gVisor's own fake `4.19.0-gvisor`.

**Test 1:**

| | runc | gVisor |
|---|---|---|
| Kernel reported | `6.18.54.1-microsoft-standard-WSL2` (the real host kernel) | `4.19.0-gvisor` (gVisor's own fake kernel, dated 2016) |

runc hands an agent the exact kernel version to target. gVisor hands back a fabricated identity instead — recon aimed at it is aimed at the wrong kernel.

**Test 2:**

| | runc | gVisor |
|---|---|---|
| CPU model | `AMD Ryzen 7 9700X 8-Core Processor` (real host CPU) | `unknown` |
| Cores seen | `16` (real host core count) | `2` (virtualized) |
| Memory reported | `15919000 kB` (~15 GB, real host RAM) | `262144 kB` (~256 MB — exactly the container's own `--memory` limit, not the host's) |

runc leaks real hardware specs straight through `/proc`, useful for fingerprinting or side-channel setup. gVisor fabricates `/proc` from the container's own cgroup limits instead of reading the real files.

**Test 3:**

| | runc | gVisor |
|---|---|---|
| `unshare(CLONE_NEWNET)` | denied (`-1`, errno 1 — Docker's default seccomp profile) | succeeds (`0`) |
| `mount()` | denied (`-1`) | denied (`-1`) |

`unshare` succeeding on gVisor looks alarming at first, but it isn't creating a *host* namespace — gVisor runs its own sandboxed kernel (Sentry), so the call is satisfied entirely inside that sandbox and never reaches the real host namespaces. It's allowed because it's harmless there, not because gVisor failed to stop it.

**Test 4:**

| | runc | gVisor |
|---|---|---|
| `ptrace` (attach to own forked child) | succeeds (`0`) | succeeds (`0`) — contained in gVisor's own process model |
| Raw socket (`SOCK_RAW`) | OPENED | denied (`Errno 1`) |
| `io_uring_setup` | denied, errno 1 (`EPERM` — a seccomp rule, which can be turned off with `--security-opt seccomp=unconfined`) | denied, errno 38 (`ENOSYS` — not implemented at all, nothing to misconfigure) |

With identical, *unhardened* settings, runc still let the container open a raw socket (able to craft arbitrary packets), while gVisor refused it outright. The `io_uring` errno difference is the clearest structural point: runc's "permission denied" is a configurable seccomp rule; gVisor's "function not found" means the syscall path doesn't exist in its kernel, independent of any flag someone could flip.

## LLM-written version: same results, the model never knew

Run with `qwen3:14b` via Ollama, given only a plain-English description of each probe (e.g. *"Write a short Python script that prints what kernel/OS version the script is currently running on..."*) — not told anything about runc or gVisor. The model wrote different code each time (its own variable names, its own `libc.syscall()` vs named `ctypes` bindings), but the outcome matched the hardcoded version exactly:

| | runc (LLM-written) | gVisor (LLM-written) |
|---|---|---|
| Test 1: kernel | `6.18.54.1-microsoft-standard-WSL2` (real) | `4.19.0-gvisor` (fake) |
| Test 2: CPU/RAM | Real CPU model, `15919000` kB | `unknown` CPU, `262144` kB |
| Test 3: `unshare` | denied (`-1`) | succeeds (`0`, contained in gVisor's own kernel) |
| Test 4: raw socket | **"Raw ICMP socket succeeded"** | **"Raw ICMP socket failed: Operation not permitted"** |

The point: the model had no idea it was being run under a different runtime, and no way to tell from inside the sandbox that its own `platform.release()` call was lying to it. Identical instructions, identical intent, different outcome purely because of which runtime executed the code — which is exactly why this isn't something an LLM's own judgment, prompting, or guardrails can fix. It has to be enforced at the sandbox layer.

## Net takeaway

gVisor's protection isn't one thing:
- Identity/hardware info is fully masked (tests 1–2).
- Some dangerous syscalls (`mount`, raw sockets, `io_uring`) are blocked or unimplemented even with zero container hardening (tests 3–4).
- A few syscalls (`unshare`, `ptrace`-on-self) are *allowed* but contained entirely within gVisor's own sandboxed kernel rather than reaching the host.

None of this requires a kernel CVE — it's gVisor's normal, by-design behavior versus runc's normal, by-design behavior.

## Open questions

- `unshare` succeeding inside gVisor's own kernel: confirmed harmless here, but worth checking whether any gVisor-internal privilege escalation is reachable through it.
- Kata Containers not yet tested as a third runtime.

All test data is fake, no real credentials or hardware identifiers beyond what's shown above.
