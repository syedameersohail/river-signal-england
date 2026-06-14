"""
CLI runner for River Signal quality gates.

Usage:
    python tests/run_gates.py
    python tests/run_gates.py --gate 2
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Callable

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils import load_config  # noqa: E402
from quality_gates import (  # noqa: E402
    GateResult,
    gate_1_data_sanity,
    gate_2_ranking_quality,
    gate_3_output_quality,
)


GateFunction = Callable[[dict], GateResult]

GATES: dict[int, GateFunction] = {
    1: gate_1_data_sanity,
    2: gate_2_ranking_quality,
    3: gate_3_output_quality,
}

GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
RESET = "\033[0m"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run River Signal quality gates.")
    parser.add_argument("--gate", type=int, choices=GATES.keys(), help="Run a single gate by number.")
    args = parser.parse_args()

    config = load_config()
    gate_numbers = [args.gate] if args.gate else sorted(GATES)
    results = [GATES[number](config) for number in gate_numbers]

    print_report(results)
    save_report(results)

    return 0 if all(result.passed for result in results) else 1


def print_report(results: list[GateResult]) -> None:
    for result in results:
        status = _status(result.passed)
        print()
        print(f"{result.gate_name} {status}")
        print("-" * 88)
        print(f"{'Status':<8} {'Check':<28} Message")
        print("-" * 88)
        for check in result.checks:
            print(f"{_status(check.passed):<17} {check.name:<28} {check.message}")

    overall = all(result.passed for result in results)
    print()
    print(f"Overall: {_status(overall)}")


def save_report(results: list[GateResult]) -> None:
    output_dir = PROJECT_ROOT / "data" / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "gate_report.json"
    payload = {
        "passed": all(result.passed for result in results),
        "gates": [asdict(result) for result in results],
    }
    with open(report_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, default=str)
    print(f"Saved full report: {report_path}")


def _status(passed: bool) -> str:
    return f"{GREEN}PASS{RESET}" if passed else f"{RED}FAIL{RESET}"


if __name__ == "__main__":
    raise SystemExit(main())
