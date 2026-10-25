#!/usr/bin/env python3
"""Monte Carlo forecast of the 2026 Brazilian presidential runoff (Lula vs Flávio).

Same model as the dashboard:
  1. Pool each poll's Flávio valid-vote share into a weighted average.
     weight = 0.5 ** (days_before_vote / half_life)
              * sqrt(min(sample, 5000))          (optional)
              * 1.5 if pollster is in accuracy group A (optional)
     By default only each pollster's most recent poll counts.
  2. Draw N elections: share ~ Normal(mean + bias, sigma).
  3. Win probability = share of draws above 50%.

Standard library only. Usage:
  python model/simulate.py                      # base case
  python model/simulate.py --sigma 3 --bias -1  # scenario
  python model/simulate.py --json out.json      # write results for the dashboard
"""
import argparse
import csv
import json
import math
import random
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ELECTION_DAY = date(2026, 10, 25)


def load_polls(path):
    polls = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if not row.get("flavio_valid"):
                continue  # registered but results not published yet
            released = date.fromisoformat(row["released"])
            polls.append({
                "id": row["id"],
                "pollster": row["pollster"],
                "field_dates": row.get("field_dates", ""),
                "released": row["released"],
                "days": (ELECTION_DAY - released).days,
                "n": int(row["sample_size"] or 2000),  # unknown sample: weigh it like a typical 2,000
                "n_known": bool(row["sample_size"]),
                "notes": row.get("notes", ""),
                "flavio": float(row["flavio_valid"]),
                "group_a": row.get("group_a", "0") == "1",
                "registration": row.get("tse_registration", ""),
                "source": row.get("source", ""),
            })
    return polls


def select(polls, latest_only=True, max_days=None):
    out = [p for p in polls if max_days is None or p["days"] <= max_days]
    if latest_only:
        newest = {}
        for p in out:
            cur = newest.get(p["pollster"])
            if cur is None or p["days"] < cur["days"]:
                newest[p["pollster"]] = p
        out = list(newest.values())
    return out


def weight(p, half_life=5.0, by_sample=True, by_quality=True):
    w = 0.5 ** (p["days"] / half_life)
    w *= math.sqrt(min(p["n"], 5000)) if by_sample else math.sqrt(2000)
    if by_quality and p["group_a"]:
        w *= 1.5
    return w


def aggregate(polls, **kw):
    ws = [weight(p, **kw) for p in polls]
    total = sum(ws)
    mean = sum(p["flavio"] * w for p, w in zip(polls, ws)) / total
    return mean, [w / total for w in ws]


def simulate(mean, sigma=2.0, bias=0.0, n=40000, seed=None):
    rng = random.Random(seed)
    center = mean + bias
    draws = sorted(rng.gauss(center, sigma) for _ in range(n))
    wins = sum(1 for x in draws if x > 50)
    q = lambda p: draws[min(n - 1, int(p * n))]
    return {
        "center": center,
        "p_flavio": wins / n,
        "p_lula": 1 - wins / n,
        "median": q(0.5),
        "p10": q(0.10), "p90": q(0.90),
        "p025": q(0.025), "p975": q(0.975),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--polls", default=ROOT / "data" / "polls.csv")
    ap.add_argument("--sigma", type=float, default=2.0, help="polling error SD on Flávio's share (pts)")
    ap.add_argument("--bias", type=float, default=0.0, help="shift toward Flávio (+) or Lula (-), pts")
    ap.add_argument("--half-life", type=float, default=5.0)
    ap.add_argument("--all-waves", action="store_true", help="count every poll, not just each pollster's latest")
    ap.add_argument("--max-days", type=int, default=None, help="drop polls released more than N days before the vote")
    ap.add_argument("--no-sample-weight", action="store_true")
    ap.add_argument("--no-quality-weight", action="store_true")
    ap.add_argument("--n", type=int, default=40000)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--json", help="write polls + result to this path")
    a = ap.parse_args()

    polls = select(load_polls(a.polls), latest_only=not a.all_waves, max_days=a.max_days)
    if not polls:
        raise SystemExit("No polls selected.")
    mean, shares = aggregate(polls, half_life=a.half_life,
                             by_sample=not a.no_sample_weight, by_quality=not a.no_quality_weight)
    res = simulate(mean, a.sigma, a.bias, a.n, a.seed)

    print(f"Polls used: {len(polls)}")
    for p, s in sorted(zip(polls, shares), key=lambda t: -t[1]):
        print(f"  {p['pollster']:<20} {p['released']}  Flávio {p['flavio']:5.1f}  weight {s*100:5.1f}%")
    print(f"\nWeighted average: Flávio {mean:.2f}% / Lula {100-mean:.2f}% (valid votes)")
    print(f"Center after bias: {res['center']:.2f}%   sigma {a.sigma}")
    print(f"P(Flávio wins) = {res['p_flavio']*100:.1f}%   P(Lula wins) = {res['p_lula']*100:.1f}%")
    print(f"80% range for Flávio: {res['p10']:.1f}–{res['p90']:.1f}%")

    if a.json:
        Path(a.json).write_text(json.dumps({"polls": polls, "weighted_mean": mean, "result": res,
                                            "params": vars(a) | {"polls": str(a.polls)}},
                                           ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        print(f"\nWrote {a.json}")


if __name__ == "__main__":
    main()
