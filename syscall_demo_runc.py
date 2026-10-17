"""runc-only run of the syscall demo. Run syscall_demo_gvisor.py too and
compare the two outputs — that comparison is the actual experiment."""
from syscall_tests import run_for

if __name__ == "__main__":
    run_for("runc")
