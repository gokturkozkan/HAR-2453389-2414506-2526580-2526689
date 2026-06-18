import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RESET = "\033[0m"
GREEN = "\033[32m"
CYAN = "\033[36m"
BOLD = "\033[1m"
DIM = "\033[2m"


def colorize(output):
    replacements = {
        " PASSED ": f" {GREEN}PASSED{RESET} ",
        " PASSED [": f" {GREEN}PASSED{RESET} [",
        " passed": f" {GREEN}passed{RESET}",
        "Actual status: 401": f"{GREEN}Actual status: 401{RESET}",
        "Status: 401": f"{GREEN}Status: 401{RESET}",
        "success=50/50": f"{GREEN}success=50/50{RESET}",
        "success=15/15": f"{GREEN}success=15/15{RESET}",
    }

    for plain, colored in replacements.items():
        output = output.replace(plain, colored)

    return output


def clean_output(output):
    lines = []

    for line in output.splitlines():
        if "test session starts" in line:
            continue

        lines.append(line)

    return colorize("\n".join(lines).strip())


def run_command(command, env=None):
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
    )

    stdout = clean_output(completed.stdout)
    stderr = clean_output(completed.stderr)

    if stdout:
        print(stdout)

    if stderr:
        if stdout:
            print()
        print(stderr)

    return completed.returncode


def print_header(item):
    print(f"{BOLD}{CYAN}{item['id']} - {item['title']}{RESET}")
    print(f"{DIM}{'-' * 72}{RESET}")
    sys.stdout.flush()


def run_pytest(item):
    print_header(item)
    command = [
        sys.executable,
        "-m",
        "pytest",
        "--color=yes",
        "--disable-warnings",
        *item["args"],
    ]
    return run_command(command)


def show_json(item):
    print_header(item)
    path = ROOT / item["path"]
    print()
    if not path.exists():
        print(f"Missing file: {path}")
        return 1

    with path.open("r", encoding="utf-8") as file:
        payload = json.load(file)

    print(json.dumps(payload, indent=2))
    return 0


def run_performance(item):
    print_header(item)
    command = [sys.executable, "test_results/performance_benchmark.py"]
    return run_command(command)


def run_admin_unauthorized(item):
    print_header(item)
    env = os.environ.copy()
    env["ADMIN_TOKEN"] = "test-token"

    return run_command(
        [sys.executable, "test_results/admin_unauthorized_check.py"],
        env=env,
    )


