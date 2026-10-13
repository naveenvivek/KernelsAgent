"""Use case: a tenant-data agent is hijacked and its code tries to override access control.
Four setups, same attack. All data and secrets are fake."""
import json, pathlib, subprocess, shutil
from sandbox import DOCKER

ROOT = pathlib.Path(__file__).parent / "demo-data"
WSL_ROOT = "/mnt/d/VSCode/KernelsAgent/demo-data"          # same folder, seen from Ubuntu WSL
IMAGE = "python:3.12-slim"

def seed():
    shutil.rmtree(ROOT, ignore_errors=True)
    (ROOT / "tenant-a").mkdir(parents=True); (ROOT / "tenant-b").mkdir(parents=True)
    (ROOT / "tenant-a" / "orders.csv").write_text("id,amount\n1,10\n")
    (ROOT / "tenant-b" / "customers.csv").write_text("name,card\nSECRET-B-alice,4111-FAKE\n")

def host_kernel():
    return subprocess.run(["docker","info","--format","{{.KernelVersion}}"],capture_output=True,text=True).stdout.strip()

ATTACK = r'''
import os, json, ctypes, platform
r = {}
def t(name, f):
    try: r[name] = "BREACH: " + str(f())
    except Exception as e: r[name] = "held"
def read_b():
    s = open('/data/tenant-b/customers.csv').read()
    assert 'SECRET-B' in s; return "read other tenant's records"
def env():
    v = os.environ['SECRET_API_KEY']; return "stole " + v[:8] + "..."
def tamper():
    open('/data/tenant-a/orders.csv','a').write('9,999999\n'); return "rewrote own input data"
def delete_b():
    os.remove('/data/tenant-b/customers.csv'); return "deleted other tenant's file"
def root():
    assert os.getuid() == 0; return "running as root"
def sysfile():
    open('/etc/evil','w').write('x'); return "wrote a system file"
def mount():
    l = ctypes.CDLL(None, use_errno=True)
    assert l.mount(b'none', b'/mnt', b'tmpfs', 0, None) == 0; return "mounted a filesystem"
def kern():
    assert platform.release() == "__HOSTK__"; return "host kernel " + platform.release()
for n, f in [("read other tenant's data", read_b), ("steal API key from env", env),
             ("tamper with data", tamper), ("delete other tenant's data", delete_b),
             ("run as root", root), ("write system file", sysfile),
             ("mount a filesystem", mount), ("see host kernel version", kern)]: t(n, f)
print(json.dumps(r))
'''

def run(level, hostk):
    seed()
    gv = level["runtime"] == "runsc"
    root = WSL_ROOT if gv else str(ROOT)
    cmd = [*DOCKER["gvisor" if gv else "runc"], "run", "--rm", "-i", "--network", "none"]
    if level["runtime"]: cmd += ["--runtime", level["runtime"]]
    if level["naive"]:
        cmd += ["-v", f"{root}:/data", "-e", "SECRET_API_KEY=sk-FAKE-123456789"]   # everything mounted rw, secret in env, root, default caps
    else:
        cmd += ["-v", f"{root}/tenant-a:/data/tenant-a:ro", "--read-only", "--tmpfs", "/tmp:size=16m",
                "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--user", "65534:65534"]
    cmd += [IMAGE, "python", "-"]
    p = subprocess.run(cmd, input=ATTACK.replace("__HOSTK__", hostk), capture_output=True, text=True, timeout=60)
    try: return json.loads(p.stdout.strip().splitlines()[-1])
    except Exception: return {"error": (p.stderr or p.stdout)[-300:]}

LEVELS = [
 ("naive / runc",           {"naive": True,  "runtime": None}),
 ("naive / gVisor",         {"naive": True,  "runtime": "runsc"}),
 ("hardened / runc",        {"naive": False, "runtime": None}),
 ("hardened / gVisor",      {"naive": False, "runtime": "runsc"}),
]

if __name__ == "__main__":
    hk = host_kernel(); print("host kernel:", hk, "\n")
    res = {n: run(l, hk) for n, l in LEVELS}
    for n, r in res.items():
        if "error" in r: print("ERROR", n, r["error"])
    checks = [k for k in next(iter(res.values())) if k != "error"]
    w = max(len(c) for c in checks)
    print("attack".ljust(w), *[f"{n:>18}" for n in res])
    for c in checks:
        print(c.ljust(w), *[f"{('BREACH' if res[n].get(c,'').startswith('BREACH') else 'held'):>18}" for n in res])
    print("\ndetail (naive / runc):"); [print(" ", k, "->", v) for k, v in res["naive / runc"].items()]
    shutil.rmtree(ROOT, ignore_errors=True)
