#!/usr/bin/env python3
"""Grill-Me-Sleek server.

Usage:
  python3 server.py << 'EOF'         # Push questions (non-blocking, returns URL)
    <json_data>
  EOF
  python3 server.py '<json_data>'    # Push questions (non-blocking, returns URL)
  python3 server.py --wait           # Block until user submits answers
  python3 server.py --done           # Signal session complete
  python3 server.py --serve          # Server: long-running background process

Architecture mirrors brainstorming's server.cjs:
  - One long-lived background server per session (started once, reused)
  - File-based content push: agent writes JSON to content/, server watches
  - Content directory polling (Python equivalent of brainstorming's fs.watch)
  - WebSocket live reload (same browser tab across all batches)
  - Process monitoring: exits when owner (harness) dies
  - Idle timeout: auto-shutdown after 30 min
  - Port conflict retry
  - Browser fallback: prints URL when auto-open fails (WSL etc.)
"""

import base64
import hashlib
import json
import os
import socket
import struct
import subprocess
import sys
import threading
import time
import webbrowser
from urllib.parse import parse_qs

# ---------------------------------------------------------------------------
# Paths — initialized in main() from GRILL_SESSION_DIR or derived from ppid
# ---------------------------------------------------------------------------

SESSION_DIR = ""
STATE_DIR = ""
CONTENT_DIR = ""
PID_FILE = ""
PORT_FILE = ""
LOG_FILE = ""
RESULT_FILE = ""

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_TEMPLATE_PATH = os.path.join(_SCRIPT_DIR, "template.html")


def _resolve_owner_pid():
    """Get the harness (grandparent) PID, like brainstorming's
    `ps -o ppid= -p $PPID`. Falls back to None if unreliable."""
    ppid = os.getppid()
    try:
        r = subprocess.run(
            ["ps", "-o", "ppid=", "-p", str(ppid)],
            capture_output=True,
            text=True,
            timeout=2,
        )
        gpid = int(r.stdout.strip())
        if gpid <= 1:
            return None
        return gpid
    except Exception:
        return None


def _find_live_session():
    """Find an existing session with a live server owned by the same owner.

    Only matches sessions whose directory name contains our owner PID, so
    different Claude instances (different harness PIDs) never collide.
    """
    owner = _resolve_owner_pid() or os.getppid()
    candidate = f"/tmp/grill-me-sleek-{owner}"
    pf = os.path.join(candidate, "state", "server.pid")
    try:
        with open(pf) as f:
            pid = int(f.read().strip())
        os.kill(pid, 0)
        return candidate
    except (FileNotFoundError, ValueError, OSError):
        pass
    return None


def _init_paths():
    global SESSION_DIR, STATE_DIR, CONTENT_DIR
    global PID_FILE, PORT_FILE, LOG_FILE, RESULT_FILE
    SESSION_DIR = os.environ.get("GRILL_SESSION_DIR", "")
    if not SESSION_DIR:
        existing = _find_live_session()
        if existing:
            SESSION_DIR = existing
        else:
            owner = _resolve_owner_pid() or os.getppid()
            SESSION_DIR = f"/tmp/grill-me-sleek-{owner}"
    STATE_DIR = os.path.join(SESSION_DIR, "state")
    CONTENT_DIR = os.path.join(SESSION_DIR, "content")
    PID_FILE = os.path.join(STATE_DIR, "server.pid")
    PORT_FILE = os.path.join(STATE_DIR, "server.port")
    LOG_FILE = os.path.join(STATE_DIR, "server.log")
    RESULT_FILE = os.path.join(STATE_DIR, "result.json")


def _ensure_dirs():
    os.makedirs(CONTENT_DIR, exist_ok=True)
    os.makedirs(STATE_DIR, exist_ok=True)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_IDLE_TIMEOUT_S = 30 * 60
_LIFECYCLE_INTERVAL_S = 60

_ws_clients = set()
_ws_clients_lock = threading.Lock()
_last_activity = time.time()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_free_port(host="127.0.0.1"):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        return s.getsockname()[1]


def _log(obj):
    print(json.dumps(obj, ensure_ascii=False), flush=True)


def _touch_activity():
    global _last_activity
    _last_activity = time.time()


def _remove_file(path):
    try:
        os.remove(path)
    except FileNotFoundError:
        pass


