# CLAUDE.md

## Project Overview

**myAccount-QA-agent** — An AI-powered QA agent that uses Gemini API and Playwright to autonomously test website login flows.

## Repository Structure

```
myAccount-QA-agent/
├── main.py            # Entry point — runs the login test
├── agent.py           # Gemini AI agent with function-calling loop
├── browser.py         # Playwright browser session and tool definitions
├── config.py          # Environment config loader
├── requirements.txt   # Python dependencies
├── .env.example       # Template for environment variables
├── .gitignore         # Git ignore rules
├── CLAUDE.md          # This file
└── README.md          # Project README
```

## Getting Started

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Install Playwright browsers
playwright install chromium

# 3. Set up environment variables
cp .env.example .env
# Edit .env with your API key, target URL, and login credentials

# 4. Run the agent
python main.py
```

## Environment Variables

| Variable | Description |
|---|---|
| `GEMINI_API_KEY` | Your Google Gemini API key |
| `TARGET_URL` | Login page URL to test |
| `LOGIN_USERNAME` | Username/email for login |
| `LOGIN_PASSWORD` | Password for login |
| `HEADLESS` | Run browser headless (default: `true`) |

## How It Works

1. `main.py` loads config and invokes the agent
2. `agent.py` sends a prompt to Gemini with browser tools attached via function calling
3. Gemini autonomously decides which tools to call (navigate, inspect HTML, fill fields, click, screenshot)
4. `browser.py` executes each tool via Playwright and returns results to Gemini
5. Gemini loops until it determines login passed or failed, then returns a summary

## Key Conventions

- Python 3.10+
- Gemini API (free tier) with function calling for agent reasoning
- Playwright for browser automation
- Config via `.env` file (never commit secrets)
- Screenshots saved to `screenshots/` directory
