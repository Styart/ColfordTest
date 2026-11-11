"""Tiny web server: serves static/index.html and the JSON API.

  GET  /             the help desk page
  GET  /api/config   which model is in use (so the page can show a MOCK label straight away)
  POST /api/ask      {"question": "...", "simulate_failure": false} -> answer JSON, or an error JSON with a non-200 status
"""
import argparse
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import helpdesk

PAGE = helpdesk.ROOT / "static" / "index.html"
MAX_BODY_BYTES = 10_000

# Limits so a public demo cannot run up the API bill. Kept in memory: they reset when the server restarts.
PER_MINUTE_LIMIT = 10  # questions per visitor (IP address) per minute
DAILY_LIMIT = 300      # questions per day from everyone together
recent = {}            # IP address -> times of that visitor's questions in the last minute
today = {"date": "", "count": 0}
limit_lock = threading.Lock()  # the server handles requests on several threads


def over_limit(ip, now=None):
    """Count one question from `ip`. Return an error message if a limit is reached, else None."""
    now = now or time.time()
    with limit_lock:
        date = time.strftime("%Y-%m-%d", time.gmtime(now))
        if today["date"] != date:  # a new day: start counting again
            today.update(date=date, count=0)
            recent.clear()
        times = [t for t in recent.get(ip, []) if now - t < 60]
        if len(times) >= PER_MINUTE_LIMIT:
            return "Too many questions in a short time. Please wait a minute and try again."
        if today["count"] >= DAILY_LIMIT:
            return "This demo has reached its daily question limit. Please try again tomorrow."
        recent[ip] = times + [now]
        today["count"] += 1
        return None


class Handler(BaseHTTPRequestHandler):
    timeout = 15  # seconds: drop a connection that stops sending, so it cannot hold a thread forever

    def send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        settings = self.server.settings
        if self.path in ("/", "/index.html"):
            body = PAGE.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/api/config":
            self.send_json(200, {"model": helpdesk.model_label(settings), "mock": settings["provider"] == "mock",
                                 "configured": settings["provider"] == "mock" or settings["configured"]})
        else:
            self.send_json(404, {"error": "not_found", "message": "Not found."})

    def do_POST(self):
        if self.path != "/api/ask":
            return self.send_json(404, {"error": "not_found", "message": "Not found."})
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if length < 0:  # read(-1) would read until the client hangs up, ignoring the size limit
            return self.send_json(400, {"error": "bad_length", "message": "Invalid Content-Length header."})
        if length > MAX_BODY_BYTES:
            return self.send_json(413, {"error": "too_large", "message": "Request is too large."})
        try:
            data = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            data = None
        if not isinstance(data, dict):
            return self.send_json(400, {"error": "bad_json", "message": "Send a JSON object like {\"question\": \"...\"}."})
        limit_message = over_limit(self.client_address[0])
        if limit_message:
            return self.send_json(429, {"error": "too_many_requests", "message": limit_message})
        status, payload = helpdesk.handle_question(str(data.get("question") or ""), self.server.settings,
                                                   simulate_failure=data.get("simulate_failure") is True)
        if status != 200:
            print(f"ask failed: {payload['error']}")  # the kind only: never the key or the request body
        self.send_json(status, payload)


def main():
    parser = argparse.ArgumentParser(description="BrightPath help desk web server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--mock", action="store_true", help="use the labelled mock model instead of a real one")
    args = parser.parse_args()

    sys.stdout.reconfigure(line_buffering=True)  # show our log lines immediately, even when piped
    helpdesk.load_env_file()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.settings = helpdesk.get_settings(mock=args.mock)
    print(f"Model: {helpdesk.model_label(server.settings)}")
    if server.settings["provider"] != "mock" and not server.settings["configured"]:
        print("Warning: no model configured - questions will return a 'no model configured' error. "
              "Add ANTHROPIC_API_KEY to .env or start with --mock.")
    print(f"Help desk running at http://{args.host}:{args.port}  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
