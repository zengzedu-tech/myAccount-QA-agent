"""Browser automation via Chrome DevTools Protocol — zero external dependencies."""

import base64
import json
import os
import random
import socket
import struct
import subprocess
import tempfile
import time
import urllib.request


# ---------------------------------------------------------------------------
# Minimal WebSocket client (RFC 6455) — stdlib only
# ---------------------------------------------------------------------------

class _WebSocket:
    """Minimal WebSocket client for Chrome DevTools Protocol."""

    def __init__(self, url: str):
        assert url.startswith("ws://"), f"Only ws:// supported, got {url}"
        rest = url[5:]
        slash = rest.find("/")
        host_port = rest[:slash] if slash != -1 else rest
        path = rest[slash:] if slash != -1 else "/"
        host, _, port = host_port.partition(":")
        port = int(port) if port else 80

        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.settimeout(30)
        self._sock.connect((host, int(port)))

        # WebSocket handshake
        key = base64.b64encode(os.urandom(16)).decode()
        req = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            f"Upgrade: websocket\r\n"
            f"Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            f"Sec-WebSocket-Version: 13\r\n"
            f"\r\n"
        )
        self._sock.sendall(req.encode())

        resp = b""
        while b"\r\n\r\n" not in resp:
            chunk = self._sock.recv(4096)
            if not chunk:
                raise ConnectionError("Connection closed during handshake")
            resp += chunk
        if b"101" not in resp.split(b"\r\n")[0]:
            raise ConnectionError(f"WebSocket handshake failed: {resp[:200]}")

    def _read_exact(self, n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            chunk = self._sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("WebSocket connection closed")
            buf += chunk
        return buf

    def send(self, data: str):
        """Send a text frame (client-masked per RFC 6455)."""
        payload = data.encode("utf-8")
        mask = os.urandom(4)
        header = bytearray()
        header.append(0x81)  # FIN + text opcode
        length = len(payload)
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.append(0x80 | 126)
            header.extend(struct.pack(">H", length))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack(">Q", length))
        header.extend(mask)
        masked = bytearray(len(payload))
        for i in range(len(payload)):
            masked[i] = payload[i] ^ mask[i % 4]
        self._sock.sendall(bytes(header) + bytes(masked))

    def recv(self) -> str:
        """Receive a complete text message (handles fragmentation)."""
        message = b""
        while True:
            hdr = self._read_exact(2)
            fin = (hdr[0] & 0x80) != 0
            opcode = hdr[0] & 0x0F
            is_masked = (hdr[1] & 0x80) != 0
            length = hdr[1] & 0x7F
            if length == 126:
                length = struct.unpack(">H", self._read_exact(2))[0]
            elif length == 127:
                length = struct.unpack(">Q", self._read_exact(8))[0]
            mask_key = self._read_exact(4) if is_masked else None
            payload = self._read_exact(length)
            if is_masked:
                payload = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))

            # Respond to pings
            if opcode == 0x9:
                pong_mask = os.urandom(4)
                pong = bytearray([0x8A])
                plen = len(payload)
                if plen < 126:
                    pong.append(0x80 | plen)
                else:
                    pong.append(0x80 | 126)
                    pong.extend(struct.pack(">H", plen))
                pong.extend(pong_mask)
                pong.extend(bytes(payload[i] ^ pong_mask[i % 4] for i in range(plen)))
                self._sock.sendall(bytes(pong))
                continue
            if opcode == 0x8:
                raise ConnectionError("WebSocket closed by server")

            message += payload
            if fin:
                return message.decode("utf-8")

    def close(self):
        try:
            close = bytearray([0x88, 0x80]) + os.urandom(4)
            self._sock.sendall(bytes(close))
        except OSError:
            pass
        try:
            self._sock.close()
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Chrome DevTools Protocol browser session
# ---------------------------------------------------------------------------

