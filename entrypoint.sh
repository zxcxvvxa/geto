#!/bin/bash
set -e

echo "[+] Starting ultra low-latency container environment..."

# 1. Maximize File Descriptor Limits
ulimit -n 1048576 2>/dev/null || ulimit -n 65535 2>/dev/null || true

# 2. Prepare Runtime Directories
mkdir -p /run/sshd /var/run/sshd /app

# 3. Generate SSH Host Keys explicitly if missing
if [ ! -f /etc/ssh/ssh_host_rsa_key ]; then
    echo "[+] Generating missing OpenSSH host keys..."
    ssh-keygen -A
fi

# 4. Clean up stale supervisor PID files from previous crashes
rm -f /var/run/supervisord.pid /tmp/supervisord.sock

echo "[+] Launching Supervisor..."
exec /usr/bin/supervisord -n -c /etc/supervisor/supervisord.conf
