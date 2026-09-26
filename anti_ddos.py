import asyncio
import time
import socket
from collections import deque

try:
    import uvloop
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
except ImportError:
    pass

BUF_SIZE = 65536          # 64KB chunk processing
MAX_CONN_PER_IP = 150     # Max connections per IP in window
RATE_LIMIT_WINDOW = 120   # 2-minute sliding window

ip_connections = {}

def check_rate_limit(ip: str) -> bool:
    now = time.monotonic()  # Faster monotonic clock vs system time
    timestamps = ip_connections.get(ip)
    if timestamps is None:
        timestamps = deque()
        ip_connections[ip] = timestamps

    # Fast pruning
    while timestamps and now - timestamps[0] >= RATE_LIMIT_WINDOW:
        timestamps.popleft()

    if len(timestamps) >= MAX_CONN_PER_IP:
        return False

    timestamps.append(now)
    return True

async def cleanup_stale_ips():
    """Periodic background task to purge idle IP records."""
    while True:
        await asyncio.sleep(60)
        now = time.monotonic()
        for ip in list(ip_connections.keys()):
            timestamps = ip_connections[ip]
            while timestamps and now - timestamps[0] >= RATE_LIMIT_WINDOW:
                timestamps.popleft()
            if not timestamps:
                del ip_connections[ip]

class BridgeProtocol(asyncio.Protocol):
    """Zero-overhead bidirectional proxy protocol with automatic backpressure handling."""
    def __init__(self, target_transport=None):
        self.transport = None
        self.peer_transport = target_transport
        self.handshake_done = False

    def connection_made(self, transport):
        self.transport = transport
        sock = transport.get_extra_info('socket')
        if sock:
            # Low latency socket tuning
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1048576)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1048576)
            except OSError:
                pass

    def data_received(self, data):
        if not self.peer_transport:
            return

        # If incoming from client and handshake not done
        if not self.handshake_done:
            self.handshake_done = True
            # Fast response 101 WS Upgrade ACK
            response_header = (
                b"HTTP/1.1 101 Switching Protocols\r\n"
                b"Upgrade: websocket\r\n"
                b"Connection: Upgrade\r\n\r\n"
            )
            self.transport.write(response_header)
            return

        # Forward instantly without intermediate stream queue overhead
        self.peer_transport.write(data)

    def pause_writing(self):
        """Native backpressure flow control to prevent bufferbloat/red pings."""
        if self.peer_transport:
            self.peer_transport.pause_reading()

    def resume_writing(self):
        """Resume reading when OS buffers clear up."""
        if self.peer_transport:
            self.peer_transport.resume_reading()

    def connection_lost(self, exc):
        if self.peer_transport:
            self.peer_transport.close()
            self.peer_transport = None

class ServerBridgeProtocol(BridgeProtocol):
    """Client connection handler that opens local SSH socket asynchronously."""
    def connection_made(self, transport):
        super().connection_made(transport)
        peername = transport.get_extra_info('peername')
        client_ip = peername[0] if peername else '0.0.0.0'

        if not check_rate_limit(client_ip):
            transport.close()
            return

        loop = asyncio.get_running_loop()
        # Non-blocking async connection to local SSH daemon
        asyncio.create_task(self._connect_ssh(loop))

    async def _connect_ssh(self, loop):
        try:
            # Connect to local SSH target
            _, ssh_protocol = await loop.create_connection(
                lambda: BridgeProtocol(target_transport=self.transport),
                '127.0.0.1', 
                22
            )
            self.peer_transport = ssh_protocol.transport
            self.handshake_done = False
        except Exception:
            self.transport.close()

async def main():
    asyncio.create_task(cleanup_stale_ips())
    loop = asyncio.get_running_loop()
    
    server = await loop.create_server(
        ServerBridgeProtocol,
        '127.0.0.1',
        2222,
        backlog=65535,
        reuse_port=True
    )
    print("[+] Ultra Low-Latency WS Bridge running on 127.0.0.1:2222")
    async with server:
        await server.serve_forever()

if __name__ == '__main__':
    asyncio.run(main())
