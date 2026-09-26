FROM debian:bookworm-slim
ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Asia/Shanghai

RUN apt-get update && apt-get install -y \
    build-essential libssl-dev zlib1g-dev libpam0g-dev libselinux1-dev \
    openssh-server nginx python3 python3-pip cmake git wget curl ca-certificates unzip supervisor \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Direct Xray Core installation (Direct download with fallback)
RUN (wget -O /tmp/xray.zip "https://github.com/XTLS/Xray-core/releases/latest/download/Xray-linux-64.zip" || \
     wget -O /tmp/xray.zip "https://ghproxy.com/https://github.com/XTLS/Xray-core/releases/latest/download/Xray-linux-64.zip") \
    && unzip /tmp/xray.zip -d /usr/local/bin/ \
    && chmod +x /usr/local/bin/xray \
    && mkdir -p /usr/local/etc/xray \
    && rm -f /tmp/xray.zip

# Build BadVPN UDPGW
RUN git clone https://github.com/ambrop72/badvpn.git /tmp/badvpn \
    && cd /tmp/badvpn && mkdir build && cd build \
    && cmake .. -DBUILD_NOTHING_BY_DEFAULT=1 -DBUILD_UDPGW=1 \
    && make install && rm -rf /tmp/badvpn

RUN mkdir -p /var/run/sshd /run/sshd /app
RUN useradd -m -s /bin/bash geto && echo 'geto:suguru' | chpasswd

# Configure OpenSSH settings for maximum speed & low latency
RUN echo "PermitRootLogin yes" >> /etc/ssh/sshd_config
RUN echo "PasswordAuthentication yes" >> /etc/ssh/sshd_config
RUN { \
    echo "UseDNS no"; \
    echo "GSSAPIAuthentication no"; \
    echo "GSSAPIKeyExchange no"; \
    echo "TCPKeepAlive yes"; \
    echo "ClientAliveInterval 10"; \
    echo "ClientAliveCountMax 2"; \
    echo "MaxSessions 500"; \
    echo "MaxStartups 1000:30:2000"; \
    echo "MaxAuthTries 10"; \
    echo "Compression no"; \
    echo "Ciphers aes128-gcm@openssh.com,chacha20-poly1305@openssh.com,aes128-ctr"; \
    echo "MACs hmac-sha2-256-etm@openssh.com,umac-64-etm@openssh.com"; \
    echo "KexAlgorithms curve25519-sha256,curve25519-sha256@libssh.org"; \
    } >> /etc/ssh/sshd_config

COPY banner.txt /etc/ssh/banner.txt
RUN echo "Banner /etc/ssh/banner.txt" >> /etc/ssh/sshd_config

COPY xray_config.json /usr/local/etc/xray/config.json
COPY nginx.conf /etc/nginx/nginx.conf
COPY supervisord.conf /etc/supervisor/supervisord.conf
COPY wsproxy.py /app/wsproxy.py
COPY sub_server.py /usr/local/bin/sub_server.py
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh /app/wsproxy.py /usr/local/bin/sub_server.py

EXPOSE 8080
ENTRYPOINT ["/entrypoint.sh"]
