"""
Shared utilities for the river chemistry anomaly engine.
Config loading, logging, and common helpers.
"""

import yaml
import logging
from pathlib import Path
from datetime import datetime

import polars as pl


# ── Paths ──

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config" / "settings.yaml"


def load_config(path: Path = CONFIG_PATH) -> dict:
    """Load YAML config. Returns dict."""
    with open(path) as f:
        return yaml.safe_load(f)


def get_path(config: dict, key: str) -> Path:
    """Resolve a relative path from config to absolute."""
    return PROJECT_ROOT / config["paths"][key]


# ── Logging ──

def setup_logger(name: str, level: str = "INFO") -> logging.Logger:
    """Consistent logger across pipeline stages."""
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level))

    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            "%(asctime)s | %(name)-18s | %(levelname)-5s | %(message)s",
            datefmt="%H:%M:%S",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger


# ── Stage stats (from your notebooks) ──

def stage_stats(df: pl.DataFrame, label: str, logger: logging.Logger = None) -> pl.DataFrame:
    """
    Print row/site/determinand counts at a pipeline stage.
    Pass-through: returns the same DataFrame for chaining.
    """
    n_rows = df.height
    n_sites = df.select(pl.col("site_id").n_unique()).item()

    # determinant column may not exist at every stage
    if "determinant" in df.columns:
        n_dets = df.select(pl.col("determinant").n_unique()).item()
        msg = f"{label:<45} {n_rows:>12,} rows | {n_sites:>8,} sites | {n_dets:>6,} dets"
    else:
        msg = f"{label:<45} {n_rows:>12,} rows | {n_sites:>8,} sites"

    if logger:
        logger.info(msg)
    else:
        print(msg)

    return df


# ── Timestamp helpers ──

def now_tag() -> str:
    """Short timestamp for output filenames: 20260610_143022"""
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def ensure_dir(path: Path) -> Path:
    """Create directory if it doesn't exist. Returns the path."""
    path.mkdir(parents=True, exist_ok=True)
    return path
