"""Loopback-only J.A.R.V.I.S. UI server and server-side OpenAI integration."""
from collections import deque
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, urlopen
import uuid

APP_DIR = Path(__file__).resolve().parent
ROOT = APP_DIR.parent
NOTES_FILE = ROOT / "notes.json"
ENV_FILE = ROOT / ".env"
HISTORY = deque(maxlen=20)  # ten user/assistant turns
HISTORY_LOCK = threading.Lock()
NOTES_LOCK = threading.Lock()
AI_LOCK = threading.Lock()


def load_dotenv(path=ENV_FILE):
    """Load simple KEY=value entries without overriding the process environment."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip("\"'")
        if key and key not in os.environ:
            os.environ[key] = value


load_dotenv()

BASE_NODES = [
    ("local-server", "Local HTTP server", "Serves the interface and local JSON API on 127.0.0.1:8765."),
    ("respond", "Assistant response", "Routes local commands first, then sends ordinary requests to the server-side AI."),
    ("dotenv", "Environment loader", "Reads OPENAI_API_KEY and optional OPENAI_MODEL from the process environment or .env."),
    ("openai-api", "OpenAI Responses API", "Generates JARVIS replies on the local Python server; the browser never receives the API key."),
    ("history", "Conversation history", "Keeps the latest ten user and assistant turns in server memory."),
    ("knowledge-store", "Knowledge store", "Stores user-taught notes in local notes.json, which is excluded from Git."),
    ("remember", "Remember command", "Remember that ... saves a note and flashes its node next time the brain opens."),
    ("forget", "Forget command", "Forget ... removes matching saved notes."),
    ("knowledge-query", "Knowledge query", "What do you know about ... searches saved notes and repository features."),
    ("time", "Time command", "Returns local system time without an AI request."),
    ("date", "Date command", "Returns the local date without an AI request."),
    ("show-brain", "Show brain command", "Opens the gold knowledge visualization only on an explicit brain command."),
    ("hide-brain", "Hide brain command", "Returns from the knowledge view to the cyan HUD."),
    ("web-open", "Open website", "Asks for confirmation before opening an external website."),
    ("web-search", "Web search", "Asks for confirmation before opening a web search page."),
    ("system-status", "System status", "Reports available CPU load, memory, and battery information."),
    ("timer", "Timer", "Starts a local countdown and announces when it completes."),
    ("confirm-action", "Action confirmation", "Website and search actions wait for an explicit confirmation."),
    ("voice-recognition", "Voice recognition", "Optional browser Web Speech API input, including spoken brain commands."),
    ("wake-word", "Wake word", "Optional Jarvis wake-word filter for voice input."),
    ("speech-synthesis", "Speech synthesis", "Reads replies aloud with a mute toggle and speaking animation."),
    ("hud-renderer", "HUD renderer", "Inline SVG cyan interface with rotating rings and a listening progress sweep."),
    ("mode-switcher", "Mode switcher", "Enforces the HUD default and the separate on-demand gold brain mode."),
    ("brain-canvas", "Brain canvas", "Draws the gold particle sphere, circuit shards, great-circle arcs, and labels."),
    ("node-hit-test", "Brain node selection", "Click a visible node to show its associated note or feature detail."),
    ("reduced-motion", "Reduced motion", "Stops continuous canvas drift when the OS requests reduced motion."),
    ("local-notes", "Local notes", "Notes stay in the local project file and are not uploaded by this server code."),
    ("command-bar", "Command bar", "Accepts typed commands, confirmation, mute, and optional voice controls."),
    ("responsive-ui", "Responsive layout", "HUD and command controls adapt to narrow and short windows."),
]
BASE_NODE_MAP = {item[0]: item for item in BASE_NODES}


def _read_notes():
    try:
        data = json.loads(NOTES_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []


def _write_notes(notes):
    temp = NOTES_FILE.with_suffix(".json.tmp")
    temp.write_text(json.dumps(notes, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(NOTES_FILE)


def _all_nodes(consume_flash=False):
    with NOTES_LOCK:
        notes = _read_notes()
        result = [
            {"id": key, "name": name, "note": note, "source": "repository", "flash": False}
            for key, name, note in BASE_NODES
        ]
        result.extend({**item, "source": "user", "flash": bool(item.get("flash"))} for item in notes)
        if consume_flash:
            changed = False
            for item in notes:
                if item.get("flash"):
                    item["flash"] = False
                    changed = True
            if changed:
                _write_notes(notes)
        return result


def _local_match(text):
    clean = text.strip()
    low = clean.casefold()
    if re.fullmatch(r"(?:show brain|open (?:the )?brain|show (?:your )?knowledge brain|brain)", low):
        return {"reply": "Knowledge brain online, sir.", "action": {"type": "show_brain"}, "speak": True}
    if re.fullmatch(r"(?:hide brain|back|interface)", low):
        return {"reply": "Interface restored, sir.", "action": {"type": "hide_brain"}, "speak": True}
    if re.fullmatch(r"(?:what time is it|time|current time)", low):
        return {"reply": f"It is {datetime.now().astimezone().strftime('%I:%M %p').lstrip('0')}, sir.", "speak": True}
    if re.fullmatch(r"(?:what(?:'s| is) the date|date|today(?:'s)? date)", low):
        return {"reply": f"Today is {datetime.now().astimezone().strftime('%A, %B %d, %Y').replace(' 0', ' ')}, sir.", "speak": True}

    remember = re.match(r"^(?:remember that|remember)\s+(.+?)\s*[.!?]*$", clean, re.I)
    if remember:
        note = remember.group(1).strip()
        if not note:
            return {"reply": "What would you like me to remember, sir?", "speak": True}
        title = note.split(".", 1)[0].split("!", 1)[0].split("?", 1)[0].strip()[:48] or "New note"
        with NOTES_LOCK:
            notes = _read_notes()
            node = {"id": "note-" + uuid.uuid4().hex[:10], "name": title, "note": note, "created_at": time.time(), "flash": True}
            notes.append(node)
            _write_notes(notes)
        return {"reply": "I shall remember that, sir.", "speak": True, "highlight": node["id"], "nodes": _all_nodes()}

    forget = re.match(r"^forget\s+(.+?)\s*[.!?]*$", clean, re.I)
    if forget:
        topic = forget.group(1).strip().casefold()
        with NOTES_LOCK:
            notes = _read_notes()
            kept = [n for n in notes if topic not in (str(n.get("name", "")) + " " + str(n.get("note", ""))).casefold()]
            removed = len(notes) - len(kept)
            if removed:
                _write_notes(kept)
        msg = f"I have forgotten {removed} matching note{'s' if removed != 1 else ''}, sir." if removed else "I found no matching note to forget, sir."
        return {"reply": msg, "speak": True, "nodes": _all_nodes()}

    know = re.match(r"^what do you know about\s+(.+?)\s*[?!.]*$", clean, re.I)
    if know:
        topic = know.group(1).strip().casefold()
        matches = [n for n in _all_nodes() if topic in n["name"].casefold() or topic in n["note"].casefold()]
        if matches:
            node = matches[-1] if matches[-1]["source"] == "user" else matches[0]
            return {"reply": f"{node['name']}: {node['note']}", "speak": True, "highlight": node["id"]}
    return None


def _system_status():
    parts = []
    try:
        load = os.getloadavg()[0]
        parts.append(f"CPU load average: {load:.2f}")
    except (AttributeError, OSError):
        pass
    try:
        mem = {}
        for line in Path("/proc/meminfo").read_text().splitlines():
            key, value = line.split(":", 1)
            mem[key] = int(value.strip().split()[0])
        total, available = mem["MemTotal"], mem.get("MemAvailable", 0)
        if total:
            parts.append(f"Memory used: {100 * (total - available) / total:.0f}%")
    except (OSError, ValueError, KeyError):
        pass
    try:
        for battery in Path("/sys/class/power_supply").iterdir():
            if (battery / "type").read_text().strip() == "Battery":
                capacity = (battery / "capacity").read_text().strip()
                parts.append(f"Battery: {capacity}%")
                break
    except OSError:
        pass
    return "System status, sir: " + ("; ".join(parts) if parts else "CPU, memory, and battery readings are unavailable on this system.")


def _url_action(url):
    candidate = url.strip().strip("<>")
    if not re.match(r"^https?://", candidate, re.I):
        candidate = "https://" + candidate
    parsed = urlsplit(candidate)
    if parsed.scheme not in ("http", "https") or not parsed.netloc or any(char.isspace() for char in candidate):
        return None
    return candidate


def _command_action(text):
    low = text.casefold().strip()
    if low in ("system status", "status"):
        return {"reply": _system_status(), "speak": True}
    timer = re.match(r"^(?:set\s+)?timer(?:\s+for)?\s+(\d+)\s*(seconds?|secs?|minutes?|mins?)$", low)
    if timer:
        value = int(timer.group(1))
        unit = timer.group(2)
        seconds = value * (60 if unit.startswith(("m", "min")) else 1)
        if seconds <= 0 or seconds > 86400:
            return {"reply": "Please choose a timer from one second to 24 hours, sir.", "speak": True}
        return {"reply": f"Timer set for {value} {unit}, sir.", "speak": True, "timer_seconds": seconds}
    if low.startswith(("open app ", "open file ", "open folder ")):
        return {"reply": "This web interface cannot open local apps or files, sir.", "speak": True}
    if low.startswith("open website "):
        target = text.strip()[len("open website "):].strip()
        url = _url_action(target)
        return {"reply": "Shall I proceed, sir?", "speak": True, "confirmation": {"type": "open_url", "url": url}} if url else {"reply": "Please give me a valid website address, sir.", "speak": True}
    if low.startswith("open ") and re.match(r"^open\s+(?:https?://|www\.|[\w-]+\.[a-z]{2,})", low):
        target = text.strip()[5:].strip()
        url = _url_action(target)
        return {"reply": "Shall I proceed, sir?", "speak": True, "confirmation": {"type": "open_url", "url": url}} if url else None
    search = re.match(r"^(?:web\s+search(?:\s+for)?|search\s+(?:the\s+)?web(?:\s+for)?|search\s+for)\s+(.+)$", text.strip(), re.I)
    if search:
        from urllib.parse import quote_plus
        query = search.group(1).strip()
        url = "https://www.google.com/search?q=" + quote_plus(query)
        return {"reply": "Shall I proceed, sir?", "speak": True, "confirmation": {"type": "open_url", "url": url}}
    return None


def _ai_reply(text):
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        return "My AI connection is not configured yet, sir. Add OPENAI_API_KEY to .env and try again.", True
    model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"
    instructions = (
        "You are J.A.R.V.I.S., a concise, polite personal assistant. Address the user as sir naturally. "
        "Answer in one to three sentences unless the user asks for more. Be clear about uncertainty. "
        "Never claim to have opened apps, files, or websites or performed actions unless the local UI confirms it."
    )
    with AI_LOCK:
        with HISTORY_LOCK:
            history = list(HISTORY)
        request_body = {
            "model": model,
            "instructions": instructions,
            "input": history + [{"role": "user", "content": text}],
            "max_output_tokens": 240,
            "store": False,
        }
        request = Request(
            "https://api.openai.com/v1/responses",
            data=json.dumps(request_body).encode("utf-8"),
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=25) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, OSError, ValueError):
            return "I can't reach my AI service at the moment, sir. Please check the internet connection and try again.", True
        answer = str(payload.get("output_text", "")).strip()
        if not answer:
            chunks = []
            for item in payload.get("output", []):
                if item.get("type") == "message":
                    for part in item.get("content", []):
                        if part.get("type") == "output_text":
                            chunks.append(part.get("text", ""))
            answer = "\n".join(chunks).strip()
        if not answer:
            answer = "I wasn't able to prepare a reply just now, sir. Please try again."
            return answer, True
        with HISTORY_LOCK:
            HISTORY.extend([{"role": "user", "content": text}, {"role": "assistant", "content": answer}])
        return answer, False


def respond(text):
    """Handle local commands before making a server-side AI request."""
    text = str(text or "").strip()
    if not text:
        return {"reply": "Please enter a command, sir.", "speak": True}
    local = _local_match(text)
    if local is not None:
        return local
    action = _command_action(text)
    if action is not None:
        return action
    answer, unavailable = _ai_reply(text)
    return {"reply": answer, "speak": True, "unavailable": unavailable}


def _send_json(handler, data, status=200):
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(APP_DIR), **kwargs)

    def do_GET(self):
        parsed = urlsplit(self.path)
        if parsed.path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return
        if parsed.path == "/api/knowledge":
            consume = parse_qs(parsed.query).get("consume") == ["1"]
            return _send_json(self, {"nodes": _all_nodes(consume_flash=consume)})
        if parsed.path == "/api/status":
            return _send_json(self, {"reply": _system_status()})
        if parsed.path == "/":
            self.path = "/jarvis.html"
        return super().do_GET()

    def do_POST(self):
        if urlsplit(self.path).path != "/api/respond":
            return self.send_error(404)
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > 32_000:
                return _send_json(self, {"reply": "That command is too long, sir.", "speak": False}, 413)
            payload = json.loads(self.rfile.read(length) or b"{}")
            text = str(payload.get("text", "")).strip()
        except (ValueError, AttributeError):
            return _send_json(self, {"reply": "I couldn't read that command, sir.", "speak": False}, 400)
        result = respond(text)
        if "nodes" not in result and (text.casefold().startswith(("remember", "forget"))):
            result["nodes"] = _all_nodes()
        _send_json(self, result)


if __name__ == "__main__":
    address = ("127.0.0.1", int(os.environ.get("JARVIS_PORT", "8765")))
    print(f"J.A.R.V.I.S. UI: http://{address[0]}:{address[1]}/")
    ThreadingHTTPServer(address, Handler).serve_forever()
