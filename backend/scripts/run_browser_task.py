"""Run one browser-agent task and print steps and wall-clock time.

  uv run python scripts/run_browser_task.py dashdish "Order one Classic Cheeseburger from Souvla for delivery and place the order"
  flags: --headed  --no-screenshot  --max-steps N
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
for noisy in ("httpx", "openai", "httpcore", "browsergym", "agisdk"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

from browser_agent.runner import BrowserJobRunner  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("site", choices=["dashdish", "udriver", "taskhare"])
    ap.add_argument("goal")
    ap.add_argument("--headed", action="store_true", help="show the browser window")
    ap.add_argument("--no-screenshot", action="store_true", help="accessibility tree only, no screenshot to the model")
    ap.add_argument("--max-steps", type=int, default=None)
    ap.add_argument("--flow-key", default=None, help="learn/replay a named flow, e.g. usual-soup")
    ap.add_argument("--no-replay", action="store_true", help="ignore any learned flow (but still save one)")
    args = ap.parse_args()

    job = BrowserJobRunner().run_now(
        args.site, args.goal, headless=not args.headed, use_screenshot=not args.no_screenshot, max_steps=args.max_steps,
        flow_key=args.flow_key, replay=not args.no_replay,
    )
    print("\n=== RESULT ===")
    print("status:   ", job.status)
    print("steps:    ", job.steps, f"(model calls: {job.model_calls}, replayed: {job.replayed_steps})")
    print("seconds:  ", job.seconds)
    print("final url:", job.final_url)
    print("result:   ", job.result_text or job.error)
    print("actions:")
    for i, a in enumerate(job.actions, 1):
        print(f"  {i:2d}. {a[:140]}")


if __name__ == "__main__":
    main()
