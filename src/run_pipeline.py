"""
River Chemistry Anomaly Engine — Full Pipeline Runner
=====================================================
Runs all four layers in sequence:
  01_ingest → 02_fingerprint → 03_score → 04_narrate

Usage:
    python src/run_pipeline.py              # run all layers
    python src/run_pipeline.py --from 3     # resume from layer 3 (scoring)
"""

import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
TESTS_DIR = PROJECT_ROOT / "tests"

for directory in [str(SRC_DIR), str(TESTS_DIR)]:
    if directory not in sys.path:
        sys.path.insert(0, directory)

from utils import load_config, setup_logger  # noqa: E402

from quality_gates import (  # noqa: E402
    GateResult,
    gate_1_data_sanity,
    gate_2_ranking_quality,
    gate_3_output_quality,
)


log = setup_logger("pipeline")


def run(start_from: int = 1):
    """Run the pipeline from the specified layer."""

    config = load_config()

    log.info("=" * 60)
    log.info("RIVER CHEMISTRY ANOMALY ENGINE")
    log.info(f"Started at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log.info("=" * 60)

    t0 = time.time()

    layers = [
        (1, "INGEST",      "01_ingest"),
        (2, "FINGERPRINT", "02_fingerprint"),
        (3, "SCORE",       "03_score"),
        (4, "NARRATE",     "04_narrate"),
    ]

    for num, name, module_name in layers:
        if num < start_from:
            log.info(f"Skipping Layer {num} — {name}")
            continue

        log.info(f"\n{'─' * 40}")
        log.info(f"Running Layer {num} — {name}")
        log.info(f"{'─' * 40}")

        t_layer = time.time()

        # Dynamic import and run
        module = __import__(module_name)
        module.run()

        elapsed = time.time() - t_layer
        log.info(f"Layer {num} completed in {elapsed:.1f}s")

        if num == 1:
            _run_gate(gate_1_data_sanity(config))
        elif num == 3:
            _run_gate(gate_2_ranking_quality(config))
        elif num == 4:
            _run_gate(gate_3_output_quality(config))

    total = time.time() - t0
    log.info(f"\n{'=' * 60}")
    log.info(f"Pipeline complete in {total:.1f}s")
    log.info(f"Output: data/output/ranked_feed.json")
    log.info("All gates passed. Ready to publish.")
    log.info(f"{'=' * 60}")


def _run_gate(result: GateResult) -> None:
    """Log a gate result and halt the pipeline on failure."""

    status = "PASSED" if result.passed else "FAILED"
    log.info(f"{result.gate_name}: {status}")
    for check in result.checks:
        check_status = "PASS" if check.passed else "FAIL"
        log.info(f"  [{check_status}] {check.name}: {check.message}")

    if not result.passed:
        log.error(f"{result.gate_name} failed. Pipeline halted.")
        raise SystemExit(1)


if __name__ == "__main__":
    start = 1
    if "--from" in sys.argv:
        idx = sys.argv.index("--from")
        if idx + 1 < len(sys.argv):
            start = int(sys.argv[idx + 1])

    run(start_from=start)
