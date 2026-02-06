"""Entry point for the QA agent — runs login test and prints results."""

import sys
from config import get_config
from agent import run_login_test


def main():
    print("=" * 60)
    print("  myAccount QA Agent — Login Test")
    print("=" * 60)

    try:
        config = get_config()
    except ValueError as e:
        print(f"\nConfiguration error:\n{e}")
        sys.exit(1)

    print(f"\nTarget: {config['target_url']}")
    print(f"User:   {config['username']}")
    print(f"Mode:   {'headless' if config['headless'] else 'headed'}")
    print("-" * 60)
    print("Running login test...\n")

    result = run_login_test(
        target_url=config["target_url"],
        username=config["username"],
        password=config["password"],
        api_key=config["api_key"],
        headless=config["headless"],
    )

    print("\n" + "=" * 60)
    print("RESULT:", "PASS" if result["success"] else "FAIL")
    print("=" * 60)

    if result.get("login_duration") is not None:
        print(f"\nLogin load time: {result['login_duration']:.2f}s")
    else:
        print("\nLogin load time: could not be measured")

    print("\n" + "-" * 60)
    print("ACCOUNT INFORMATION:")
    print("-" * 60)
    print(result.get("account_info") or "(none captured)")

    print("\n" + "-" * 60)
    print("OFFERS:")
    print("-" * 60)
    print(result.get("offers") or "(none captured)")

    print("\n" + "-" * 60)
    print("Agent summary:")
    print(result["summary"])

    if result["steps"]:
        print(f"\nSteps taken ({len(result['steps'])}):")
        for step in result["steps"]:
            print(f"  {step}")

    sys.exit(0 if result["success"] else 1)


if __name__ == "__main__":
    main()
