"""Small standard-library launcher for the J.A.R.V.I.S. interface."""
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def do_POST(self):
        if self.path != "/api/respond":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
            text = str(payload.get("text", "")).strip()
        except (ValueError, AttributeError):
            self.send_error(400, "Expected JSON with a text field")
            return
        reply = respond(text)
        body = json.dumps({"reply": reply, "speak": False}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


def respond(text: str) -> str:
    """Assistant integration point; connect the project's assistant here."""
    if not text:
        return "Please enter a command."
    return "Assistant backend is not configured in this repository yet."


if __name__ == "__main__":
    address = ("127.0.0.1", 8765)
    print(f"J.A.R.V.I.S. UI: http://{address[0]}:{address[1]}/jarvis.html")
    ThreadingHTTPServer(address, Handler).serve_forever()
