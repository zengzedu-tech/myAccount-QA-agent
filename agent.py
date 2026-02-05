"""Claude-powered QA agent that tests login flows using Playwright."""

import json
import anthropic
from browser import BrowserSession, TOOL_DEFINITIONS, execute_tool


def run_login_test(
    target_url: str,
    username: str,
    password: str,
    api_key: str,
    headless: bool = True,
    model: str = "claude-sonnet-4-5-20250929",
) -> dict:
    """
    Run an AI-driven login test against the target URL.

    The Claude agent autonomously navigates to the login page, inspects the HTML
    to find form fields, fills in credentials, submits, and determines whether
    login succeeded or failed.

    Returns a dict with keys: success (bool), summary (str), steps (list[str]).
    """
    client = anthropic.Anthropic(api_key=api_key)
    session = BrowserSession(headless=headless)
    session.start()

    steps: list[str] = []

    system_prompt = (
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

    user_message = (
        f"Test login on this website:\n"
        f"- URL: {target_url}\n"
        f"- Username/email: {username}\n"
        f"- Password: {password}\n\n"
        f"Go ahead and test it now."
    )

    messages = [{"role": "user", "content": user_message}]

    max_turns = 15
    final_summary = "Agent did not produce a result."

    try:
        for turn in range(max_turns):
            response = client.messages.create(
                model=model,
                max_tokens=1024,
                system=system_prompt,
                tools=TOOL_DEFINITIONS,
                messages=messages,
            )

            # Collect assistant content
            assistant_content = response.content
            messages.append({"role": "assistant", "content": assistant_content})

            # Check if the agent is done (no more tool calls)
            tool_uses = [b for b in assistant_content if b.type == "tool_use"]

            if not tool_uses:
                # Extract final text response
                text_blocks = [b.text for b in assistant_content if b.type == "text"]
                final_text = "\n".join(text_blocks)
                final_summary = final_text
                break

            # Execute each tool call and collect results
            tool_results = []
            for tool_use in tool_uses:
                step_desc = f"[Turn {turn + 1}] {tool_use.name}({json.dumps(tool_use.input)})"
                print(f"  -> {step_desc}")
                steps.append(step_desc)

                try:
                    result = execute_tool(session, tool_use.name, tool_use.input)
                except Exception as e:
                    result = f"Error: {e}"

                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_use.id,
                        "content": result,
                    }
                )

            messages.append({"role": "user", "content": tool_results})

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
