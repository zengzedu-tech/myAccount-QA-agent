# CLAUDE.md

## Project Overview

**myAccount-QA-agent** — An AI-powered QA agent that uses Gemini API and Chrome DevTools Protocol to autonomously test website login flows, capture account information, and extract offers.

**Zero external dependencies** — uses only Python standard library + Chrome/Edge.

## Repository Structure

```
myAccount-QA-agent/
├── main.py            # Entry point — runs the login test
├── agent.py           # Gemini AI agent (direct REST API, no SDK)
├── browser.py         # Chrome DevTools Protocol browser session (no Playwright)
├── config.py          # Environment config loader (custom .env parser)
├── requirements.txt   # No external deps — stdlib only
├── .env.example       # Template for environment variables
├── .gitignore         # Git ignore rules
├── CLAUDE.md          # This file
└── README.md          # Project README
```

## Getting Started

```bash
# 1. Set up environment variables
copy .env.example .env    # Windows
# cp .env.example .env    # macOS/Linux

# Edit .env with your Gemini API key, target URL, and login credentials

# 2. Run the agent (no pip install needed)
py main.py       # Windows
# python main.py  # macOS/Linux
```

### Prerequisites

- **Python 3.10+**
- **Chrome or Edge** installed on the system

No `pip install` required — the project uses only Python standard library.

## Environment Variables

| Variable | Description |
|---|---|
| `GEMINI_API_KEY` | Your Google Gemini API key ([aistudio.google.com/apikey](https://aistudio.google.com/apikey)) |
| `TARGET_URL` | Login page URL to test |
| `LOGIN_USERNAME` | Username/email for login |
| `LOGIN_PASSWORD` | Password for login |
| `HEADLESS` | Run browser headless (default: `true`) |

## How It Works

1. `main.py` loads config and invokes the agent
2. `agent.py` sends a prompt to Gemini REST API with browser tools via function calling
3. Gemini autonomously decides which tools to call (navigate, inspect HTML, fill fields, click, screenshot)
4. `browser.py` executes each tool via Chrome DevTools Protocol and returns results to Gemini
5. The agent runs through 4 phases:
   - **Phase 1 — Login**: Navigate, fill credentials, submit, verify URL changed
   - **Phase 2 — Account Info**: Read account overview, take screenshot
   - **Phase 3 — Offers**: Navigate to offers page, read offers, take screenshot
   - **Phase 4 — Report**: Call `done()` with all captured data

## Architecture

- **Browser**: Custom Chrome DevTools Protocol (CDP) client over WebSocket (stdlib `socket`)
- **AI**: Direct Gemini REST API calls via `urllib` (no SDK)
- **Config**: Custom `.env` parser (no `python-dotenv`)
- **Stealth**: Anti-bot-detection flags (disabled AutomationControlled, custom user agent)

## Key Conventions

- Python 3.10+, zero external dependencies
- Gemini API (free tier) with function calling for agent reasoning
- Chrome DevTools Protocol for browser automation
- Config via `.env` file (never commit secrets)
- Screenshots saved to `screenshots/` directory