def _count_rounds():
    """Count existing question batches to determine current round number."""
    try:
        files = [
            f
            for f in os.listdir(CONTENT_DIR)
            if f.startswith("questions-") and f.endswith(".json")
        ]
        return len(files) + 1
    except FileNotFoundError:
        return 1


def _server_is_alive():
    """Check PID file + process liveness. Returns (alive, pid)."""
    try:
        with open(PID_FILE) as f:
            pid = int(f.read().strip())
    except (FileNotFoundError, ValueError):
        return False, None
    try:
        os.kill(pid, 0)
        return True, pid
    except OSError:
        _remove_file(PID_FILE)
        _remove_file(PORT_FILE)
        return False, pid


def _read_port():
    try:
        with open(PORT_FILE) as f:
            return int(f.read().strip())
    except (FileNotFoundError, ValueError):
        return None


# ---------------------------------------------------------------------------
# WebSocket (RFC 6455) — zero-dependency
# ---------------------------------------------------------------------------

_WS_MAGIC = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
_OP_TEXT = 0x01
_OP_CLOSE = 0x08
_OP_PING = 0x09
_OP_PONG = 0x0A


def _ws_accept(key):
    raw = hashlib.sha1((key + _WS_MAGIC).encode()).digest()
    return base64.b64encode(raw).decode()


def _ws_enc(op, payload):
    fin = 0x80
    n = len(payload)
    if n < 126:
        return bytes([fin | op, n]) + payload
    if n < 65536:
        return bytes([fin | op, 126]) + struct.pack(">H", n) + payload
    return bytes([fin | op, 127]) + struct.pack(">Q", n) + payload


def _ws_dec(buf):
    if len(buf) < 2:
        return None
    op = buf[0] & 0x0F
    masked = (buf[1] & 0x80) != 0
    n = buf[1] & 0x7F
    off = 2
    if n == 126:
        if len(buf) < 4:
            return None
        n = struct.unpack(">H", buf[2:4])[0]
        off = 4
    elif n == 127:
        if len(buf) < 10:
            return None
        n = struct.unpack(">Q", buf[2:10])[0]
        off = 10
    if not masked:
        return None
    mo = off
    do = off + 4
    total = do + n
    if len(buf) < total:
        return None
    mask = buf[mo:do]
    data = bytes(buf[do + i] ^ mask[i % 4] for i in range(n))
    return op, data, total


def _ws_broadcast(msg):
    frame = _ws_enc(_OP_TEXT, json.dumps(msg).encode())
    with _ws_clients_lock:
        dead = set()
        for ws in _ws_clients:
            try:
                ws.sendall(frame)
            except Exception:
                dead.add(ws)
        _ws_clients.difference_update(dead)


def _ws_add(c):
    with _ws_clients_lock:
        _ws_clients.add(c)


def _ws_del(c):
    with _ws_clients_lock:
        _ws_clients.discard(c)


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------


def _render_html(grill_data):
    with open(_TEMPLATE_PATH, encoding="utf-8") as f:
        tpl = f.read()
    esc = json.dumps(grill_data)
    # Escape for embedding inside JS string literal in HTML <script>:
    # 1. Double backslashes so JS doesn't eat JSON escapes
    # 2. Escape single quotes (our string delimiter)
    # 3. Escape < > so HTML parser doesn't see them as tags
    esc = esc.replace("\\", "\\\\").replace("'", "\\'")
    esc = esc.replace("<", "\\u003c").replace(">", "\\u003e")
    return tpl.replace("{{GRILL_DATA}}", esc)


def _done_data(title="All done", text="You can close this tab."):
    """Data dict for done mode — rendered by template.html."""
    return {"_mode": "done", "title": title, "description": text}


def _status_data(title, extra=""):
    """Data dict for status mode — rendered by template.html."""
    return {"_mode": "status", "title": title, "description": extra}


# ---------------------------------------------------------------------------
# Content watcher — like brainstorming's fs.watch + debounce
# ---------------------------------------------------------------------------


