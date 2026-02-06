"""Gemini-powered QA agent — calls Gemini REST API directly via urllib (no SDK)."""

import json
import time
import urllib.request
from browser import BrowserSession, execute_tool

GEMINI_API_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)

# Tool declarations in Gemini REST API format
TOOL_DECLARATIONS = [
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
    {
        "name": "done",
        "description": (
            "Call this when you have completed ALL tasks (login test, account info, and offers). "
            "Report the full results."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "result": {
                    "type": "STRING",
                    "description": "'pass' if login succeeded, 'fail' if it did not.",
                },
                "reason": {
                    "type": "STRING",
                    "description": "Explanation of why login passed or failed.",
                },
                "account_info": {
                    "type": "STRING",
                    "description": "Description of the basic account information shown on the main page after login (account holder name, accounts listed, balances, payment info, etc.).",
                },
                "offers": {
                    "type": "STRING",
                    "description": "List of offers shown on the offers page. Describe each offer.",
                },
            },
            "required": ["result", "reason", "account_info", "offers"],
        },
    },
]

SYSTEM_INSTRUCTION = (
    "You are a QA testing agent controlling a real browser. "
    "You MUST use the provided tools to interact with the browser. "
    "Do NOT guess or assume results — you must actually perform each action.\n\n"
    "Instructions:\n"
    "PHASE 1 — LOGIN:\n"
    "1. Call navigate to go to the target URL.\n"
    "2. Call get_page_html to inspect the page and find the login form fields and submit button.\n"
    "3. Call fill to enter the username/email and password using the correct CSS selectors.\n"
    "4. Call click on the submit button (or call press_key with 'Enter').\n"
    "5. Call wait with 5000ms for the page to fully load after login.\n"
    "6. Call get_current_url to verify the URL changed away from the login page.\n\n"
    "PHASE 2 — ACCOUNT INFO:\n"
    "7. Call get_page_text to read the main account overview page.\n"
    "8. Call screenshot with filename 'account_overview.png'.\n"
    "9. Carefully note ALL account information: account holder name, vehicle(s), "
    "account numbers, balances, payment amounts, due dates, and any other details shown.\n\n"
    "PHASE 3 — OFFERS PAGE:\n"
    "10. Call get_page_html to find the navigation link/button for the Offers page.\n"
    "11. Call click on the Offers link to navigate to the offers page.\n"
    "12. Call wait with 3000ms for the offers page to load.\n"
    "13. Call get_page_text to read all offers on the page.\n"
    "14. Call screenshot with filename 'offers_page.png'.\n\n"
    "PHASE 4 — REPORT:\n"
    "15. Call done with the result, account_info (detailed description of what you saw "
    "on the account overview), and offers (list every offer shown on the offers page).\n\n"
    "Be methodical. If a selector doesn't work, call get_page_html again and try a different one.\n"
    "IMPORTANT: Start by calling the navigate tool. Do not skip any steps. "
    "You MUST complete all 4 phases before calling done."
)


def _call_gemini(
    api_key: str,
    model: str,
    contents: list,
    tool_mode: str = "ANY",
) -> dict:
    """Make a direct REST call to the Gemini generateContent endpoint."""
    url = GEMINI_API_URL.format(model=model) + f"?key={api_key}"
    body = {
        "systemInstruction": {"parts": [{"text": SYSTEM_INSTRUCTION}]},
        "contents": contents,
        "tools": [{"functionDeclarations": TOOL_DECLARATIONS}],
        "toolConfig": {"functionCallingConfig": {"mode": tool_mode}},
    }
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


def run_login_test(
    target_url: str,
    username: str,
    password: str,
    api_key: str,
    headless: bool = True,
    model: str = "gemini-2.0-flash",
) -> dict:
    """
    Run an AI-driven login test against the target URL.

    Returns a dict with keys: success (bool), summary (str), steps (list[str]).
    """
    session = BrowserSession(headless=headless)
    session.start()

    steps: list[str] = []

    user_message = (
        f"Test login on this website:\n"
        f"- URL: {target_url}\n"
        f"- Username/email: {username}\n"
        f"- Password: {password}\n\n"
        f"Start by calling the navigate tool with the URL above."
    )

    # Conversation history in Gemini REST format
    contents = [{"role": "user", "parts": [{"text": user_message}]}]

    max_turns = 25
    final_summary = "Agent did not produce a result."
    done_called = False
    account_info = ""
    offers = ""

    # Timing: track from login button click to main page loaded
    login_click_time = None
    login_load_time = None
    login_duration = None

    try:
        for turn in range(max_turns):
            tool_mode = "AUTO" if done_called else "ANY"
            response = _call_gemini(api_key, model, contents, tool_mode)

            # Extract assistant parts
            candidate = response.get("candidates", [{}])[0]
            model_content = candidate.get("content", {})
            model_parts = model_content.get("parts", [])

            # Add model response to history
            contents.append({"role": "model", "parts": model_parts})

            # Debug logging
            for p in model_parts:
                if "text" in p:
                    print(f"  [model text] {p['text'][:200]}")
                if "functionCall" in p:
                    print(f"  [model tool] {p['functionCall']['name']}")

            # Collect function calls
            function_calls = [p for p in model_parts if "functionCall" in p]

            if not function_calls:
                text_parts = [p["text"] for p in model_parts if "text" in p]
                final_summary = "\n".join(text_parts) if text_parts else final_summary
                break

            # Execute each function call
            response_parts = []
            for part in function_calls:
                fc = part["functionCall"]
                name = fc["name"]
                args = fc.get("args", {})
                step_desc = f"[Turn {turn + 1}] {name}({json.dumps(args)})"
                print(f"  -> {step_desc}")
                steps.append(step_desc)

                # Start timer right before clicking the login button
                if name == "click" and login_click_time is None:
                    login_click_time = time.time()
                    print(f"  [timer] Login click — timer started")

                if name == "done":
                    done_called = True
                    result_val = args.get("result", "fail")
                    reason = args.get("reason", "No reason given.")
                    account_info = args.get("account_info", "")
                    offers = args.get("offers", "")
                    final_summary = json.dumps(
                        {"result": result_val, "reason": reason}
                    )
                    result = "Test complete."
                else:
                    try:
                        result = execute_tool(session, name, args)
                    except Exception as e:
                        result = f"Error: {e}"

                # Stop timer when we detect URL changed away from login page
                if (
                    name == "get_current_url"
                    and login_click_time is not None
                    and login_load_time is None
                    and "login" not in result.lower()
                ):
                    login_load_time = time.time()
                    login_duration = login_load_time - login_click_time
                    print(f"  [timer] Main page loaded — {login_duration:.2f}s")

                print(f"  <- {result[:200]}")

                response_parts.append(
                    {
                        "functionResponse": {
                            "name": name,
                            "response": {"result": result},
                        }
                    }
                )

            if done_called:
                break

            contents.append({"role": "user", "parts": response_parts})

    finally:
        session.stop()

    success = (
        '"result": "pass"' in final_summary
        or '"result":"pass"' in final_summary
    )

    return {
        "success": success,
        "summary": final_summary,
        "steps": steps,
        "login_duration": login_duration,
        "account_info": account_info,
        "offers": offers,
    }
