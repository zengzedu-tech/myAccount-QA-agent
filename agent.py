"""Gemini-powered QA agent that tests login flows using Playwright."""

import json
import google.generativeai as genai
from browser import BrowserSession, execute_tool


# Define tools as Gemini function declarations
GEMINI_TOOLS = [
    genai.protos.Tool(
        function_declarations=[
            genai.protos.FunctionDeclaration(
                name="navigate",
                description="Navigate the browser to a URL.",
                parameters=genai.protos.Schema(
                    type=genai.protos.Type.OBJECT,
                    properties={
                        "url": genai.protos.Schema(
                            type=genai.protos.Type.STRING,
                            description="The URL to navigate to.",
                        )
                    },
                    required=["url"],
                ),
            ),
            genai.protos.FunctionDeclaration(
                name="click",
                description="Click an element on the page by CSS selector.",
                parameters=genai.protos.Schema(
                    type=genai.protos.Type.OBJECT,
                    properties={
                        "selector": genai.protos.Schema(
                            type=genai.protos.Type.STRING,
                            description="CSS selector of the element to click.",
                        )
                    },
                    required=["selector"],
                ),
            ),
            genai.protos.FunctionDeclaration(
                name="fill",
                description="Type text into a form field identified by CSS selector.",
                parameters=genai.protos.Schema(
                    type=genai.protos.Type.OBJECT,
                    properties={
                        "selector": genai.protos.Schema(
                            type=genai.protos.Type.STRING,
                            description="CSS selector of the input field.",
                        ),
                        "value": genai.protos.Schema(
                            type=genai.protos.Type.STRING,
                            description="The text to type into the field.",
                        ),
                    },
                    required=["selector", "value"],
                ),
            ),
            genai.protos.FunctionDeclaration(
                name="get_page_text",
                description="Get the visible text content of the current page.",
                parameters=genai.protos.Schema(
                    type=genai.protos.Type.OBJECT,
                    properties={},
                ),
            ),
            genai.protos.FunctionDeclaration(
                name="get_page_html",
                description="Get the HTML source of the current page to inspect its structure and find selectors.",
                parameters=genai.protos.Schema(
                    type=genai.protos.Type.OBJECT,
                    properties={},
                ),
            ),
            genai.protos.FunctionDeclaration(
                name="screenshot",
                description="Take a screenshot of the current page.",
                parameters=genai.protos.Schema(
                    type=genai.protos.Type.OBJECT,
                    properties={
                        "filename": genai.protos.Schema(
                            type=genai.protos.Type.STRING,
                            description="Filename for the screenshot (default: screenshot.png).",
                        )
                    },
                ),
            ),
            genai.protos.FunctionDeclaration(
                name="get_current_url",
                description="Get the current page URL.",
                parameters=genai.protos.Schema(
                    type=genai.protos.Type.OBJECT,
                    properties={},
                ),
            ),
            genai.protos.FunctionDeclaration(
                name="press_key",
                description="Press a keyboard key (e.g. 'Enter', 'Tab').",
                parameters=genai.protos.Schema(
                    type=genai.protos.Type.OBJECT,
                    properties={
                        "key": genai.protos.Schema(
                            type=genai.protos.Type.STRING,
                            description="The key to press.",
                        )
                    },
                    required=["key"],
                ),
            ),
            genai.protos.FunctionDeclaration(
                name="wait",
                description="Wait for a specified duration in milliseconds.",
                parameters=genai.protos.Schema(
                    type=genai.protos.Type.OBJECT,
                    properties={
                        "ms": genai.protos.Schema(
                            type=genai.protos.Type.NUMBER,
                            description="Milliseconds to wait (default: 2000).",
                        )
                    },
                ),
            ),
        ]
    )
]


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
    genai.configure(api_key=api_key)

    model_instance = genai.GenerativeModel(
        model_name=model,
        tools=GEMINI_TOOLS,
        system_instruction=(
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
        ),
    )

    chat = model_instance.start_chat()
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

    max_turns = 15
    final_summary = "Agent did not produce a result."

    try:
        response = chat.send_message(user_message)

        for turn in range(max_turns):
            # Check for function calls
            function_calls = []
            for part in response.parts:
                if part.function_call.name:
                    function_calls.append(part.function_call)

            if not function_calls:
                # No more tool calls — extract final text
                final_summary = response.text
                break

            # Execute each function call and collect responses
            function_responses = []
            for fc in function_calls:
                tool_input = dict(fc.args) if fc.args else {}
                step_desc = f"[Turn {turn + 1}] {fc.name}({json.dumps(tool_input)})"
                print(f"  -> {step_desc}")
                steps.append(step_desc)

                try:
                    result = execute_tool(session, fc.name, tool_input)
                except Exception as e:
                    result = f"Error: {e}"

                function_responses.append(
                    genai.protos.Part(
                        function_response=genai.protos.FunctionResponse(
                            name=fc.name,
                            response={"result": result},
                        )
                    )
                )

            # Send function results back to Gemini
            response = chat.send_message(function_responses)

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
