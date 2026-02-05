"""Gemini-powered QA agent that tests login flows using Playwright."""

import json
from google import genai
from google.genai import types
from browser import BrowserSession, execute_tool


# Define tools as Gemini function declarations
TOOLS = [
    types.Tool(
        function_declarations=[
            types.FunctionDeclaration(
                name="navigate",
                description="Navigate the browser to a URL.",
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "url": types.Schema(
                            type=types.Type.STRING,
                            description="The URL to navigate to.",
                        )
                    },
                    required=["url"],
                ),
            ),
            types.FunctionDeclaration(
                name="click",
                description="Click an element on the page by CSS selector.",
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "selector": types.Schema(
                            type=types.Type.STRING,
                            description="CSS selector of the element to click.",
                        )
                    },
                    required=["selector"],
                ),
            ),
            types.FunctionDeclaration(
                name="fill",
                description="Type text into a form field identified by CSS selector.",
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "selector": types.Schema(
                            type=types.Type.STRING,
                            description="CSS selector of the input field.",
                        ),
                        "value": types.Schema(
                            type=types.Type.STRING,
                            description="The text to type into the field.",
                        ),
                    },
                    required=["selector", "value"],
                ),
            ),
            types.FunctionDeclaration(
                name="get_page_text",
                description="Get the visible text content of the current page.",
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={},
                ),
            ),
            types.FunctionDeclaration(
                name="get_page_html",
                description="Get the HTML source of the current page to inspect its structure and find selectors.",
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={},
                ),
            ),
            types.FunctionDeclaration(
                name="screenshot",
                description="Take a screenshot of the current page.",
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "filename": types.Schema(
                            type=types.Type.STRING,
                            description="Filename for the screenshot (default: screenshot.png).",
                        )
                    },
                ),
            ),
            types.FunctionDeclaration(
                name="get_current_url",
                description="Get the current page URL.",
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={},
                ),
            ),
            types.FunctionDeclaration(
                name="press_key",
                description="Press a keyboard key (e.g. 'Enter', 'Tab').",
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "key": types.Schema(
                            type=types.Type.STRING,
                            description="The key to press.",
                        )
                    },
                    required=["key"],
                ),
            ),
            types.FunctionDeclaration(
                name="wait",
                description="Wait for a specified duration in milliseconds.",
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "ms": types.Schema(
                            type=types.Type.NUMBER,
                            description="Milliseconds to wait (default: 2000).",
                        )
                    },
                ),
            ),
        ]
    )
]

SYSTEM_INSTRUCTION = (
    "You are a QA testing agent. Your job is to test whether login works on a website.\n\n"
    "You have browser tools to navigate, inspect the page, fill forms, and click buttons.\n\n"
    "Instructions:\n"
    "1. Navigate to the target URL.\n"
    "2. Use get_page_html to inspect the page and find the login form fields and submit button.\n"
    "3. Fill in the username/email and password fields using the correct CSS selectors.\n"
    "4. Submit the form (click the submit button or press Enter).\n"
    "5. Wait briefly, then check the page text and URL to determine if login succeeded.\n"
    "6. Take a screenshot of the final state.\n\n"
    "When you are done, respond with a JSON block in this exact format:\n"
    '```json\n{"result": "pass" or "fail", "reason": "explanation"}\n```\n\n'
    "Be methodical. If a selector doesn't work, inspect the HTML again and try a different one."
)


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

    The Gemini agent autonomously navigates to the login page, inspects the HTML
    to find form fields, fills in credentials, submits, and determines whether
    login succeeded or failed.

    Returns a dict with keys: success (bool), summary (str), steps (list[str]).
    """
    client = genai.Client(api_key=api_key)
    session = BrowserSession(headless=headless)
    session.start()

    steps: list[str] = []

    user_message = (
        f"Test login on this website:\n"
        f"- URL: {target_url}\n"
        f"- Username/email: {username}\n"
        f"- Password: {password}\n\n"
        f"Go ahead and test it now."
    )

    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_INSTRUCTION,
        tools=TOOLS,
    )

    # Build conversation history
    contents: list[types.Content] = [
        types.Content(role="user", parts=[types.Part(text=user_message)])
    ]

    max_turns = 15
    final_summary = "Agent did not produce a result."

    try:
        for turn in range(max_turns):
            response = client.models.generate_content(
                model=model,
                contents=contents,
                config=config,
            )

            # Collect assistant parts
            assistant_parts = list(response.candidates[0].content.parts)
            contents.append(
                types.Content(role="model", parts=assistant_parts)
            )

            # Check for function calls
            function_calls = [p for p in assistant_parts if p.function_call]

            if not function_calls:
                # No more tool calls — extract final text
                text_parts = [p.text for p in assistant_parts if p.text]
                final_summary = "\n".join(text_parts)
                break

            # Execute each function call and collect responses
            response_parts = []
            for part in function_calls:
                fc = part.function_call
                tool_input = dict(fc.args) if fc.args else {}
                step_desc = f"[Turn {turn + 1}] {fc.name}({json.dumps(tool_input)})"
                print(f"  -> {step_desc}")
                steps.append(step_desc)

                try:
                    result = execute_tool(session, fc.name, tool_input)
                except Exception as e:
                    result = f"Error: {e}"

                response_parts.append(
                    types.Part(
                        function_response=types.FunctionResponse(
                            name=fc.name,
                            response={"result": result},
                        )
                    )
                )

            contents.append(types.Content(role="user", parts=response_parts))

    finally:
        session.stop()

    # Parse the result
    success = False
    if '"result": "pass"' in final_summary or '"result":"pass"' in final_summary:
        success = True

    return {
        "success": success,
        "summary": final_summary,
        "steps": steps,
    }
