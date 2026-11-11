"""Ask the help desk from the command line.

  python cli.py "When is the group coaching session?"
  python cli.py --mock "What is your refund policy?"
  python cli.py --simulate-failure "When is the group coaching session?"
Exit code: 0 on an answer (including "not in the documents"), 1 on an error.
"""
import argparse
import json
import sys

import helpdesk


def print_result(status, payload):
    if payload["mock"]:
        print("[MOCK MODE - this answer comes from a keyword matcher, not a real language model]")
    if status != 200:
        simulated = " (simulated failure)" if payload["simulated_failure"] else ""
        print(f"Error{simulated}: {payload['message']}")
        return
    print("Answer:", payload["answer"])
    if payload["answer_replaced"]:
        print("(Shown as direct quotes: the model's own wording included a detail the documents do not back up.)")
    for source in payload["sources"]:
        print(f"Source: {source['title']} ({source['file']})")
        print(f'  "{source["quote"]}"')
    print(f"Model: {payload['model']}")


def main():
    parser = argparse.ArgumentParser(description="Ask the BrightPath help desk a question")
    parser.add_argument("question", nargs="+", help="the question to ask")
    parser.add_argument("--mock", action="store_true", help="use the labelled mock model instead of a real one")
    parser.add_argument("--simulate-failure", action="store_true", help="send the request to an unreachable address")
    parser.add_argument("--json", action="store_true", help="print the raw JSON result")
    args = parser.parse_args()

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # titles contain dashes; never crash on them
    helpdesk.load_env_file()
    settings = helpdesk.get_settings(mock=args.mock)
    status, payload = helpdesk.handle_question(" ".join(args.question), settings, args.simulate_failure)
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print_result(status, payload)
    return 0 if status == 200 else 1


if __name__ == "__main__":
    sys.exit(main())
