import http.server
import urllib.parse
import json
import os

class OAuthHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        print(f"\n=== OAUTH CALLBACK ===", flush=True)
        print(f"Path: {self.path}", flush=True)
        print(f"Params: {json.dumps({k: v[0][:80] if isinstance(v, list) and v else str(v)[:80] for k, v in params.items()}, indent=2)}", flush=True)
        
        # Save the code if present
        if 'code' in params:
            code = params['code'][0]
            fd = os.open('oauth_code.txt', os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, 'w') as f:
                f.write(code)
            print("Code received and saved.", flush=True)
        
        self.send_response(200)
        self.send_header('Content-Type', 'text/html')
        self.end_headers()
        self.wfile.write(b"<html><body><h1>Auth complete!</h1><p>You can close this window.</p><script>window.close()</script></body></html>")
    
    def log_message(self, format, *args):
        print(f"[OAuth] {format % args}", flush=True)

server = http.server.HTTPServer(('127.0.0.1', 13387), OAuthHandler)
print("OAuth server on :13387 (Windows side)", flush=True)
server.serve_forever()
