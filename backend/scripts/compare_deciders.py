"""Compare browser-agent deciders on the demo's two DashDish flows.

  uv run python scripts/compare_deciders.py --trials 3 --deciders llm,jev

Flow A: first-time order from the home page (Souvla cheeseburger).
Flow B: lookup Wingstop (park), then order "8 piece" on the parked page (the call's real sequence).
Success is checked independently: an order id (ORD-...) on the final page.
"""

import argparse
import json
import logging
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
logging.getLogger("browser_agent.runner").setLevel(logging.INFO)

_ORDER_ID = re.compile(r"\bORD-\d{6,}", re.I)


def confirmed(text: str) -> bool:
    return bool(_ORDER_ID.search(text or ""))


def flow_a(decider):
    from browser_agent.runner import BrowserJobRunner
    from config import settings
    j = BrowserJobRunner().run_now("dashdish", "Order one Classic Cheeseburger from Souvla for delivery and place the order.",
                                   headless=True, use_screenshot=False, replay=False, decider=decider)
    return {"flow": "A first-time order", "status": j.status, "seconds": j.seconds, "steps": j.steps, "calls": j.model_calls,
            "confirmed": confirmed(j.final_text), "claim": j.result_text or j.error}


def flow_b(decider):
    from browser_agent.runner import BrowserJobRunner
    from config import settings
    r = BrowserJobRunner()
    look = r.run_now("dashdish", "Look up Wingstop on DoorDash.", headless=True, use_screenshot=False, lookup=True, park=True,
                     park_when="OPEN", page_name="Wingstop", user_id=settings.demo_user_id, decider=decider)
    order = r.run_now("dashdish", "Find 8 piece and place the delivery order.", headless=True, use_screenshot=False,
                      user_id=settings.demo_user_id, decider=decider)
    return {"flow": "B lookup+parked order", "status": f"{look.status}/{order.status}", "seconds": round(look.seconds + order.seconds, 1),
            "lookup_s": look.seconds, "order_s": order.seconds, "steps": look.steps + order.steps, "calls": look.model_calls + order.model_calls,
            "confirmed": confirmed(order.final_text) and "OPEN" in (look.result_text or ""), "claim": (look.result_text or look.error) + " || " + (order.result_text or order.error)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=3)
    ap.add_argument("--deciders", default="llm,jev")
    ap.add_argument("--flows", default="A,B")
    args = ap.parse_args()
    rows = []
    for decider in args.deciders.split(","):
        for flow in args.flows.split(","):
            fn = flow_a if flow == "A" else flow_b
            for t in range(1, args.trials + 1):
                print(f"\n=== {decider} flow {flow} trial {t}/{args.trials} ===", flush=True)
                row = fn(decider); row.update(decider=decider, trial=t); rows.append(row)
                print(f"  {row['status']:12s} {row['seconds']:6.1f}s steps={row['steps']:2d} calls={row['calls']:2d} confirmed={row['confirmed']}  {str(row['claim'])[:90]}", flush=True)
    out = Path(__file__).resolve().parent.parent / "data" / "benchmarks"; out.mkdir(parents=True, exist_ok=True)
    path = out / f"deciders-{time.strftime('%Y%m%d-%H%M%S')}.json"; path.write_text(json.dumps(rows, indent=2))
    print("\n=== summary ===")
    print(f"{'decider':8s} {'flow':24s} {'ok':>5s} {'median s':>9s} {'min':>6s} {'max':>6s} {'med calls':>9s}")
    for decider in args.deciders.split(","):
        for flow in args.flows.split(","):
            rs = [r for r in rows if r["decider"] == decider and r["flow"].startswith(flow)]
            if not rs: continue
            secs = sorted(r["seconds"] for r in rs); calls = sorted(r["calls"] for r in rs)
            print(f"{decider:8s} {rs[0]['flow']:24s} {sum(r['confirmed'] for r in rs)}/{len(rs):<3d} {secs[len(secs)//2]:9.1f} {secs[0]:6.1f} {secs[-1]:6.1f} {calls[len(calls)//2]:9d}")
    print("saved:", path)


if __name__ == "__main__":
    main()
