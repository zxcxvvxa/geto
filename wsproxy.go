package main

import (
	"bytes"
	"fmt"
	"io"
	"net"
	"os"
	"syscall"
	"time"
)

// Standard HTTP 101 Switching Protocols payload
var http101Response = []byte(
	"HTTP/1.1 101 Switching Protocols\r\n" +
		"Upgrade: websocket\r\n" +
		"Connection: Upgrade\r\n\r\n",
)

// Optimize TCP socket flags directly at kernel level
func optimizeSocket(conn net.Conn) {
	tcpConn, ok := conn.(*net.TCPConn)
	if !ok {
		return
	}

	// Disable Nagle's algorithm for instant packet delivery
	_ = tcpConn.SetNoDelay(true)

	// Set low-level socket options on Linux
	rawConn, err := tcpConn.SyscallConn()
	if err != nil {
		return
	}

	_ = rawConn.Control(func(fd uintptr) {
		// Enable TCP_QUICKACK (12) to force immediate ACKs and eliminate ~40ms delays
		_ = syscall.SetsockoptInt(int(fd), syscall.IPPROTO_TCP, 12, 1)
	})
}

func handleClient(clientConn net.Conn) {
	defer clientConn.Close()
	optimizeSocket(clientConn)

	// Read initial HTTP WebSocket upgrade GET request header
	buf := make([]byte, 4096)
	n, err := clientConn.Read(buf)
	if err != nil || n == 0 {
		return
	}

	// Reply immediately with HTTP 101 Switching Protocols header
	if _, err := clientConn.Write(http101Response); err != nil {
		return
	}

	// Dial local SSH daemon directly on port 22
	sshConn, err := net.DialTimeout("tcp", "127.0.0.1:22", 3*time.Second)
	if err != nil {
		return
	}
	defer sshConn.Close()
	optimizeSocket(sshConn)

	// Extract trailing payload bytes if client bundled SSH data in initial handshake packet
	headerEnd := bytes.Index(buf[:n], []byte("\r\n\r\n"))
	if headerEnd != -1 && headerEnd+4 < n {
		payload := buf[headerEnd+4 : n]
		if _, err := sshConn.Write(payload); err != nil {
			return
		}
	}

	// Bidirectional Kernel Zero-Copy (uses splice system call on Linux)
	done := make(chan struct{}, 2)

	go func() {
		_, _ = io.Copy(sshConn, clientConn)
		done <- struct{}{}
	}()

	go func() {
		_, _ = io.Copy(clientConn, sshConn)
		done <- struct{}{}
	}()

	// Wait until either direction terminates
	<-done
}

func main() {
	// Configure high-performance TCP listener with SO_REUSEADDR and SO_REUSEPORT
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
		fmt.Fprintf(os.Stderr, "[-] Failed to bind wsproxy listener: %v\n", err)
		os.Exit(1)
	}
	defer listener.Close()

	fmt.Println("[+] High-Performance Go WS Proxy running on 127.0.0.1:2222")

	for {
		conn, err := listener.Accept()
		if err != nil {
			continue
		}
		go handleClient(conn)
	}
}