ITEMS = {
    "UT-1": {
        "id": "UT-1",
        "section": "Unit Testing",
        "title": "unit-only pytest result",
        "purpose": "Runs all unit-level backend, activity label, and TDMA transport tests.",
        "expected": "17 passed",
        "runner": run_pytest,
        "args": [
            "tests/test_activity_label_flow.py",
            "tests/test_backend_unit.py",
            "tests/test_transport_unit.py",
            "-v",
        ],
    },
    "UT-2": {
        "id": "UT-2",
        "section": "Unit Testing",
        "title": "activity label flow unit tests",
        "purpose": "Shows activity prediction, label retrieval, invalid payload, logging, and relabel unit checks.",
        "expected": "Activity label flow tests listed as PASSED",
        "runner": run_pytest,
        "args": ["tests/test_activity_label_flow.py", "-v"],
    },
    "UT-3": {
        "id": "UT-3",
        "section": "Unit Testing",
        "title": "backend route unit tests",
        "purpose": "Shows auth, user update, ESP status, admin-token, and calibration route unit checks.",
        "expected": "Backend unit tests listed as PASSED",
        "runner": run_pytest,
        "args": ["tests/test_backend_unit.py", "-v"],
    },
    "UT-4": {
        "id": "UT-4",
        "section": "Unit Testing",
        "title": "TDMA transport unit tests",
        "purpose": "Shows frame parsing, node order, axis transform, payload, and reconnect backoff unit checks.",
        "expected": "TDMA transport tests listed as PASSED",
        "runner": run_pytest,
        "args": ["tests/test_transport_unit.py", "-v"],
    },
    "IT-1": {
        "id": "IT-1",
        "section": "Integration Testing",
        "title": "integration flow pytest result",
        "purpose": "Runs TDMA payload to backend prediction, relabel persistence, calibration, and mobile auth integration flows.",
        "expected": "4 passed",
        "runner": run_pytest,
        "args": ["tests/test_integration_flow.py", "-v"],
    },
    "IT-2": {
        "id": "IT-2",
        "section": "Integration Testing",
        "title": "full suite regression result",
        "purpose": "Runs the complete automated suite to prove integration changes did not break other test groups.",
        "expected": "27 passed",
        "runner": run_pytest,
        "args": ["tests", "-v"],
    },
    "IT-3": {
        "id": "IT-3",
        "section": "Integration Testing",
        "title": "integration flow detailed test names",
        "purpose": "Shows the individual integration test cases and their PASSED status.",
        "expected": "Integration test names listed as PASSED",
        "runner": run_pytest,
        "args": ["tests/test_integration_flow.py", "-v"],
    },
    "ST-1": {
        "id": "ST-1",
        "section": "System Testing",
        "title": "system flow pytest result",
        "purpose": "Runs end-to-end backend system flows from health/auth/prediction/relabel and calibrated prediction.",
        "expected": "2 passed",
        "runner": run_pytest,
        "args": ["tests/test_system_flow.py", "-v"],
    },
    "ST-2": {
        "id": "ST-2",
        "section": "System Testing",
        "title": "full suite regression result",
        "purpose": "Runs the complete suite to show system-level changes pass with all other groups.",
        "expected": "27 passed",
        "runner": run_pytest,
        "args": ["tests", "-v"],
    },
    "ST-3": {
        "id": "ST-3",
        "section": "System Testing",
        "title": "system flow detailed test names",
        "purpose": "Shows complete system flow and calibrated system flow test cases as PASSED.",
        "expected": "System test names listed as PASSED",
        "runner": run_pytest,
        "args": ["tests/test_system_flow.py", "-v"],
    },
    "PT-1": {
        "id": "PT-1",
        "section": "Performance Testing",
        "title": "performance benchmark terminal result",
        "purpose": "Measures endpoint latency and process CPU/RAM for backend operations.",
        "expected": "Latency rows printed and performance_results.json written",
        "runner": run_performance,
    },
    "PT-2": {
        "id": "PT-2",
        "section": "Performance Testing",
        "title": "performance_results.json evidence",
        "purpose": "Prints raw benchmark JSON produced by performance_benchmark.py.",
        "expected": "JSON contains benchmark rows and resource_usage",
        "runner": show_json,
        "path": "test_results/performance_results.json",
    },
    "RT-1": {
        "id": "RT-1",
        "section": "Recovery Testing",
        "title": "recovery flow pytest result",
        "purpose": "Runs recovery tests for invalid predictions, ESP reconnect, relabel fallback, and calibration-file safety.",
        "expected": "4 passed",
        "runner": run_pytest,
        "args": ["tests/test_recovery_flow.py", "-v"],
    },
    "RT-2": {
        "id": "RT-2",
        "section": "Recovery Testing",
        "title": "recovery flow detailed test names",
        "purpose": "Shows every recovery scenario and its PASSED status.",
        "expected": "Recovery test names listed as PASSED",
        "runner": run_pytest,
        "args": ["tests/test_recovery_flow.py", "-v"],
    },
    "SCT-1": {
        "id": "SCT-1",
        "section": "Security Testing",
        "title": "backend/security pytest result",
        "purpose": "Runs backend unit tests that include auth, duplicate user, password, and admin route protection checks.",
        "expected": "5 passed",
        "runner": run_pytest,
        "args": ["tests/test_backend_unit.py", "-v"],
    },
    "SCT-2": {
        "id": "SCT-2",
        "section": "Security Testing",
        "title": "auth and admin security test cases",
        "purpose": "Runs the specific authentication and admin-token protection tests.",
        "expected": "Auth/security test names listed as PASSED",
        "runner": run_pytest,
        "args": [
            "tests/test_backend_unit.py::test_auth_register_login_duplicate_and_wrong_password",
            "tests/test_backend_unit.py::test_user_update_validates_and_prevents_duplicate_usernames",
            "tests/test_backend_unit.py::test_admin_json_routes_are_protected_by_admin_token",
            "-v",
        ],
    },
    "SCT-3": {
        "id": "SCT-3",
        "section": "Security Testing",
        "title": "admin route unauthorized response",
        "purpose": "Directly calls /admin/users.json without the required token and prints the HTTP status.",
        "expected": "Actual status: 401",
        "runner": run_admin_unauthorized,
    },
}


def list_items():
    print("Available report evidence IDs:")
    for item_id in ITEMS:
        item = ITEMS[item_id]
        print(f"  {item_id}: {item['title']}")


def main():
    parser = argparse.ArgumentParser(
        description="Run report evidence commands with explanatory terminal output."
    )
    parser.add_argument("--id", dest="item_id", help="Evidence ID to run, for example UT-1")
    parser.add_argument("--all", action="store_true", help="Run every evidence command")
    parser.add_argument("--list", action="store_true", help="List available evidence IDs")
    args = parser.parse_args()

    if args.list:
        list_items()
        return 0

    if args.all:
        failed = []
        for item in ITEMS.values():
            code = item["runner"](item)
            print()
            print(f"Result for {item['id']}: {'PASSED' if code == 0 else 'FAILED'}")
            print()
            if code != 0:
                failed.append(item["id"])
        if failed:
            print("Failed evidence IDs:", ", ".join(failed))
            return 1
        return 0

    if not args.item_id:
        parser.error("Provide --id, --all, or --list")

    item_id = args.item_id.upper()
    item = ITEMS.get(item_id)

    if item is None:
        print(f"Unknown evidence ID: {args.item_id}")
        list_items()
        return 1

    return item["runner"](item)


if __name__ == "__main__":
    raise SystemExit(main())
