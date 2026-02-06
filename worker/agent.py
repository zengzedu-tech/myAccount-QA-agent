"""Generic skill runner — executes any BaseSkill via Gemini + CDP browser.

The runner is skill-agnostic: it takes a BaseSkill instance, wires up its
tool declarations and system instruction, runs the Gemini function-calling
loop, and returns the structured result produced by the skill's parse_done().
"""

from __future__ import annotations

import json
import time
import urllib.request

from browser import BrowserSession, execute_tool
from skills.base import BaseSkill

GEMINI_API_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)


def _call_gemini(
    api_key: str,
    model: str,
    system_instruction: str,
    tool_declarations: list[dict],
    contents: list,
    tool_mode: str = "ANY",
) -> dict:
    """Make a direct REST call to the Gemini generateContent endpoint."""
    url = GEMINI_API_URL.format(model=model) + f"?key={api_key}"
    body = {
        "systemInstruction": {"parts": [{"text": system_instruction}]},
        "contents": contents,
        "tools": [{"functionDeclarations": tool_declarations}],
        "toolConfig": {"functionCallingConfig": {"mode": tool_mode}},
    }
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


def run_skill(
    skill: BaseSkill,
    request: dict,
    api_key: str,
    headless: bool = True,
    model: str = "gemini-2.0-flash",
    screenshot_dir: str = "screenshots",
) -> dict:
    """Run a skill against a target URL via an AI-driven browser session.

    Parameters
    ----------
    skill : BaseSkill
        The skill instance that defines tools, prompts, and result parsing.
    request : dict
        Must contain at least ``target_url`` and ``credentials``.
        Passed to ``skill.build_user_message()``.
    api_key : str
        Gemini API key.
    headless : bool
        Run Chrome in headless mode.
    model : str
        Gemini model name.
    screenshot_dir : str
        Directory to save screenshots into.

    Returns
    -------
    dict
        Always contains ``success``, ``summary``, ``steps``.
        Additional keys depend on the skill's ``parse_done()`` output.
    """
    session = BrowserSession(headless=headless, screenshot_dir=screenshot_dir)
    session.start()

    steps: list[str] = []
    user_message = skill.build_user_message(request)
    contents = [{"role": "user", "parts": [{"text": user_message}]}]

    tool_declarations = skill.get_all_tool_declarations()
    system_instruction = skill.system_instruction

    final_summary = "Agent did not produce a result."
    done_result: dict | None = None

    try:
        for turn in range(skill.max_turns):
            tool_mode = "AUTO" if done_result is not None else "ANY"
            response = _call_gemini(
                api_key, model, system_instruction,
                tool_declarations, contents, tool_mode,
            )

            candidate = response.get("candidates", [{}])[0]
            model_content = candidate.get("content", {})
            model_parts = model_content.get("parts", [])

            contents.append({"role": "model", "parts": model_parts})

            for p in model_parts:
                if "text" in p:
                    print(f"  [model text] {p['text'][:200]}")
                if "functionCall" in p:
                    print(f"  [model tool] {p['functionCall']['name']}")

            function_calls = [p for p in model_parts if "functionCall" in p]

            if not function_calls:
                text_parts = [p["text"] for p in model_parts if "text" in p]
                final_summary = "\n".join(text_parts) if text_parts else final_summary
                break

            response_parts = []
            for part in function_calls:
                fc = part["functionCall"]
                name = fc["name"]
                args = fc.get("args", {})
                step_desc = f"[Turn {turn + 1}] {name}({json.dumps(args)})"
                print(f"  -> {step_desc}")
                steps.append(step_desc)

                if name == "done":
                    done_result = skill.parse_done(args)
                    result = "Test complete."
                else:
                    try:
                        result = execute_tool(session, name, args)
                    except Exception as e:
                        result = f"Error: {e}"

                # Let the skill observe every tool call (for timing, metrics, etc.)
                skill.on_tool_call(name, args, result)

                print(f"  <- {result[:200]}")

                response_parts.append(
                    {
                        "functionResponse": {
                            "name": name,
                            "response": {"result": result},
                        }
                    }
                )

            if done_result is not None:
                break

            contents.append({"role": "user", "parts": response_parts})

    finally:
        session.stop()

    # Build the final output — merge skill-specific fields with standard ones
    if done_result is not None:
        output = {**done_result, "steps": steps}
    else:
        output = {
            "success": False,
            "summary": final_summary,
            "steps": steps,
        }
    return output
