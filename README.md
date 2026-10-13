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
| `setup-gvisor.sh` | Installs gVisor and a second dockerd in Ubuntu WSL (Docker Desktop can't take custom runtimes) |
| `flow.html` | Flow diagram and results |

## Run
```
python agent.py --task kernel
python agent.py --runtime gvisor --ask "print the first 10 primes"
python tests.py
python access_demo.py
```
gVisor setup (WSL2): `wsl -d Ubuntu -u root -- bash /mnt/d/VSCode/KernelsAgent/setup-gvisor.sh` (adjust the path).

## Findings so far
- Hardening (non-root, no caps, read-only fs, only the needed mount, no secrets in env) is what stops access-control overrides. gVisor alone does not fix a naive setup.
- gVisor hides the host kernel; `runc` exposes it.
- gVisor is about 7x slower on file-heavy work in these tests.
- Open: fork bomb kills the gVisor sandbox (cause not checked); `unshare` is allowed inside gVisor's own kernel. Kata not yet tested.

All test data and secrets are fake.
