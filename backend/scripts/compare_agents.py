"""Compare the Muse Spark runner with jev-ultrafast on the same DashDish task.

  uv run python scripts/compare_agents.py --trials 3 [--agents muse,jev] [--goal "..."]

Each trial resets the clone, runs one first-time order (no learned-flow replay), and verifies the
outcome independently by looking for an order id on the final page. Results go to
data/benchmarks/<timestamp>.json and a summary table is printed.
"""

import argparse
import json
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
logging.getLogger("browser_agent").setLevel(logging.INFO)

from browser_agent.verify import dashdish_order_confirmed  # noqa: E402

GOAL = "Order one Classic Cheeseburger from Souvla for delivery and place the order."


def run_muse(goal):
    from browser_agent.runner import BrowserJobRunner

    job = BrowserJobRunner().run_now("dashdish", goal, use_screenshot=False, replay=False)
    return {"agent": "muse", "status": job.status, "seconds": job.seconds, "steps": job.steps,
            "decisions": job.model_calls, "final_url": job.final_url,
            "order_id": dashdish_order_confirmed(job.final_text), "claim": job.result_text or job.error}


def run_jev(goal):
    from browser_agent import jev_runner

    r = jev_runner.run("dashdish", goal)
    return {"agent": "jev", "status": r.status, "seconds": r.seconds, "seconds_after_first_obs": r.seconds_after_first_observation,
            "steps": r.steps, "decisions": r.decisions, "text_calls": r.text_calls, "final_url": r.final_url,
            "order_id": dashdish_order_confirmed(r.final_text), "claim": r.error or r.status,
            "actions": [h.get("action") for h in r.history]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=3)
    ap.add_argument("--agents", default="muse,jev")
    ap.add_argument("--goal", default=GOAL)
    args = ap.parse_args()
    runners = {"muse": run_muse, "jev": run_jev}
    rows = []
    for name in args.agents.split(","):
        for t in range(1, args.trials + 1):
            print(f"\n=== {name} trial {t}/{args.trials} ===", flush=True)
            row = runners[name](args.goal)
            row["trial"] = t
            row["confirmed"] = bool(row["order_id"])
            rows.append(row)
            print(f"  {row['status']:8s} {row['seconds']:6.1f}s  steps={row['steps']:2d} decisions={row['decisions']:2d} confirmed={row['confirmed']}  {str(row['claim'])[:80]}", flush=True)
    out = Path(__file__).resolve().parent.parent / "data" / "benchmarks"
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{time.strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps({"goal": args.goal, "rows": rows}, indent=2))

    print("\n=== summary ===")
    print(f"{'agent':6s} {'runs':>4s} {'confirmed':>9s} {'median s':>9s} {'min s':>6s} {'max s':>6s} {'median decisions':>16s}")
    for name in args.agents.split(","):
        rs = [r for r in rows if r["agent"] == name]
        secs = sorted(r["seconds"] for r in rs)
        dec = sorted(r["decisions"] for r in rs)
        med = lambda xs: xs[len(xs) // 2] if xs else 0  # noqa: E731
        print(f"{name:6s} {len(rs):4d} {sum(r['confirmed'] for r in rs):9d} {med(secs):9.1f} {secs[0] if secs else 0:6.1f} {secs[-1] if secs else 0:6.1f} {med(dec):16d}")
    print("saved:", path)


if __name__ == "__main__":
    main()
