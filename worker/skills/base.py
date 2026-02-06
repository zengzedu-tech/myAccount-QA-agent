"""Base class that every worker skill must implement."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


# Standard browser tools shared by all skills.
# Skills get these automatically — no need to redeclare them.
BROWSER_TOOL_DECLARATIONS = [
    {
        "name": "navigate",
        "description": "Navigate the browser to a URL.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "url": {"type": "STRING", "description": "The URL to navigate to."}
            },
            "required": ["url"],
        },
    },
    {
        "name": "click",
        "description": "Click an element on the page by CSS selector.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "selector": {
                    "type": "STRING",
                    "description": "CSS selector of the element to click.",
                }
            },
            "required": ["selector"],
        },
    },
    {
        "name": "fill",
        "description": "Type text into a form field identified by CSS selector.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "selector": {
                    "type": "STRING",
                    "description": "CSS selector of the input field.",
                },
                "value": {
                    "type": "STRING",
                    "description": "The text to type into the field.",
                },
            },
            "required": ["selector", "value"],
        },
    },
    {
        "name": "get_page_text",
        "description": "Get the visible text content of the current page.",
        "parameters": {"type": "OBJECT", "properties": {}},
    },
    {
        "name": "get_page_html",
        "description": (
            "Get the HTML source of the current page to inspect its structure "
            "and find selectors."
        ),
        "parameters": {"type": "OBJECT", "properties": {}},
    },
    {
        "name": "screenshot",
        "description": "Take a screenshot of the current page.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "filename": {
                    "type": "STRING",
                    "description": "Filename for the screenshot (default: screenshot.png).",
                }
            },
        },
    },
    {
        "name": "get_current_url",
        "description": "Get the current page URL.",
        "parameters": {"type": "OBJECT", "properties": {}},
    },
    {
        "name": "press_key",
        "description": "Press a keyboard key (e.g. 'Enter', 'Tab').",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "key": {
                    "type": "STRING",
                    "description": "The key to press.",
                }
            },
            "required": ["key"],
        },
    },
    {
        "name": "wait",
        "description": "Wait for a specified duration in milliseconds.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "ms": {
                    "type": "NUMBER",
                    "description": "Milliseconds to wait (default: 2000).",
                }
            },
        },
    },
]


class BaseSkill(ABC):
    """Abstract base class for all worker skills.

    To add a new skill:
    1. Create a file in worker/skills/ (e.g. ``my_skill.py``).
    2. Subclass ``BaseSkill`` and implement all abstract members.
    3. The skill is auto-discovered by the registry — no manual registration needed.
    """

    # ------------------------------------------------------------------
    # Identity — every skill must declare these
    # ------------------------------------------------------------------

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique identifier used in API requests (e.g. ``"login_checker"``)."""

    @property
    @abstractmethod
    def description(self) -> str:
        """Short human-readable description shown in ``GET /api/skills``."""

    # ------------------------------------------------------------------
    # Agent configuration
    # ------------------------------------------------------------------

    @property
    @abstractmethod
    def system_instruction(self) -> str:
        """System prompt sent to Gemini that tells the AI what to do."""

    @property
    def done_tool_declaration(self) -> dict:
        """The ``done`` tool declaration specific to this skill.

        Override this to customise the parameters that the AI must return
        when it calls ``done()``.  The default provides a minimal
        pass/fail interface.
        """
        return {
            "name": "done",
            "description": "Call when the task is complete. Report results.",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "result": {
                        "type": "STRING",
                        "description": "'pass' or 'fail'.",
                    },
                    "reason": {
                        "type": "STRING",
                        "description": "Explanation of the result.",
                    },
                },
                "required": ["result", "reason"],
            },
        }

    @property
    def extra_tool_declarations(self) -> list[dict]:
        """Additional Gemini tool declarations beyond browser + done.

        Override if your skill needs custom tools (e.g. an API call tool).
        Default: empty list.
        """
        return []

    @property
    def max_turns(self) -> int:
        """Maximum agent loop iterations. Default 25."""
        return 25

    def get_all_tool_declarations(self) -> list[dict]:
        """Combine browser tools + skill-specific tools + done tool."""
        return BROWSER_TOOL_DECLARATIONS + self.extra_tool_declarations + [self.done_tool_declaration]

    # ------------------------------------------------------------------
    # Execution hooks
    # ------------------------------------------------------------------

    @abstractmethod
    def build_user_message(self, request: dict) -> str:
        """Build the initial user message sent to Gemini.

        ``request`` contains the fields from the API call (target_url,
        credentials, instructions, etc.).
        """

    @abstractmethod
    def parse_done(self, args: dict) -> dict:
        """Extract structured data from the ``done()`` call arguments.

        Must return a dict with at least ``{"success": bool, "summary": str}``.
        Add any extra keys your skill needs (the runner passes them through).
        """

    def on_tool_call(self, tool_name: str, tool_args: dict, tool_result: str) -> None:
        """Optional hook called after each tool execution.

        Use for timing, custom metrics, etc.  Default: no-op.
        """
