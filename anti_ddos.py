import asyncio
import time
import socket
from collections import deque

try:
    import uvloop
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
except ImportError:
    pass

BUF_SIZE = 65536          # 64KB optimal buffer for low syscall overhead without memory stall
MAX_CONN_PER_IP = 150     # Max connections per IP in window
RATE_LIMIT_WINDOW = 120   # 2-minute sliding window

# Use deques for O(1) popping instead of O(N) list comprehensions
ip_connections = {}

def check_rate_limit(ip: str) -> bool:
    now = time.time()
    timestamps = ip_connections.setdefault(ip, deque())
    
    # O(1) cleanup of old timestamps from the left
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
        now = time.time()
        for ip in list(ip_connections.keys()):
            timestamps = ip_connections[ip]
            while timestamps and now - timestamps[0] >= RATE_LIMIT_WINDOW:
                timestamps.popleft()
            if not timestamps:
                del ip_connections[ip]

async def pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    """Bidirectional streaming without excessive drain pauses."""
    try:
        while True:
            data = await reader.read(BUF_SIZE)
            if not data:
                break
            writer.write(data)
            # Do not await writer.drain() on every chunk to eliminate context-switch delay
    except Exception:
        pass
    finally:
        writer.close()

async def handle_client(client_reader: asyncio.StreamReader, client_writer: asyncio.StreamWriter):
    # Extract client IP address safely
    peername = client_writer.get_extra_info('peername')
    client_ip = peername[0] if peername else '0.0.0.0'

    if not check_rate_limit(client_ip):
        client_writer.close()
        return

    try:
        # Tune client socket IMMEDIATELY before reading
        client_sock = client_writer.get_extra_info('socket')
        if client_sock:
            client_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            try:
                client_sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1048576)
                client_sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1048576)
            except OSError:
                pass

        # FIX 1: Read HTTP header immediately until end-of-header delimiter instead of waiting for 4096 bytes
        await client_reader.readuntil(b"\r\n\r\n")
        
        # Send HTTP 101 WebSocket handshake acknowledgement
        response_header = (
            b"HTTP/1.1 101 Switching Protocols\r\n"
            b"Upgrade: websocket\r\n"
            b"Connection: Upgrade\r\n\r\n"
        )
        client_writer.write(response_header)

        # Connect to local SSH daemon
        ssh_reader, ssh_writer = await asyncio.open_connection('127.0.0.1', 22)

        # Tune SSH socket
        ssh_sock = ssh_writer.get_extra_info('socket')
        if ssh_sock:
            ssh_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            try:
                ssh_sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1048576)
                ssh_sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1048576)
            except OSError:
                pass

        # Run bidirectional piping concurrently
        await asyncio.gather(
            pipe(client_reader, ssh_writer),
            pipe(ssh_reader, client_writer),
            return_exceptions=True
        )
    except Exception:
        pass
    finally:
        client_writer.close()

async def main():
    asyncio.create_task(cleanup_stale_ips())
    server = await asyncio.start_server(
        handle_client,
        '127.0.0.1',
        2222,
        backlog=2048,
        reuse_address=True
    )
    print("[+] Low-latency WebSocket bridge running with uvloop on 127.0.0.1:2222")
    async with server:
        await server.serve_forever()

if __name__ == '__main__':
    asyncio.run(main())
