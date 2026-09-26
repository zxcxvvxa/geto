package main

import (
	"bytes"
	"io"
	"net"
	"os"
	"sync"
	"syscall"
	"time"
)

var http101Response = []byte(
	"HTTP/1.1 101 Switching Protocols\r\n" +
		"Upgrade: websocket\r\n" +
		"Connection: Upgrade\r\n\r\n",
)

// Reusable byte buffer pool to eliminate GC allocations per request
var bufPool = sync.Pool{
	New: func() any {
		b := make([]byte, 4096)
		return &b
	},
}

// Low-level socket tuner: disables Nagle's algorithm & forces immediate TCP ACKs
func tuneFD(fd uintptr) {
	_ = syscall.SetsockoptInt(int(fd), syscall.IPPROTO_TCP, syscall.TCP_NODELAY, 1)
	_ = syscall.SetsockoptInt(int(fd), syscall.IPPROTO_TCP, 12, 1) // 12 = TCP_QUICKACK
}

func optimizeConn(conn net.Conn) {
	if tcpConn, ok := conn.(*net.TCPConn); ok {
		if raw, err := tcpConn.SyscallConn(); err == nil {
			_ = raw.Control(tuneFD)
		}
	}
}

func handleClient(clientConn net.Conn) {
	defer clientConn.Close()
	optimizeConn(clientConn)

	// Fetch zero-allocation buffer from sync.Pool
	bufPtr := bufPool.Get().(*[]byte)
	buf := *bufPtr
	defer bufPool.Put(bufPtr)

	n, err := clientConn.Read(buf)
	if err != nil || n == 0 {
		return
	}

	// Send HTTP 101 Switching Protocols handshake instantly
	if _, err := clientConn.Write(http101Response); err != nil {
		return
	}

	// Fast Dialer with pre-handshake socket optimization
	dialer := net.Dialer{
		Timeout: 2 * time.Second,
		Control: func(network, address string, c syscall.RawConn) error {
			return c.Control(tuneFD)
		},
	}

	sshConn, err := dialer.Dial("tcp", "127.0.0.1:22")
	if err != nil {
		return
	}
	defer sshConn.Close()

	// Forward initial pipelined SSH payload if sent along with HTTP GET header
	if headerEnd := bytes.Index(buf[:n], []byte("\r\n\r\n")); headerEnd != -1 && headerEnd+4 < n {
		if _, err := sshConn.Write(buf[headerEnd+4 : n]); err != nil {
			return
		}
	}

	// Zero-copy kernel splice with active half-close signaling
	var wg sync.WaitGroup
	wg.Add(2)

	pipe := func(dst, src net.Conn) {
		defer wg.Done()
		_, _ = io.Copy(dst, src)
		if tc, ok := dst.(*net.TCPConn); ok {
			_ = tc.CloseWrite()
		}
	}

	go pipe(sshConn, clientConn)
	go pipe(clientConn, sshConn)

	wg.Wait()
}

func main() {
	lc := net.ListenConfig{
		Control: func(network, address string, c syscall.RawConn) error {
			return c.Control(func(fd uintptr) {
				_ = syscall.SetsockoptInt(int(fd), syscall.SOL_SOCKET, syscall.SO_REUSEADDR, 1)
				_ = syscall.SetsockoptInt(int(fd), syscall.SOL_SOCKET, 15, 1) // 15 = SO_REUSEPORT
			})
		},
	}

	listener, err := lc.Listen(nil, "tcp", "127.0.0.1:2222")
	if err != nil {
		os.Exit(1)
	}
	defer listener.Close()

	for {
		conn, err := listener.Accept()
		if err != nil {
			continue
		}
		go handleClient(conn)
	}
}
