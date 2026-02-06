"""Login Checker skill — tests login flow and records basic account info."""

from __future__ import annotations

import time
from skills.base import BaseSkill


class LoginCheckerSkill(BaseSkill):

    name = "login_checker"
    description = "Test website login flow and record basic account information."

    # -- Agent configuration ------------------------------------------------

    system_instruction = (
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

    @property
    def done_tool_declaration(self) -> dict:
        return {
            "name": "done",
            "description": (
                "Call this when you have completed ALL tasks "
                "(login test, account info, and offers). Report the full results."
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
                        "description": (
                            "Description of the basic account information shown on the "
                            "main page after login (account holder name, accounts listed, "
                            "balances, payment info, etc.)."
                        ),
                    },
                    "offers": {
                        "type": "STRING",
                        "description": "List of offers shown on the offers page. Describe each offer.",
                    },
                },
                "required": ["result", "reason", "account_info", "offers"],
            },
        }

    # -- Execution hooks ----------------------------------------------------

    def __init__(self):
        self._login_click_time: float | None = None
        self._login_load_time: float | None = None
        self.login_duration: float | None = None

    def build_user_message(self, request: dict) -> str:
        target_url = request["target_url"]
        username = request.get("credentials", {}).get("username", "")
        password = request.get("credentials", {}).get("password", "")
        return (
            f"Test login on this website:\n"
            f"- URL: {target_url}\n"
            f"- Username/email: {username}\n"
            f"- Password: {password}\n\n"
            f"Start by calling the navigate tool with the URL above."
        )

    def parse_done(self, args: dict) -> dict:
        result_val = args.get("result", "fail")
        return {
            "success": result_val == "pass",
            "summary": f'{{"result": "{result_val}", "reason": "{args.get("reason", "")}"}}',
            "account_info": args.get("account_info", ""),
            "offers": args.get("offers", ""),
            "login_duration": self.login_duration,
        }

    def on_tool_call(self, tool_name: str, tool_args: dict, tool_result: str) -> None:
        # Track login timing: start on first click, stop when URL leaves login page
        if tool_name == "click" and self._login_click_time is None:
            self._login_click_time = time.time()
            print("  [timer] Login click — timer started")

        if (
            tool_name == "get_current_url"
            and self._login_click_time is not None
            and self._login_load_time is None
            and "login" not in tool_result.lower()
        ):
            self._login_load_time = time.time()
            self.login_duration = self._login_load_time - self._login_click_time
            print(f"  [timer] Main page loaded — {self.login_duration:.2f}s")
