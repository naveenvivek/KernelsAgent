# KernelsAgent

Experiment: what does gVisor actually change about syscall behavior, compared to the default container runtime (`runc`, shared kernel) — without relying on a kernel CVE or container escape. One plain container at a time, run once per runtime, nothing shared between containers.

## Files

| File | Purpose |
|---|---|
| `sandbox.py` | `DockerSandbox(runtime)`: runs code in a locked-down container; the runtime is the only thing that changes |
| `syscall_tests.py` | Shared test-case definitions (not run directly) |
| `syscall_demo_runc.py` | Runs the test cases against `runc` only |
| `syscall_demo_gvisor.py` | Runs the same test cases against `gvisor` only |
| `setup-gvisor.sh` | Installs gVisor and starts a second, separate dockerd in Ubuntu WSL (Docker Desktop can't take custom runtimes) |

## Setup

gVisor setup (WSL2), run once:
```
wsl -d Ubuntu -u root -- bash /mnt/d/VSCode/KernelsAgent/setup-gvisor.sh
```
(adjust the path to wherever this repo lives). This installs gVisor (`runsc`) and starts a dedicated `dockerd` on its own socket inside the Ubuntu WSL distro, separate from Docker Desktop.

## Run

```
python syscall_demo_runc.py
python syscall_demo_gvisor.py
```
Run both and compare the output — that comparison is the actual experiment.

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
