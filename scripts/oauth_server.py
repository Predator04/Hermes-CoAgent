import http.server
import urllib.parse
import json
import os
import tempfile

class OAuthHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            self._handle_oauth()
        except Exception as e:
            print(f"[OAuth] Error handling request: {e}", flush=True)
            try:
                self.send_response(500)
                self.send_header('Content-Type', 'text/plain')
                self.end_headers()
                self.wfile.write(b"Internal Server Error")
            except Exception:
                pass

    def _handle_oauth(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        print(f"\n=== OAUTH CALLBACK ===", flush=True)
        print(f"Path: {self.path}", flush=True)
        print(f"Params: {json.dumps({k: ('<redacted>' if k in ('code', 'state', 'error_description') else (v[0][:80] if isinstance(v, list) and v else str(v)[:80])) for k, v in params.items()}, indent=2)}", flush=True)
        
        # Save the code if present
        code_received = False
        if 'code' in params and params['code']:
            code = params['code'][0]
            target = 'oauth_code.txt'
            fd, tmp_path = tempfile.mkstemp(prefix='.oauth_code_', suffix='.tmp',
                                            dir=os.path.dirname(os.path.abspath(target)) or '.')
            try:
                with os.fdopen(fd, 'w') as f:
                    f.write(code)
                os.replace(tmp_path, target)
            except Exception:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
            code_received = True
            print("Code received and saved.", flush=True)
        
        self.send_response(200)
        self.send_header('Content-Type', 'text/html')
        self.end_headers()
        if code_received:
            self.wfile.write(b"<html><body><h1>Auth complete!</h1><p>You can close this window.</p><script>window.close()</script></body></html>")
        else:
            self.wfile.write(b"<html><body><h1>No code received</h1><p>Check the callback URL.</p></body></html>")
    
    def log_message(self, format, *args):
        print(f"[OAuth] {format % args}", flush=True)

if __name__ == "__main__":
    server = http.server.HTTPServer(('127.0.0.1', 13387), OAuthHandler)
    print("OAuth server on :13387 (Windows side)", flush=True)
    server.serve_forever()
