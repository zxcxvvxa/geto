import asyncio
import socket

# Constant 101 HTTP Upgrade Response
HTTP_101_RESPONSE = (
    b"HTTP/1.1 101 Switching Protocols\r\n"
    b"Upgrade: websocket\r\n"
    b"Connection: Upgrade\r\n\r\n"
)

def optimize_socket(sock):
    """Apply zero-delay kernel flags to local loopback socket."""
    if not sock:
        return
    # Disable Nagle's algorithm for instant packet dispatch
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    
    # Disable delayed ACKs on Linux (prevents ~40ms ACK delay overhead)
    if hasattr(socket, "TCP_QUICKACK"):
        try:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_QUICKACK, 1)
        except OSError:
            pass


class BridgeProtocol(asyncio.Protocol):
    """Zero-overhead bidirectional proxy protocol with flow control."""
    def __init__(self, target_transport=None):
        self.transport = None
        self.peer_transport = target_transport

    def connection_made(self, transport):
        self.transport = transport
        optimize_socket(transport.get_extra_info('socket'))

    def data_received(self, data):
        if self.peer_transport:
            self.peer_transport.write(data)

    def pause_writing(self):
        if self.peer_transport:
            self.peer_transport.pause_reading()

    def resume_writing(self):
        if self.peer_transport:
            self.peer_transport.resume_reading()

    def connection_lost(self, exc):
        if self.peer_transport:
            self.peer_transport.close()
            self.peer_transport = None


class ClientBridgeProtocol(BridgeProtocol):
    """Client handler with fast 101 handshake, buffer queueing, and stream bridging."""
    def __init__(self):
        super().__init__()
        self.handshake_sent = False
        self.pending_buffer = bytearray()

    def connection_made(self, transport):
        super().connection_made(transport)
        loop = asyncio.get_running_loop()
        asyncio.create_task(self._connect_ssh(loop))

    async def _connect_ssh(self, loop):
        try:
            _, ssh_protocol = await loop.create_connection(
                lambda: BridgeProtocol(target_transport=self.transport),
                '127.0.0.1', 
                22
            )
            self.peer_transport = ssh_protocol.transport
            
            # Flush any payload received while SSH socket was establishing
            if self.pending_buffer:
                self.peer_transport.write(self.pending_buffer)
                self.pending_buffer = None
        except Exception:
            self.transport.close()

    def data_received(self, data):
        if not self.handshake_sent:
            self.handshake_sent = True
            self.transport.write(HTTP_101_RESPONSE)
            
            # Find boundary of initial HTTP request (\r\n\r\n)
            header_end = data.find(b"\r\n\r\n")
            if header_end != -1:
                # Retain payload bytes attached to the initial handshake packet
                payload = data[header_end + 4:]
                if payload:
                    if self.peer_transport:
                        self.peer_transport.write(payload)
                    else:
                        self.pending_buffer.extend(payload)
            return

        if self.peer_transport:
            self.peer_transport.write(data)
        elif self.pending_buffer is not None:
            self.pending_buffer.extend(data)


async def main():
    loop = asyncio.get_running_loop()
    
    server = await loop.create_server(
        ClientBridgeProtocol,
        '127.0.0.1',
        2222,
        backlog=65535,
        reuse_port=True
    )
    print("[+] Zero-Delay WS Proxy running on 127.0.0.1:2222")
    async with server:
        await server.serve_forever()


if __name__ == '__main__':
    asyncio.run(main())
