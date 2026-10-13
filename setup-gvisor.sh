#!/usr/bin/env bash
# Run inside Ubuntu WSL: sudo bash setup-gvisor.sh
# Installs gVisor (runsc) and starts a SEPARATE dockerd on its own socket,
# so Docker Desktop is untouched.
set -euo pipefail
apt-get update -y && apt-get install -y docker.io curl bzip2
ARCH=$(uname -m)
VER=${GVISOR_VERSION:-20261005.0}
URL=https://storage.googleapis.com/gvisor/releases/release/${VER}/${ARCH}
TMP=$(mktemp -d); cd "$TMP"
curl -fsSL -O "$URL/gvisor.tar.bz2" -O "$URL/gvisor.tar.bz2.sha512"
sha512sum -c gvisor.tar.bz2.sha512
tar -xjf gvisor.tar.bz2
install -m 755 runsc containerd-shim-runsc-v1 /usr/local/bin/
rm -rf /usr/local/bin/gvisor-bin; cp -r gvisor-bin /usr/local/bin/gvisor-bin; chmod -R a+rx /usr/local/bin/gvisor-bin
cd /; rm -rf "$TMP"
runsc --version | head -1
mkdir -p /var/lib/docker-gvisor /run/docker-gvisor
pkill -f 'docker-gvisor.sock' || true
nohup dockerd --host unix:///run/docker-gvisor.sock \
  --data-root /var/lib/docker-gvisor --exec-root /run/docker-gvisor \
  --pidfile /run/docker-gvisor.pid --bridge none --iptables=false \
  --add-runtime runsc=/usr/local/bin/runsc \
  >/var/log/dockerd-gvisor.log 2>&1 &
sleep 6
chmod 666 /run/docker-gvisor.sock
docker -H unix:///run/docker-gvisor.sock info --format '{{range $k,$v := .Runtimes}}{{$k}} {{end}}' | sed 's/^/runtimes: /'
docker -H unix:///run/docker-gvisor.sock run --rm --runtime runsc --network none python:3.12-slim \
  python -c 'import platform; print("gVisor kernel:", platform.release())'
