"""Pluggable code sandbox. The only thing that changes between isolation
levels is the OCI runtime passed to `docker run --runtime`."""
import subprocess, uuid

# None = Docker default (runc, shared kernel). Later: "runsc" (gVisor), "kata-runtime"/"kata".
RUNTIMES = {"runc": None, "gvisor": "runsc", "kata": "kata"}
# Which docker engine serves each runtime. gVisor lives in its own dockerd inside Ubuntu WSL.
DOCKER = {"runc": ["docker"],
          "gvisor": ["wsl", "-d", "Ubuntu", "--", "docker", "-H", "unix:///run/docker-gvisor.sock"],
          "kata": ["wsl", "-d", "Ubuntu", "--", "docker", "-H", "unix:///run/docker-kata.sock"]}


class DockerSandbox:
    def __init__(self, runtime="runc", image="python:3.12-slim", timeout=30,
                 memory="256m", cpus="1", network="none"):
        self.runtime = RUNTIMES[runtime]
        self.name = runtime
        self.image, self.timeout = image, timeout
        self.memory, self.cpus, self.network = memory, cpus, network

    def run(self, code: str) -> dict:
        cname = "sbx-" + uuid.uuid4().hex[:8]
        cmd = [*DOCKER[self.name], "run", "--rm", "-i", "--name", cname,
               "--network", self.network,          # no outbound traffic by default
               "--memory", self.memory, "--cpus", self.cpus,
               "--pids-limit", "128",
               "--read-only", "--tmpfs", "/tmp:size=64m",
               "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
               "--user", "65534:65534"]            # nobody, no credentials mounted
        if self.runtime:
            cmd += ["--runtime", self.runtime]
        cmd += [self.image, "python", "-"]         # code arrives on stdin
        try:
            p = subprocess.run(cmd, input=code, capture_output=True, text=True,
                               timeout=self.timeout)
            return {"runtime": self.name, "exit": p.returncode,
                    "stdout": p.stdout.strip(), "stderr": p.stderr.strip()}
        except subprocess.TimeoutExpired:
            subprocess.run([*DOCKER[self.name], "kill", cname], capture_output=True)
            return {"runtime": self.name, "exit": -1, "stdout": "", "stderr": "timeout"}
