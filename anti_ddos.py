import asyncio
import time
import socket

try:
    import uvloop
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
except ImportError:
    pass

BUF_SIZE = 131072         # 128KB buffer
MAX_CONN_PER_IP = 150     # Max connections per IP in window
RATE_LIMIT_WINDOW = 120   # 2-minute sliding window

ip_connections = {}

def check_rate_limit(ip: str) -> bool:
    now = time.time()
    timestamps = ip_connections.setdefault(ip, [])
    
    # Prune old timestamps
    ip_connections[ip] = [t for t in timestamps if now - t < RATE_LIMIT_WINDOW]
    
    if len(ip_connections[ip]) >= MAX_CONN_PER_IP:
        return False
    
    ip_connections[ip].append(now)
    return True

async def cleanup_stale_ips():
    """Periodic task to purge idle IP records from memory."""
    while True:
        await asyncio.sleep(300)
        now = time.time()
        for ip in list(ip_connections.keys()):
            ip_connections[ip] = [t for t in ip_connections[ip] if now - t < RATE_LIMIT_WINDOW]
            if not ip_connections[ip]:
                del ip_connections[ip]

async def pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    """Bidirectional pipe for proxying data streams."""
    try:
        while True:
            data = await reader.read(BUF_SIZE)
            if not data:
                break
            writer.write(data)
            await writer.drain()
    except (asyncio.CancelledError, Exception):
        pass
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass

async def handle_client(client_reader: asyncio.StreamReader, client_writer: asyncio.StreamWriter):
    # Extract client IP address safely
    peername = client_writer.get_extra_info('peername')
    client_ip = peername[0] if peername else '0.0.0.0'

    if not check_rate_limit(client_ip):
        client_writer.close()
        await client_writer.wait_closed()
        return

    try:
        # Read the initial HTTP request header
        await client_reader.read(4096)
        
        # Send HTTP 101 WebSocket handshake acknowledgement
        response_header = (
            b"HTTP/1.1 101 Switching Protocols\r\n"
            b"Upgrade: websocket\r\n"
            b"Connection: Upgrade\r\n\r\n"
        )
        client_writer.write(response_header)
        await client_writer.drain()

        # Connect to local SSH daemon
        ssh_reader, ssh_writer = await asyncio.open_connection('127.0.0.1', 22)

        # Tune underlying sockets if available
        for writer in (client_writer, ssh_writer):
            sock = writer.get_extra_info('socket')
            if sock:
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

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
        backlog=1000,
        reuse_address=True
    )
    print("[+] Anti-DDoS bridge running with uvloop on 127.0.0.1:2222")
    async with server:
        await server.serve_forever()

if __name__ == '__main__':
    asyncio.run(main())
