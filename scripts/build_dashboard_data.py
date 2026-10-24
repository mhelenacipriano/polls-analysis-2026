#!/usr/bin/env python3
"""Convert data/polls.csv into public/polls.json, which the dashboard loads on start."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "model"))
from simulate import load_polls  # noqa: E402

polls = load_polls(ROOT / "data" / "polls.csv")
out = [{
    "id": p["id"], "name": p["pollster"], "field": p["field_dates"] or "—",
    "released": p["released"], "days": p["days"], "n": p["n"],
    "flavio": p["flavio"], "groupA": p["group_a"],
    "reg": p["registration"], "src": p["source"],
} for p in polls]
dest = ROOT / "public" / "polls.json"
dest.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"Wrote {len(out)} polls to {dest.relative_to(ROOT)}")
