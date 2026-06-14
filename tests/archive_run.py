"""
Archive the current River Signal release artifacts.

Run after a successful release:
    python tests/archive_run.py
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from utils import load_config, now_tag  # noqa: E402


def archive_current_run(config: dict | None = None) -> Path:
    """Copy current processed and output artifacts to a timestamped archive."""

    cfg = config or load_config()
    timestamp = now_tag()
    archive_dir = PROJECT_ROOT / "data" / "archive" / timestamp
    archive_dir.mkdir(parents=True, exist_ok=False)

    processed_dir = PROJECT_ROOT / cfg.get("paths", {}).get("processed_data", "data/processed")
    output_dir = PROJECT_ROOT / cfg.get("paths", {}).get("output", "data/output")

    for pattern in ("*.parquet", "*.json"):
        _copy_matches(processed_dir, pattern, archive_dir)
    _copy_matches(output_dir, "*.json", archive_dir)

    return archive_dir


def _copy_matches(source_dir: Path, pattern: str, archive_dir: Path) -> None:
    if not source_dir.exists():
        return
    for source in source_dir.glob(pattern):
        if source.is_file():
            shutil.copy2(source, archive_dir / source.name)


def main() -> int:
    archive_dir = archive_current_run()
    print(f"Archived current run to {archive_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
