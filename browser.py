"""Playwright browser tools for the QA agent."""

import base64
import os
from playwright.sync_api import sync_playwright, Browser, Page


class BrowserSession:
    """Manages a Playwright browser session with actions the AI agent can invoke."""

    def __init__(self, headless: bool = True):
        self.headless = headless
        self._playwright = None
        self._browser: Browser | None = None
        self._page: Page | None = None

    def start(self):
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(
            headless=self.headless,
            args=[
                "--disable-blink-features=AutomationControlled",
            ],
        )
        self._page = self._browser.new_page(
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1920, "height": 1080},
        )
        # Remove the webdriver flag that Cloudflare checks
        self._page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        """)

    def stop(self):
        if self._browser:
            self._browser.close()
        if self._playwright:
            self._playwright.stop()
        self._browser = None
        self._page = None
        self._playwright = None

    @property
    def page(self) -> Page:
        if self._page is None:
            raise RuntimeError("Browser session not started. Call start() first.")
        return self._page

    def navigate(self, url: str) -> str:
        """Navigate to a URL and return the page title."""
        self.page.goto(url, wait_until="domcontentloaded", timeout=15000)
        return f"Navigated to {self.page.url} — title: {self.page.title()}"

    def click(self, selector: str) -> str:
        """Click an element matching the CSS selector."""
        self.page.click(selector, timeout=5000)
        self.page.wait_for_load_state("domcontentloaded", timeout=10000)
        return f"Clicked '{selector}'. Current URL: {self.page.url}"

    def fill(self, selector: str, value: str) -> str:
        """Fill a form field with a value."""
        self.page.fill(selector, value, timeout=5000)
        return f"Filled '{selector}' with value."

    def get_page_text(self) -> str:
        """Get visible text content of the page (truncated)."""
        text = self.page.inner_text("body")
        if len(text) > 5000:
            text = text[:5000] + "\n... (truncated)"
        return text

    def get_page_html(self) -> str:
        """Get the page HTML (truncated) for inspecting structure."""
        html = self.page.content()
        if len(html) > 10000:
            html = html[:10000] + "\n... (truncated)"
        return html

    def screenshot(self, filename: str = "screenshot.png") -> str:
        """Take a screenshot and save it. Returns the file path."""
        os.makedirs("screenshots", exist_ok=True)
        path = os.path.join("screenshots", filename)
        self.page.screenshot(path=path, full_page=False)
        return f"Screenshot saved to {path}"

    def screenshot_base64(self) -> str:
        """Take a screenshot and return it as a base64 string."""
        raw = self.page.screenshot(full_page=False)
        return base64.b64encode(raw).decode("utf-8")

    def get_current_url(self) -> str:
        """Return the current page URL."""
        return self.page.url

    def press_key(self, key: str) -> str:
        """Press a keyboard key (e.g. 'Enter', 'Tab')."""
        self.page.keyboard.press(key)
        return f"Pressed key '{key}'."

    def wait(self, ms: int = 2000) -> str:
        """Wait for a specified number of milliseconds."""
        self.page.wait_for_timeout(ms)
        return f"Waited {ms}ms."


# Tool definitions for Claude API tool_use
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
