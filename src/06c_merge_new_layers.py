"""Merge WFD status and discharge points data into ranked_feed.json."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

WFD_PATH = ROOT / "data" / "processed" / "site_wfd_status.json"
DISCHARGE_PATH = ROOT / "data" / "processed" / "site_discharge_points.json"
FEED_PATH = ROOT / "data" / "output" / "ranked_feed.json"
FRONTEND_FEED_PATH = ROOT / "frontend" / "public" / "data" / "ranked_feed.json"


def load_lookup(path: Path, key: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        records = json.load(f)
    return {r["site_id"]: r.get(key) for r in records}


def main():
    wfd_lookup = load_lookup(WFD_PATH, "wfd_status")
    discharge_lookup = load_lookup(DISCHARGE_PATH, "discharge_points")
    print(f"Loaded {len(wfd_lookup)} WFD status records")
    print(f"Loaded {len(discharge_lookup)} discharge point records")

    with open(FEED_PATH, "r", encoding="utf-8") as f:
        feed_data = json.load(f)

    sites = feed_data["feed"]
    wfd_added = 0
    discharge_added = 0

    for site in sites:
        sid = site.get("site_id")

        wfd = wfd_lookup.get(sid)
        if wfd:
            site["wfd_status"] = wfd
            wfd_added += 1
        else:
            site.pop("wfd_status", None)

        dp = discharge_lookup.get(sid)
        if dp and dp.get("has_discharge_points"):
            site["discharge_points"] = dp
            discharge_added += 1
        else:
            site.pop("discharge_points", None)

    feed_data["feed"] = sites

    for dest in (FEED_PATH, FRONTEND_FEED_PATH):
        with open(dest, "w", encoding="utf-8") as f:
            json.dump(feed_data, f, indent=2, ensure_ascii=False)
        print(f"Saved: {dest}")

    total = len(sites)
    print(f"\nMerged into {total} sites:")
    print(f"  WFD status added: {wfd_added}")
    print(f"  Discharge points added: {discharge_added}")


if __name__ == "__main__":
    main()
