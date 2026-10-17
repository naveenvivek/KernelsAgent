"""gVisor-only run of the syscall demo. Requires the gVisor dockerd
(setup-gvisor.sh) running in Ubuntu WSL. Run syscall_demo_runc.py too and
compare the two outputs — that comparison is the actual experiment."""
from syscall_tests import run_for

if __name__ == "__main__":
    run_for("gvisor")