class _ContentWatcher:
    def __init__(self, server):
        self.server = server
        self._known = set()
        self._stop = threading.Event()
        try:
            self._known = set(f for f in os.listdir(CONTENT_DIR) if f.endswith(".json"))
        except FileNotFoundError:
            pass

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def stop(self):
        self._stop.set()

    def _run(self):
        while not self._stop.is_set():
            self._poll()
            self._stop.wait(0.3)

    def _poll(self):
        try:
            cur = set(f for f in os.listdir(CONTENT_DIR) if f.endswith(".json"))
        except FileNotFoundError:
            return
        new = cur - self._known
        if not new:
            return
        _touch_activity()
        self._known = cur
        newest = max(
            new,
            key=lambda f: os.path.getmtime(os.path.join(CONTENT_DIR, f)),
        )
        path = os.path.join(CONTENT_DIR, newest)
        try:
            with open(path) as f:
                data = json.load(f)
            if data.get("type") == "done":
                self.server.current_html = _render_html(_done_data())
                _ws_broadcast({"type": "reload"})
                _log({"type": "session-done"})
                threading.Thread(
                    target=lambda: (time.sleep(5), self.server.shutdown()),
                    daemon=True,
                ).start()
            else:
                self.server.current_html = _render_html(data)
                _ws_broadcast({"type": "reload"})
                _log({"type": "content-updated", "file": path})
        except Exception as e:
            _log({"type": "content-error", "error": str(e)})


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------


