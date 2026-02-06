"""Configuration loader — reads .env file using only stdlib (no python-dotenv)."""

import os


def _load_dotenv(path=None):
    """Load variables from a .env file into os.environ."""
    if path is None:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            # Strip surrounding quotes
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                value = value[1:-1]
            os.environ.setdefault(key, value)


_load_dotenv()


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
