"""Local dev server — serves static files + /api/events from CSV."""
import http.server
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from api.events import load_all_csv

PORT = 3456

class DevHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/api/events"):
            items = load_all_csv()
            body = json.dumps({"items": items, "count": len(items), "source": "csv"})
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body.encode())
        else:
            super().do_GET()

    def log_message(self, format, *args):
        if "/api/" in str(args[0]):
            super().log_message(format, *args)

os.chdir(os.path.dirname(__file__))
print(f"Dev server at http://localhost:{PORT}")
http.server.HTTPServer(("", PORT), DevHandler).serve_forever()
