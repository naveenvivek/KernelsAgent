# KernelsAgent

Test bed for running AI-agent-written code in a sandbox, first with the default container runtime (`runc`, shared kernel), then with kernel isolation (gVisor).

Inspired by the article "Your AI agent just wrote some code. Where should it run?" (gVisor vs Kata Containers).

## Files
| File | Purpose |
|---|---|
| `sandbox.py` | `DockerSandbox(runtime)`: runs code in a locked-down container; the runtime is the only thing that changes |
| `agent.py` | Minimal agent. `--ask "..."` has a local LLM (Ollama or LM Studio) write the code |
| `llm.py` | OpenAI-compatible client for Ollama / LM Studio |
| `tests.py` | 17 hostile, compatibility and performance cases, compared per runtime |
| `access_demo.py` | Use case: a hijacked agent tries to override access control, 4 setups (naive/hardened x runc/gVisor) |
| `syscall_tests.py` | Shared test-case definitions for the syscall demo (not run directly) |
| `syscall_demo_runc.py` | Runs the 4 syscall test cases against `runc` only |
| `syscall_demo_gvisor.py` | Runs the same 4 test cases against `gvisor` only |
| `setup-gvisor.sh` | Installs gVisor and a second dockerd in Ubuntu WSL (Docker Desktop can't take custom runtimes) |
| `flow.html` | Flow diagram and results |

## Run
```
python agent.py --task kernel
python agent.py --runtime gvisor --ask "print the first 10 primes"
python tests.py
python access_demo.py
python syscall_demo_runc.py
python syscall_demo_gvisor.py
```
gVisor setup (WSL2): `wsl -d Ubuntu -u root -- bash /mnt/d/VSCode/KernelsAgent/setup-gvisor.sh` (adjust the path).

## Findings so far
- Hardening (non-root, no caps, read-only fs, only the needed mount, no secrets in env) is what stops access-control overrides. gVisor alone does not fix a naive setup.
- gVisor hides the host kernel; `runc` exposes it.
- gVisor is about 7x slower on file-heavy work in these tests.
- Open: fork bomb kills the gVisor sandbox (cause not checked); `unshare` is allowed inside gVisor's own kernel (see below). Kata not yet tested.

## `syscall_demo_runc.py` / `syscall_demo_gvisor.py` — what gVisor actually changes, without any kernel exploit

A container escape via a kernel CVE is one threat model, but it needs an unpatched bug to exist. A separate, always-present gap is simpler: on `runc`, a container's syscalls go straight to the real host kernel, so even *working-as-designed* syscalls can leak host identity, hardware info, and (if the container isn't hardened) real privileges. These two scripts isolate this from the CVE question entirely — each runs the same 4 test cases (defined once, in `syscall_tests.py`) against a single runtime, one plain container at a time. No second container, no shared namespace, no exploit — run both scripts and diff the output. Host kernel for this run: `6.18.54.1-microsoft-standard-WSL2` (runc) vs gVisor's own fake `4.19.0-gvisor`.

**Test 1 — kernel fingerprinting** (`platform.release()`, `/proc/version`), hardened container (`--cap-drop ALL`, read-only, non-root, `--network none`):

| | runc | gVisor |
|---|---|---|
| Kernel reported | `6.18.54.1-microsoft-standard-WSL2` (the real host kernel) | `4.19.0-gvisor` (gVisor's own fake kernel, dated 2016) |

runc hands an agent the exact kernel version to target. gVisor hands back a fabricated identity instead — recon aimed at it is aimed at the wrong kernel.

**Test 2 — `/proc`/`/sys` host info leakage** (`/proc/cpuinfo`, `/proc/meminfo`), same hardened container:

| | runc | gVisor |
|---|---|---|
| CPU model | `AMD Ryzen 7 9700X 8-Core Processor` (real host CPU) | `unknown` |
| Cores seen | `16` (real host core count) | `2` (virtualized) |
| Memory reported | `15919000 kB` (~15 GB, real host RAM) | `262144 kB` (~256 MB — exactly the container's own `--memory` limit, not the host's) |

runc leaks real hardware specs straight through `/proc`, useful for fingerprinting or side-channel setup. gVisor fabricates `/proc` from the container's own cgroup limits instead of reading the real files.

**Test 3 — `unshare()` / `mount()`, run *without* `--cap-drop`** (default Docker capabilities, to see what each runtime blocks on its own, not what hardening already blocked):

| | runc | gVisor |
|---|---|---|
| `unshare(CLONE_NEWNET)` | denied (`-1`, errno 1 — Docker's default seccomp profile) | **succeeds (`0`)** |
| `mount()` | denied (`-1`) | denied (`-1`) |

`unshare` succeeding on gVisor looks alarming at first, but it isn't creating a *host* namespace — gVisor runs its own sandboxed kernel (Sentry), so the call is satisfied entirely inside that sandbox and never reaches the real host namespaces. It's allowed because it's harmless there, not because gVisor failed to stop it. This matches the open item already noted above.

**Test 4 — `ptrace`-on-self, raw socket, `io_uring`, also without `--cap-drop`:**

| | runc | gVisor |
|---|---|---|
| `ptrace` (attach to own forked child) | succeeds (`0`) | succeeds (`0`) — contained in gVisor's own process model |
| Raw socket (`SOCK_RAW`) | **OPENED** | denied (`Errno 1`) |
| `io_uring_setup` | denied, errno **1** (`EPERM` — a seccomp rule, which can be turned off with `--security-opt seccomp=unconfined`) | denied, errno **38** (`ENOSYS` — not implemented at all, nothing to misconfigure) |

With identical, *unhardened* settings, runc still let the container open a raw socket (able to craft arbitrary packets), while gVisor refused it outright. The `io_uring` errno difference is the clearest structural point: runc's "permission denied" is a configurable seccomp rule; gVisor's "function not found" means the syscall path doesn't exist in its kernel, independent of any flag someone could flip.

**Net takeaway:** gVisor's protection isn't one thing — identity/hardware info is fully masked (tests 1–2); some dangerous syscalls (`mount`, raw sockets, `io_uring`) are blocked or unimplemented even with zero container hardening (tests 3–4); and a few syscalls (`unshare`, `ptrace`-on-self) are *allowed* but contained entirely within gVisor's own sandboxed kernel rather than reaching the host. None of this requires a kernel CVE — it's gVisor's normal, by-design behavior versus runc's normal, by-design behavior.

All test data and secrets are fake.
