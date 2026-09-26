import asyncio
import socket

class BridgeProtocol(asyncio.Protocol):
    """Zero-overhead bidirectional proxy protocol with automatic TCP backpressure."""
    def __init__(self, target_transport=None):
        self.transport = None
        self.peer_transport = target_transport

    def connection_made(self, transport):
        self.transport = transport
        sock = transport.get_extra_info('socket')
        if sock:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1048576)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1048576)
            except OSError:
                pass

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
    """Inbound client connection handler that sends HTTP 101 header and bridges to local SSH."""
    def __init__(self):
        super().__init__()
        self.handshake_sent = False

    def connection_made(self, transport):
        super().connection_made(transport)
        loop = asyncio.get_running_loop()
        asyncio.create_task(self._connect_ssh(loop))

    async def _connect_ssh(self, loop):
        try:
            # Connect directly to local SSH server
            _, ssh_protocol = await loop.create_connection(
                lambda: BridgeProtocol(target_transport=self.transport),
                '127.0.0.1', 
                22
            )
            self.peer_transport = ssh_protocol.transport
        except Exception:
            self.transport.close()

    def data_received(self, data):
        # HERE IS THE 101 RESPONSE: Triggered on the client's first incoming HTTP packet
        if not self.handshake_sent:
            self.handshake_sent = True
            response_header = (
                b"HTTP/1.1 101 Switching Protocols\r\n"
                b"Upgrade: websocket\r\n"
                b"Connection: Upgrade\r\n\r\n"
            )
            self.transport.write(response_header)
            return

        # Forward actual payload data after handshake
        if self.peer_transport:
            self.peer_transport.write(data)

async def main():
    loop = asyncio.get_running_loop()
    
    server = await loop.create_server(
        ClientBridgeProtocol,
        '127.0.0.1',
        2222,
        backlog=65535,
        reuse_port=True
    )
    print("[+] Low-Latency WS Proxy running on 127.0.0.1:2222")
    async with server:
        await server.serve_forever()

if __name__ == '__main__':
    asyncio.run(main())