class _Handler:
    def __init__(self, conn, server):
        self.conn = conn
        self.server = server

    def handle(self):
        try:
            self._run()
        except Exception:
            pass
        finally:
            self.conn.close()

    def _run(self):
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = self.conn.recv(4096)
            if not chunk:
                return
            data += chunk
        hend = data.index(b"\r\n\r\n")
        hdr = data[:hend].decode("utf-8", errors="replace")
        lines = hdr.split("\r\n")
        parts = lines[0].split(" ")
        method = parts[0] if parts else "GET"
        path = parts[1] if len(parts) > 1 else "/"
        headers = {}
        for ln in lines[1:]:
            if ":" in ln:
                k, v = ln.split(":", 1)
                headers[k.strip().lower()] = v.strip()
        if headers.get("upgrade", "").lower() == "websocket":
            self._ws(headers, data, hend)
            return
        _touch_activity()
        if method == "GET" and path == "/":
            html = self.server.current_html or _render_html(
                _status_data(
                    "Waiting...",
                    "<p>Waiting for questions from the agent...</p>",
                )
            )
            self._html(html)
        elif method == "GET" and path == "/ws.js":
            self._ws_js()
        elif method == "POST" and path == "/submit":
            cl = int(headers.get("content-length", 0))
            body = data[hend + 4 :]
            while len(body) < cl:
                chunk = self.conn.recv(4096)
                if not chunk:
                    break
                body += chunk
            self._submit(body.decode("utf-8", errors="replace"))
        else:
            self._resp(404, b"")

    # -- WebSocket --

    def _ws(self, headers, raw, hend):
        key = headers.get("sec-websocket-key", "")
        if not key:
            self.conn.close()
            return
        accept = _ws_accept(key)
        resp = (
            "HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Accept: {accept}\r\n\r\n"
        )
        self.conn.sendall(resp.encode())
        _ws_add(self.conn)
        buf = raw[hend + 4 :]
        try:
            while True:
                chunk = self.conn.recv(4096)
                if not chunk:
                    break
                buf += chunk
                while buf:
                    r = _ws_dec(buf)
                    if r is None:
                        break
                    op, _pl, consumed = r
                    buf = buf[consumed:]
                    if op == _OP_TEXT:
                        _touch_activity()
                    elif op == _OP_CLOSE:
                        self.conn.sendall(_ws_enc(_OP_CLOSE, b""))
                        return
                    elif op == _OP_PING:
                        try:
                            self.conn.sendall(_ws_enc(_OP_PONG, _pl))
                        except Exception:
                            return
        except Exception:
            pass
        finally:
            _ws_del(self.conn)

    # -- Submit --

    def _submit(self, body):
        form = parse_qs(body)
        answers = {}
        notes = form.get("additional_notes", [""])[0]
        for k, v in form.items():
            if k.startswith("q_") and not k.endswith("_c"):
                raw = v[0]
                # Multi-select sends JSON array; single-select sends plain text
                try:
                    parsed = json.loads(raw)
                    selected = parsed if isinstance(parsed, list) else raw
                except (json.JSONDecodeError, TypeError):
                    selected = raw
                answers[k] = {
                    "selected": selected,
                    "custom_text": form.get(f"{k}_c", [""])[0],
                }
        # Handle custom_text without selected (user deselected all radios)
        for k, v in form.items():
            if k.startswith("q_") and k.endswith("_c"):
                qk = k[:-2]  # strip _c
                if qk not in answers and v[0]:
                    answers[qk] = {"selected": "", "custom_text": v[0]}
        result = {
            "answers": answers,
            "additional_notes": notes,
            "submitted_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        with open(RESULT_FILE, "w") as f:
            json.dump(result, f, ensure_ascii=False)
        self._html(
            _render_html(
                _status_data(
                    "Submitted.",
                    "<p>Waiting for the next batch...</p>"
                    "<p style='margin-top:16px;font-size:13px;"
                    "color:#9a9898'>"
                    "Stay on this tab &mdash; "
                    "new questions will appear here.</p>",
                )
            )
        )

    # -- Responses --

    def _html(self, html):
        self._resp(200, html.encode("utf-8"), "text/html; charset=utf-8")

    def _ws_js(self):
        js = (
            "(function(){"
            "var ws=new WebSocket('ws://'+location.host);"
            "ws.onmessage=function(e){"
            "var d=JSON.parse(e.data);"
            "if(d.type==='reload')location.href='/';"
            "};"
            "ws.onclose=function(){"
            "setTimeout(function(){location.href='/';},3000);"
            "};"
            "})();"
        )
        self._resp(
            200,
            js.encode("utf-8"),
            "application/javascript",
        )

    def _resp(self, code, body, ctype="application/octet-stream"):
        reason = "OK" if code == 200 else "Not Found"
        header = (
            f"HTTP/1.1 {code} {reason}\r\n"
            f"Content-Type: {ctype}\r\n"
            f"Content-Length: {len(body)}\r\n\r\n"
        ).encode()
        self.conn.sendall(header + body)


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------


class GrillServer:
    def __init__(self, port, host="127.0.0.1"):
        self.port = port
        self.host = host
        self.current_html = ""
        self._running = True
        self._sock = None
        self._watcher = None

    def start(self):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.settimeout(1.0)
        self._sock.bind((self.host, self.port))
        self._sock.listen(8)
        with open(PORT_FILE, "w") as f:
            f.write(str(self.port))
        _log({"type": "server-started", "port": self.port})
        self._watcher = _ContentWatcher(self)
        self._watcher.start()
        while self._running:
            try:
                conn, _ = self._sock.accept()
                threading.Thread(
                    target=lambda c: _Handler(c, self).handle(),
                    args=(conn,),
                    daemon=True,
                ).start()
            except TimeoutError:
                continue
            except OSError:
                break

    def shutdown(self):
        self._running = False
        if self._watcher:
            self._watcher.stop()
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Lifecycle monitoring
# ---------------------------------------------------------------------------


def _lifecycle(server, owner_pid):
    while server._running:
        time.sleep(_LIFECYCLE_INTERVAL_S)
        if owner_pid:
            try:
                os.kill(owner_pid, 0)
            except OSError:
                _log(
                    {
                        "type": "server-stopped",
                        "reason": "owner exited",
                    }
                )
                server.shutdown()
                return
        if time.time() - _last_activity > _IDLE_TIMEOUT_S:
            _log(
                {
                    "type": "server-stopped",
                    "reason": "idle timeout",
                }
            )
            server.shutdown()
            return


# ---------------------------------------------------------------------------
# Browser
# ---------------------------------------------------------------------------


def _open_browser(url):
    """Open URL in browser. WSL: try Windows host commands first."""
    is_wsl = bool(os.environ.get("WSL_DISTRO_NAME") or os.environ.get("WSLENV"))

    if is_wsl:
        # WSL: prioritize Windows host browser commands
        # cmd.exe start: first quoted arg is window title, need empty string
        for cmd in [
            ["cmd.exe", "/c", "start", '""', url],
            ["wslview", url],
            ["powershell.exe", "-c", f"Start-Process '{url}'"],
        ]:
            try:
                subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return True
            except FileNotFoundError:
                continue

    # Standard approaches

    try:
        if webbrowser.open(url):
            return True
    except Exception:
        pass

    for cmd in [
        ["xdg-open", url],
        ["open", url],
    ]:
        try:
            subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
        except Exception:
            continue
    return False


# ---------------------------------------------------------------------------
# Server mode (--serve) — long-running background process
# ---------------------------------------------------------------------------


def run_server():
    host = os.environ.get("GRILL_HOST", "127.0.0.1")
    owner_pid = (
        int(os.environ["GRILL_OWNER_PID"]) if "GRILL_OWNER_PID" in os.environ else None
    )
    _ensure_dirs()
    if owner_pid:
        try:
            os.kill(owner_pid, 0)
        except OSError:
            _log({"type": "owner-pid-invalid", "pid": owner_pid})
            owner_pid = None
    port = _find_free_port(host)
    server = GrillServer(port, host)
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))
    threading.Thread(
        target=_lifecycle,
        args=(server, owner_pid),
        daemon=True,
    ).start()
    try:
        server.start()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        _remove_file(PID_FILE)
        _remove_file(PORT_FILE)


