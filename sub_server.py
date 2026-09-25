import base64
from http.server import HTTPServer, BaseHTTPRequestHandler

PORT = 8000
SECRET_PATH = "/sub"

SNI_HOST = "firebaseremoteconfigrealtime.googleapis.com"
TARGET_PORT = 443

# Exact SSH link string
EXACT_SSH_LINK = (
    "ssh://cxlvin:cxlvin@firebaseremoteconfigrealtime.googleapis.com:443"
    "?KUX3sw04Vw3D4VZXnUUdxzm0ktSn8qvoPZ3hvirbN91tTqyY31h2V7XVKv73sB2Iq1Ien3DZ4YdTXcLkzxHX2C6Zqm2PL+v2yXb0zBDM8Os8kUjdJaB3nqafX1ffGuaRkmQSQmVVgKWe5GOYBZdTtqjnXiYz2zTjOgTxNl0B/9VFkGkqaxwznWdyY91SDIg1Kp7J95dv2LKhJiBpLPEvEYdj0xK1bXw7erwcSzEmmfbodvu/LLi/KyMjiiRm+S64#ssh-ws"
)

def extract_run_app_host(host_header):
    """Extracts host without port from HTTP Host header for authority/host."""
    if host_header:
        return host_header.split(':')[0]
    return "127.0.0.1"

def generate_subscription(host_header):
    run_app_host = extract_run_app_host(host_header)

    vless_link = (
        f"vless://cxlvin777@{SNI_HOST}:{TARGET_PORT}"
        f"?encryption=none&type=ws&headerType=none"
        f"&path=%2FCxlvinVlWS%3Fed%3D2560&security=tls"
        f"&host={run_app_host}&sni={SNI_HOST}#vless-ws"
    )

    trojan_link = (
        f"trojan://Cxlvin777@{SNI_HOST}:{TARGET_PORT}"
        f"?type=ws&headerType=none"
        f"&path=%2FCxlvinTRWS%3Fed%3D2560&security=tls"
        f"&host={run_app_host}&sni={SNI_HOST}#trojan-ws"
    )

    raw_payload = f"{vless_link}\n{trojan_link}\n{EXACT_SSH_LINK}\n"
    return base64.b64encode(raw_payload.encode('utf-8'))

class SubHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        host_header = self.headers.get('Host', '')
        
        if self.path == SECRET_PATH or self.path.startswith(f"{SECRET_PATH}?"):
            sub_body = generate_subscription(host_header)
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.send_header('Subscription-Userinfo', 'upload=0; download=0; total=107374182400; expire=0')
            self.send_header('Profile-Update-Interval', '24')
            self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
            self.end_headers()
            self.wfile.write(sub_body)
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"404 Not Found")

    def log_message(self, format, *args):
        return

if __name__ == '__main__':
    server = HTTPServer(('0.0.0.0', PORT), SubHandler)
    print(f"Subscription server running on port {PORT}...")
    server.serve_forever()
