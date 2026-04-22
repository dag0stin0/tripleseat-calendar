"""Local dev server — serves static files + /api/events via the real Vercel handler."""
import http.server
import os
import sys
from io import BytesIO

sys.path.insert(0, os.path.dirname(__file__))
from api.events import handler as api_handler

PORT = 3456


class DevHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/api/events"):
            proxy = api_handler.__new__(api_handler)
            proxy.path = self.path
            proxy.wfile = BytesIO()
            proxy._headers = {}
            proxy._status = 200

            def send_response(code):
                proxy._status = code
            def send_header(k, v):
                proxy._headers[k] = v
            def end_headers():
                pass

            proxy.send_response = send_response
            proxy.send_header = send_header
            proxy.end_headers = end_headers
            proxy.do_GET()

            body = proxy.wfile.getvalue()
            self.send_response(proxy._status)
            for k, v in proxy._headers.items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)
        else:
            super().do_GET()

    def log_message(self, fmt, *args):
        if args and "/api/" in str(args[0]):
            super().log_message(fmt, *args)


if __name__ == "__main__":
    os.chdir(os.path.dirname(__file__))
    print(f"Dev server at http://localhost:{PORT}")
    http.server.HTTPServer(("", PORT), DevHandler).serve_forever()
