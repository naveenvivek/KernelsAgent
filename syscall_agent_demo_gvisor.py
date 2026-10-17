"""Same 4 probes as syscall_demo_gvisor.py, but an LLM writes the code.
Requires a local LLM (Ollama by default, see llm.py) and the gVisor
dockerd (setup-gvisor.sh) running in Ubuntu WSL. Full prompt and model
output are logged to logs/ and printed before anything runs."""
import argparse
from syscall_agent_tests import run_for

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm", default="ollama", choices=["ollama", "lmstudio"])
    a = ap.parse_args()
    run_for("gvisor", a.llm)
