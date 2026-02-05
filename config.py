"""Configuration loader — reads from .env file or environment variables."""

import os
from dotenv import load_dotenv

load_dotenv()


def get_config() -> dict:
    """Load and validate configuration from environment."""
    config = {
        "api_key": os.getenv("GEMINI_API_KEY", ""),
        "target_url": os.getenv("TARGET_URL", ""),
        "username": os.getenv("LOGIN_USERNAME", ""),
        "password": os.getenv("LOGIN_PASSWORD", ""),
        "headless": os.getenv("HEADLESS", "true").lower() == "true",
    }

    missing = []
    if not config["api_key"]:
        missing.append("GEMINI_API_KEY")
    if not config["target_url"]:
        missing.append("TARGET_URL")
    if not config["username"]:
        missing.append("LOGIN_USERNAME")
    if not config["password"]:
        missing.append("LOGIN_PASSWORD")

    if missing:
        raise ValueError(
            f"Missing required environment variables: {', '.join(missing)}\n"
            f"Copy .env.example to .env and fill in the values."
        )

    return config