# ---------------------------------------------------------------------------
# Client mode — push content (non-blocking) + wait for result
# ---------------------------------------------------------------------------


def _start_server_bg():
    """Start server as background subprocess, return port."""
    env = os.environ.copy()
    env["GRILL_SESSION_DIR"] = SESSION_DIR
    owner = _resolve_owner_pid()
    if owner:
        env["GRILL_OWNER_PID"] = str(owner)
    log_fh = open(LOG_FILE, "w")
    subprocess.Popen(
        [sys.executable, __file__, "--serve"],
        env=env,
        stdout=log_fh,
        stderr=log_fh,
    )
    # Wait for server to write port file (up to 5s)
    for _ in range(50):
        port = _read_port()
        if port is not None:
            return port
        time.sleep(0.1)
    _log({"error": "Server failed to start"})
    sys.exit(1)


def run_done():
    """Signal the server that the session is complete."""
    _ensure_dirs()
    path = os.path.join(CONTENT_DIR, "done.json")
    with open(path, "w") as f:
        json.dump({"type": "done"}, f)
    _log({"type": "done-signal-sent"})


def run_push(json_data):
    """Push questions to server, return URL immediately (non-blocking)."""
    _ensure_dirs()

    # Reuse running server or start new one
    alive, _ = _server_is_alive()
    port = _read_port()
    first_run = not alive or port is None
    browser_opened = True  # assume already open for subsequent rounds

    if first_run:
        _remove_file(PID_FILE)
        _remove_file(PORT_FILE)
        _remove_file(RESULT_FILE)
        port = _start_server_bg()
        url = f"http://localhost:{port}"
        browser_opened = _open_browser(url)
        if not browser_opened:
            print(
                f"Open this URL manually: {url}",
                file=sys.stderr,
            )

    # Push content: write JSON to content directory
    round_num = _count_rounds()
    ts = int(time.time() * 1000)
    path = os.path.join(CONTENT_DIR, f"questions-{ts}.json")
    with open(path, "w") as f:
        json.dump(json_data, f, ensure_ascii=False)

    # Clear previous result
    _remove_file(RESULT_FILE)

    url = f"http://localhost:{port}"
    _log(
        {
            "type": "pushed",
            "url": url,
            "round": round_num,
            "browser_opened": browser_opened,
        }
    )


def run_wait():
    """Block until user submits answers, then output result to stdout."""
    _ensure_dirs()
    try:
        while True:
            if os.path.exists(RESULT_FILE):
                time.sleep(0.05)
                with open(RESULT_FILE) as f:
                    result = json.load(f)
                _remove_file(RESULT_FILE)
                print(json.dumps(result, ensure_ascii=False))
                return
            time.sleep(0.3)
    except KeyboardInterrupt:
        print(
            json.dumps({"error": "Interrupted"}, ensure_ascii=False),
            file=sys.stderr,
        )
        sys.exit(1)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    _init_paths()

    if len(sys.argv) >= 2 and sys.argv[1] == "--serve":
        run_server()
        return

    if len(sys.argv) >= 2 and sys.argv[1] == "--done":
        run_done()
        return

    if len(sys.argv) >= 2 and sys.argv[1] == "--wait":
        run_wait()
        return

    # --push or default (no subcommand): push questions (non-blocking)
    if len(sys.argv) >= 2 and sys.argv[1] == "--push":
        raw = sys.argv[2] if len(sys.argv) >= 3 else sys.stdin.read()
    elif len(sys.argv) >= 2 and sys.argv[1] != "-":
        raw = sys.argv[1]
    else:
        raw = sys.stdin.read()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"Invalid JSON: {e}", file=sys.stderr)
        sys.exit(1)

    run_push(data)


if __name__ == "__main__":
    main()
