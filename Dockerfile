FROM debian:bookworm-slim
ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Asia/Shanghai

RUN apt-get update && apt-get install -y \
    build-essential libssl-dev zlib1g-dev libpam0g-dev libselinux1-dev \
    openssh-server nginx python3 python3-pip cmake git wget curl ca-certificates unzip supervisor \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Install uvloop and aiohttp for high-performance asyncio servers
RUN pip3 install --break-system-packages uvloop aiohttp

# Direct Xray Core installation
RUN XRAY_VER=$(curl -s https://api.github.com/repos/XTLS/Xray-core/releases/latest | grep '"tag_name":' | sed -E 's/.*"([^"]+)".*/\1/') \
    && wget -O /tmp/xray.zip "https://github.com/XTLS/Xray-core/releases/download/${XRAY_VER}/Xray-linux-64.zip" \
    && unzip /tmp/xray.zip -d /usr/local/bin/ \
    && chmod +x /usr/local/bin/xray \
    && mkdir -p /usr/local/etc/xray \
    && rm -f /tmp/xray.zip

# Build BadVPN UDPGW
RUN git clone https://github.com/ambrop72/badvpn.git /tmp/badvpn \
    && cd /tmp/badvpn && mkdir build && cd build \
    && cmake .. -DBUILD_NOTHING_BY_DEFAULT=1 -DBUILD_UDPGW=1 \
    && make install && rm -rf /tmp/badvpn

RUN mkdir -p /var/run/sshd /run/sshd
RUN useradd -m -s /bin/bash geto && echo 'geto:suguru' | chpasswd

# Configure OpenSSH settings
RUN echo "PermitRootLogin yes" >> /etc/ssh/sshd_config
RUN echo "PasswordAuthentication yes" >> /etc/ssh/sshd_config
RUN { \
    echo "UseDNS no"; \
    echo "TCPKeepAlive yes"; \
    echo "ClientAliveInterval 15"; \
    echo "ClientAliveCountMax 3"; \
    echo "MaxSessions 50"; \
    echo "MaxStartups 50:30:100"; \
    echo "Compression no"; \
    } >> /etc/ssh/sshd_config

COPY banner.txt /etc/ssh/banner.txt
RUN echo "Banner /etc/ssh/banner.txt" >> /etc/ssh/sshd_config

COPY xray_config.json /usr/local/etc/xray/config.json
COPY nginx.conf /etc/nginx/nginx.conf
COPY supervisord.conf /etc/supervisor/supervisord.conf
COPY anti_ddos.py /usr/local/bin/anti_ddos.py
COPY sub_server.py /usr/local/bin/sub_server.py
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh /usr/local/bin/anti_ddos.py /usr/local/bin/sub_server.py

EXPOSE 8080
ENTRYPOINT ["/entrypoint.sh"]
