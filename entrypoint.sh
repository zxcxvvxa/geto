#!/bin/bash
set -e

echo "[+] Starting container initialization..."

# Set File Descriptor Limits
ulimit -n 1048576 2>/dev/null || ulimit -n 65535 2>/dev/null || true

# Prepare SSH Host Keys & Runtime Dirs
echo "[+] Initializing SSH environment..."
ssh-keygen -A 2>/dev/null || true
mkdir -p /run/sshd /var/run/sshd

echo "[+] Handing over process management to Supervisor..."
exec /usr/bin/supervisord -c /etc/supervisor/supervisord.conf
