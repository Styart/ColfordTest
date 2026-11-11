"""Run the three required test cases and save the results to results/.

  python run_tests.py          # uses the model configured in .env / environment
  python run_tests.py --mock   # uses the clearly labelled mock model
Writes results/test_results.json and results/test_results.md. Exit code 1 if any check fails.
"""
import argparse
import json
import sys
from datetime import datetime, timezone

import helpdesk

RESULTS_DIR = helpdesk.ROOT / "results"

# (name, question, simulate_failure, expected outcome)
CASES = [
    ("Supported question", "When is the group coaching session?", False, "answer"),
    ("Unsupported question", "What is your refund policy?", False, "not_found"),
    ("API failure", "When is the group coaching session?", True, "error"),
]
EXPECTED_TEXT = {"answer": "an answer with at least one document source",
                 "not_found": "the fixed 'not available' message and no sources",
                 "error": "a clear error message and a non-200 status"}


def check(expected, status, payload):
    if expected == "error":
        return status != 200 and bool(payload.get("message"))
    if status != 200:
        return False
    if expected == "answer":
        return payload["answered"] and len(payload["sources"]) > 0
    return not payload["answered"] and payload["answer"] == helpdesk.NOT_FOUND_ANSWER


def to_markdown(report):
    lines = ["# Help desk test results", ""]
    if report["mock"]:
        lines += ["> **MOCK MODE** - these results come from the keyword-matching mock, "
                  "not a real language model.", ""]
    lines += [f"- Run at: {report['run_at']}", f"- Model: {report['model']}",
              f"- Passed: {report['passed']} of {len(report['cases'])}", ""]
    for number, case in enumerate(report["cases"], start=1):
        result = case["result"]
        lines += [f"## {number}. {case['name']} - {'PASS' if case['passed'] else 'FAIL'}", "",
                  f"- Question: {case['question']}",
                  f"- Simulated failure: {'yes' if case['simulate_failure'] else 'no'}",
                  f"- Expected: {case['expected']}",
                  f"- HTTP status: {case['status']}"]
        if "error" in result:
            lines += [f"- Error: `{result['error']}` - {result['message']}"]
        else:
            lines += [f"- Answered from documents: {'yes' if result['answered'] else 'no'}",
                      f"- Answer: {result['answer']}"]
            for source in result["sources"]:
                lines += [f"- Source: {source['title']} (`{source['file']}`): \"{source['quote']}\""]
        lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Run the three required help desk test cases")
    parser.add_argument("--mock", action="store_true", help="use the labelled mock model instead of a real one")
    args = parser.parse_args()

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    helpdesk.load_env_file()
    settings = helpdesk.get_settings(mock=args.mock)
    cases = []
    for name, question, simulate_failure, expected in CASES:
        status, payload = helpdesk.handle_question(question, settings, simulate_failure)
        passed = check(expected, status, payload)
        cases.append({"name": name, "question": question, "simulate_failure": simulate_failure,
                      "expected": EXPECTED_TEXT[expected], "status": status, "passed": passed, "result": payload})
        print(f"{'PASS' if passed else 'FAIL'}  {name}: HTTP {status}")

    report = {"run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "model": helpdesk.model_label(settings), "mock": settings["provider"] == "mock",
              "passed": sum(case["passed"] for case in cases), "cases": cases}
    RESULTS_DIR.mkdir(exist_ok=True)
    (RESULTS_DIR / "test_results.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    (RESULTS_DIR / "test_results.md").write_text(to_markdown(report), encoding="utf-8")
    print(f"Model: {report['model']}\nSaved results/test_results.md and results/test_results.json")
    return 0 if report["passed"] == len(cases) else 1


if __name__ == "__main__":
    sys.exit(main())
