"""Run every case on every available runtime; print a comparison table."""
import subprocess, sys, time
from sandbox import DockerSandbox, DOCKER

def host_kernel():
    return subprocess.run(["docker","info","--format","{{.KernelVersion}}"],capture_output=True,text=True).stdout.strip()

def available(rt):
    try:
        cmd = [*DOCKER[rt], "info"] if rt == "runc" else [*DOCKER[rt], "info", "--format", "{{json .Runtimes}}"]
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return p.returncode == 0 and (rt == "runc" or "runsc" in p.stdout or "kata" in p.stdout)
    except Exception:
        return False

# (name, code, sandbox kwargs, check(result, host_kernel) -> bool "contained/OK")
T = [
 ("kernel hidden from code", "import platform;print(platform.release())", {},
  lambda r,h: r["exit"]==0 and r["stdout"]!=h),
 ("net: outbound blocked", "import socket\ntry: socket.create_connection(('1.1.1.1',53),2);print('OPEN')\nexcept Exception: print('blocked')", {},
  lambda r,h: r["stdout"]=="blocked"),
 ("net: metadata endpoint blocked", "import socket\ntry: socket.create_connection(('169.254.169.254',80),2);print('OPEN')\nexcept Exception: print('blocked')", {},
  lambda r,h: r["stdout"]=="blocked"),
 ("rootfs read-only", "try: open('/etc/pwned','w');print('WRITABLE')\nexcept Exception: print('ro')", {},
  lambda r,h: r["stdout"]=="ro"),
 ("runs as non-root", "import os;print(os.getuid())", {}, lambda r,h: r["stdout"]!="0"),
 ("no docker.sock / host creds", "import os\nprint(os.path.exists('/var/run/docker.sock') or os.path.exists('/root/.aws'))", {},
  lambda r,h: r["stdout"]=="False"),
 ("syscall: mount denied", "import ctypes;l=ctypes.CDLL(None,use_errno=True)\nprint(l.mount(b'none',b'/tmp',b'tmpfs',0,None), ctypes.get_errno())", {},
  lambda r,h: r["stdout"].startswith("-1")),
 ("syscall: ptrace denied", "import ctypes;l=ctypes.CDLL(None,use_errno=True)\nprint(l.ptrace(16,1,0,0))", {},
  lambda r,h: r["stdout"]=="-1"),
 ("syscall: unshare denied", "import ctypes;l=ctypes.CDLL(None,use_errno=True)\nprint(l.unshare(0x10000000))", {},
  lambda r,h: r["stdout"]=="-1"),
 ("fork bomb capped (<=128 pids)", "import os,time\nn=0\nfor _ in range(600):\n try:\n  if os.fork()==0: time.sleep(5);os._exit(0)\n  n+=1\n except OSError: break\nprint(n)", {},
  lambda r,h: r["stdout"].isdigit() and int(r["stdout"])<=128),
 ("memory 1GB -> OOM killed", "b=bytearray(1024*1024*1024);print('ALLOCATED')", {},
  lambda r,h: "ALLOCATED" not in r["stdout"]),
 ("infinite loop -> timeout", "while True: pass", {"timeout":6},
  lambda r,h: r["stderr"]=="timeout"),
 ("/tmp fill capped", "try:\n open('/tmp/x','wb').write(b'0'*(200*1024*1024));print('FILLED')\nexcept OSError: print('capped')", {},
  lambda r,h: r["stdout"]=="capped"),
 # compatibility
 ("compat: 5000 small files", "import os\nfor i in range(5000): open(f'/tmp/f{i}','w').write('x')\nprint(len(os.listdir('/tmp')))", {},
  lambda r,h: r["stdout"]=="5000"),
 ("compat: threads+subprocess+csv", "import subprocess,csv,io,concurrent.futures as f\nprint(f.ThreadPoolExecutor(4).submit(lambda:subprocess.run(['echo','ok'],capture_output=True,text=True).stdout.strip()).result(), len(list(csv.reader(io.StringIO('a,b'+chr(10)+'1,2')))))", {},
  lambda r,h: r["stdout"]=="ok 2"),
 # performance (informational, always 'OK' if it ran)
 ("perf: cpu loop 3e7", "t=sum(i for i in range(30_000_000));print('done')", {"timeout":60},
  lambda r,h: r["stdout"]=="done"),
 ("perf: 20000 file ops", "for i in range(20000):\n open(f'/tmp/f{i%500}','w').write('x')\nprint('done')", {"timeout":60},
  lambda r,h: r["stdout"]=="done"),
]

def main():
    rts = [rt for rt in ("runc","gvisor","kata") if available(rt)]
    skipped = [rt for rt in ("runc","gvisor","kata") if rt not in rts]
    h = host_kernel(); print("host kernel:", h, "| runtimes:", rts, "| unavailable:", skipped)
    DockerSandbox("runc").run("pass")  # warm image pull
    res = {}
    for name, code, kw, chk in T:
        row = {}
        for rt in rts:
            t=time.time(); r = DockerSandbox(rt, **kw).run(code); dt=time.time()-t
            row[rt] = ("PASS" if chk(r,h) else "FAIL", dt, r)
        res[name]=row
    w=max(len(n) for n in res)
    print("\n"+"test".ljust(w), *[f"{rt:>16}" for rt in rts])
    for n,row in res.items():
        print(n.ljust(w), *[f"{row[rt][0]:>8} {row[rt][1]:6.1f}s" for rt in rts])
    fails=[(n,rt,row[rt][2]) for n,row in res.items() for rt in rts if row[rt][0]=="FAIL"]
    for n,rt,r in fails: print(f"\nFAIL [{rt}] {n}: exit={r['exit']} out={r['stdout']!r} err={r['stderr'][:200]!r}")
main()
