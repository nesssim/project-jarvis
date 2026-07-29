from __future__ import annotations

import argparse
import sys

import httpx

ORCHESTRATOR_URL = "http://localhost:8000"


def main() -> None:
    parser = argparse.ArgumentParser(description="Chat with J.A.R.V.I.S.")
    parser.add_argument("message", nargs="?", help="Your message to J.A.R.V.I.S.")
    parser.add_argument(
        "--url",
        default=ORCHESTRATOR_URL,
        help=f"Orchestrator URL (default: {ORCHESTRATOR_URL})",
    )
    args = parser.parse_args()

    message = args.message or sys.stdin.read().strip()
    if not message:
        print("Usage: jarvis-chat <message>")  # noqa: T201
        sys.exit(1)

    url = f"{args.url.rstrip('/')}/chat"

    with httpx.Client(timeout=60) as client, client.stream("POST", url, json={"message": message}) as response:
        for raw_line in response.iter_lines():
            trimmed = raw_line.strip()
            if not trimmed.startswith("data: "):
                continue
            data = trimmed[6:]
            if data == "[DONE]":
                print()  # noqa: T201
                break
            print(data, end="", flush=True)  # noqa: T201


if __name__ == "__main__":
    main()