def _find_chrome() -> str:
    """Locate the Chrome/Chromium executable on Linux, Windows, or macOS."""
    candidates = []

    # Linux paths (Docker containers, standard installs)
    candidates.extend([
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
    ])

    # macOS paths
    candidates.extend([
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
    ])

    # Windows paths
    for env in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        base = os.environ.get(env, "")
        if base:
            candidates.append(os.path.join(base, "Google", "Chrome", "Application", "chrome.exe"))
    for env in ("PROGRAMFILES", "PROGRAMFILES(X86)"):
        base = os.environ.get(env, "")
        if base:
            candidates.append(os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe"))

    for path in candidates:
        if os.path.isfile(path):
            return path
    raise FileNotFoundError(
        "Chrome/Chromium not found. Checked:\n" + "\n".join(f"  {c}" for c in candidates)
        "Chrome/Edge not found. Checked:\n" + "\n".join(f"  {c}" for c in candidates)
    )


class BrowserSession:
    """Manages a Chrome browser session via CDP."""

    def __init__(self, headless: bool = True, screenshot_dir: str = "screenshots"):
        self.headless = headless
        self.screenshot_dir = screenshot_dir
    def __init__(self, headless: bool = True):
        self.headless = headless
        self._process = None
        self._ws: _WebSocket | None = None
        self._msg_id = 0
        self._port = random.randint(9200, 9399)
        self._user_data_dir = None

    def start(self):
        chrome = _find_chrome()
        self._user_data_dir = tempfile.mkdtemp(prefix="qa_chrome_")
        args = [
            chrome,
            f"--remote-debugging-port={self._port}",
            f"--user-data-dir={self._user_data_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-extensions",
            "--disable-popup-blocking",
            "--disable-dev-shm-usage",
            (
                "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
            "--window-size=1920,1080",
        ]
        if self.headless:
            args.append("--headless=new")
        args.append("about:blank")

        self._process = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        # Wait for Chrome DevTools to become available
        ws_url = None
        for _ in range(30):
            try:
                resp = urllib.request.urlopen(
                    f"http://localhost:{self._port}/json", timeout=2
                )
                pages = json.loads(resp.read())
                # Find the actual browser page, not extension background pages
                for page in pages:
                    if page.get("type") == "page" and not page.get("url", "").startswith("chrome-extension://"):
                        ws_url = page["webSocketDebuggerUrl"]
                        break
                if ws_url:
                    break
            except Exception:
                time.sleep(0.5)
        if not ws_url:
            self.stop()
            raise RuntimeError("Chrome did not start in time")

        self._ws = _WebSocket(ws_url)
        self._send("Page.enable")
        self._send("Runtime.enable")
        print(f"  [browser] Chrome started on port {self._port} (headless={self.headless})")

    def stop(self):
        if self._ws:
            self._ws.close()
            self._ws = None
        if self._process:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
            self._process = None

    # -- CDP helpers ---------------------------------------------------------

    def _send(self, method: str, params: dict | None = None) -> dict:
        """Send a CDP command and return its result (skipping async events)."""
        self._msg_id += 1
        msg = {"id": self._msg_id, "method": method}
        if params:
            msg["params"] = params
        self._ws.send(json.dumps(msg))
        target_id = self._msg_id
        while True:
            raw = self._ws.recv()
            data = json.loads(raw)
            if data.get("id") == target_id:
                if "error" in data:
                    raise RuntimeError(f"CDP error: {data['error']}")
                return data.get("result", {})
            # else it's an event — ignore and keep reading

    def _eval(self, expression: str) -> str:
        """Evaluate JS in the page and return the string result."""
        result = self._send("Runtime.evaluate", {
            "expression": expression,
            "returnByValue": True,
        })
        val = result.get("result", {})
        if val.get("type") == "undefined":
            return ""
        return str(val.get("value", ""))

    # -- Browser tools -------------------------------------------------------
    # -- Browser tools (same interface as before) ----------------------------

    def navigate(self, url: str) -> str:
        """Navigate to a URL, wait for Cloudflare if needed, return page title."""
        self._send("Page.navigate", {"url": url})
        time.sleep(3)
        # Wait for Cloudflare challenge to resolve
        for _ in range(15):
            title = self._eval("document.title")
            if "cloudflare" not in title.lower() and "attention required" not in title.lower():
                break
            time.sleep(1)
        current_url = self._eval("window.location.href")
        return f"Navigated to {current_url} — title: {title}"

    def click(self, selector: str) -> str:
        """Click an element using CDP mouse events for framework compatibility."""
        safe_sel = json.dumps(selector)
        # Get element center coordinates
        coords = self._eval(
            f"(function(){{"
            f"  var el=document.querySelector({safe_sel});"
            f"  if(!el) return 'NOT_FOUND';"
            f"  el.scrollIntoView({{block:'center'}});"
            f"  var r=el.getBoundingClientRect();"
            f"  return JSON.stringify({{x:r.x+r.width/2, y:r.y+r.height/2}});"
            f"}})()"
        )
        if coords == "NOT_FOUND":
            return f"Element '{selector}' not found."
        pos = json.loads(coords)
        x, y = pos["x"], pos["y"]
        # Dispatch real mouse events via CDP
        for etype in ("mousePressed", "mouseReleased"):
            self._send("Input.dispatchMouseEvent", {
                "type": etype,
                "x": x,
                "y": y,
                "button": "left",
                "clickCount": 1,
            })
        time.sleep(1)
        current_url = self._eval("window.location.href")
        return f"Clicked '{selector}'. Current URL: {current_url}"

    def fill(self, selector: str, value: str) -> str:
        """Fill a form field using CDP keyboard input (works with all frameworks)."""
        safe_sel = json.dumps(selector)
        # Focus the element and select any existing text so it gets replaced
        found = self._eval(
            f"(function(){{"
            f"  var el=document.querySelector({safe_sel});"
            f"  if(!el) return 'NOT_FOUND';"
            f"  el.focus();"
            f"  el.select();"
            f"  return 'OK';"
            f"}})()"
        )
        if found == "NOT_FOUND":
            return f"Element '{selector}' not found."
        self._send("Input.insertText", {"text": value})
        time.sleep(0.2)
        # Use CDP Input.insertText to simulate real keyboard input —
        # this fires native browser events that all frameworks detect.
        self._send("Input.insertText", {"text": value})
        time.sleep(0.2)
        # Dispatch a change event for frameworks that listen on blur/change
        self._eval(
            f"(function(){{"
            f"  var el=document.querySelector({safe_sel});"
            f"  if(el) el.dispatchEvent(new Event('change',{{bubbles:true}}));"
            f"}})()"
        )
        return f"Filled '{selector}' with value."

    def get_page_text(self) -> str:
        """Get visible text content of the page (truncated)."""
        text = self._eval("document.body.innerText")
        if len(text) > 5000:
            text = text[:5000] + "\n... (truncated)"
        return text

    def get_page_html(self) -> str:
        """Get the page body HTML, stripped of scripts/styles for readability."""
        html = self._eval(
            "(function(){"
            "  var clone = document.body.cloneNode(true);"
            "  clone.querySelectorAll('script,style,svg,link,noscript').forEach(function(e){e.remove()});"
            "  return clone.innerHTML;"
            "})()"
        )
        if len(html) > 15000:
            html = html[:15000] + "\n... (truncated)"
        return html

    def screenshot(self, filename: str = "screenshot.png") -> str:
        """Take a screenshot and save it to the configured screenshot directory."""
        os.makedirs(self.screenshot_dir, exist_ok=True)
        result = self._send("Page.captureScreenshot", {"format": "png"})
        data = base64.b64decode(result["data"])
        path = os.path.join(self.screenshot_dir, filename)
        """Take a screenshot and save it."""
        os.makedirs("screenshots", exist_ok=True)
        result = self._send("Page.captureScreenshot", {"format": "png"})
        data = base64.b64decode(result["data"])
        path = os.path.join("screenshots", filename)
        with open(path, "wb") as f:
            f.write(data)
        return f"Screenshot saved to {path}"

    def screenshot_base64(self) -> str:
        """Take a screenshot and return base64."""
        result = self._send("Page.captureScreenshot", {"format": "png"})
        return result["data"]

    def get_current_url(self) -> str:
        """Return the current page URL."""
        return self._eval("window.location.href")

    def press_key(self, key: str) -> str:
        """Press a keyboard key (e.g. 'Enter', 'Tab')."""
        key_map = {
            "Enter":  (13, "\r"),
            "Tab":    (9, ""),
            "Escape": (27, ""),
            "Backspace": (8, ""),
        }
        code, text = key_map.get(key, (0, ""))
        params_down = {
            "type": "rawKeyDown",
            "key": key,
            "code": key,
            "windowsVirtualKeyCode": code,
            "nativeVirtualKeyCode": code,
        }
        if text:
            params_down["text"] = text
        self._send("Input.dispatchKeyEvent", params_down)
        if text:
            self._send("Input.dispatchKeyEvent", {
                "type": "char",
                "key": text,
                "code": key,
                "text": text,
                "windowsVirtualKeyCode": code,
            })
        self._send("Input.dispatchKeyEvent", {
            "type": "keyUp",
            "key": key,
            "code": key,
            "windowsVirtualKeyCode": code,
            "nativeVirtualKeyCode": code,
        })
        return f"Pressed key '{key}'."

    def wait(self, ms: int = 2000) -> str:
        """Wait for a specified number of milliseconds."""
        time.sleep(ms / 1000)
        return f"Waited {ms}ms."


# ---------------------------------------------------------------------------
# Tool execution dispatcher
# ---------------------------------------------------------------------------

# Tool definitions (unchanged — used by agent.py)
# ---------------------------------------------------------------------------

TOOL_DEFINITIONS = [
    {
        "name": "navigate",
        "description": "Navigate the browser to a URL.",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "The URL to navigate to."}
            },
            "required": ["url"],
        },
    },
    {
        "name": "click",
        "description": "Click an element on the page by CSS selector.",
        "input_schema": {
            "type": "object",
            "properties": {
                "selector": {
                    "type": "string",
                    "description": "CSS selector of the element to click.",
                }
            },
            "required": ["selector"],
        },
    },
    {
        "name": "fill",
        "description": "Type text into a form field identified by CSS selector.",
        "input_schema": {
            "type": "object",
            "properties": {
                "selector": {
                    "type": "string",
                    "description": "CSS selector of the input field.",
                },
                "value": {
                    "type": "string",
                    "description": "The text to type into the field.",
                },
            },
            "required": ["selector", "value"],
        },
    },
    {
        "name": "get_page_text",
        "description": "Get the visible text content of the current page.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_page_html",
        "description": "Get the HTML source of the current page to inspect its structure and find selectors.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "screenshot",
        "description": "Take a screenshot of the current page.",
        "input_schema": {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "Filename for the screenshot (default: screenshot.png).",
                }
            },
        },
    },
    {
        "name": "get_current_url",
        "description": "Get the current page URL.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "press_key",
        "description": "Press a keyboard key (e.g. 'Enter', 'Tab').",
        "input_schema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "The key to press."}
            },
            "required": ["key"],
        },
    },
    {
        "name": "wait",
        "description": "Wait for a specified duration in milliseconds.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ms": {
                    "type": "integer",
                    "description": "Milliseconds to wait (default: 2000).",
                }
            },
        },
    },
]


def execute_tool(session: BrowserSession, tool_name: str, tool_input: dict) -> str:
    """Execute a browser tool by name and return the result."""
    if tool_name == "navigate":
        return session.navigate(tool_input["url"])
    elif tool_name == "click":
        return session.click(tool_input["selector"])
    elif tool_name == "fill":
        return session.fill(tool_input["selector"], tool_input["value"])
    elif tool_name == "get_page_text":
        return session.get_page_text()
    elif tool_name == "get_page_html":
        return session.get_page_html()
    elif tool_name == "screenshot":
        return session.screenshot(tool_input.get("filename", "screenshot.png"))
    elif tool_name == "get_current_url":
        return session.get_current_url()
    elif tool_name == "press_key":
        return session.press_key(tool_input["key"])
    elif tool_name == "wait":
        return session.wait(tool_input.get("ms", 2000))
    else:
        return f"Unknown tool: {tool_name}"
