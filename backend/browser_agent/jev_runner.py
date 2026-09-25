"""Experiment: run a REAL clone task with jev-ultrafast (TypeSafe Jev picks operation + element,
Muse Spark writes any typed text) and measure it the same way as BrowserJobRunner.

Requires a Chromium started with --remote-debugging-port and BU_CDP_WS / JEV_CDP_WS pointing at
its websocket, plus TYPESAFE_API_KEY. See scripts/compare_agents.py.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field

from config import settings

log = logging.getLogger(__name__)


@dataclass
class JevResult:
    site: str
    goal: str
    status: str = "failed"  # done | blocked | failed
    seconds: float = 0.0
    seconds_after_first_observation: float = 0.0
    steps: int = 0
    decisions: int = 0
    text_calls: int = 0
    final_url: str = ""
    final_text: str = ""
    error: str = ""
    history: list[dict] = field(default_factory=list)


def _env() -> None:
    if settings.typesafe_api_key:
        os.environ.setdefault("TYPESAFE_API_KEY", settings.typesafe_api_key)
    os.environ.setdefault("TYPESAFE_MODEL", settings.typesafe_model)
    ws = settings.jev_cdp_ws or os.environ.get("BU_CDP_WS", "")
    if ws:
        os.environ["BU_CDP_WS"] = ws
    # The library's own text helper always sends a `reasoning` field Meta rejects; we replace it.
    os.environ.setdefault("TEXT_MODEL_API_KEY", settings.meta_api_key or "unused")


def _muse_field_text(context: dict):
    """Drop-in for jev_ultrafast.model.field_text using Muse Spark: returns (text, meta)."""
    from browser_agent import muse
    from jev_ultrafast.questions import TEXT_VALUE

    started = time.perf_counter()
    reply = muse.complete(
        [{"role": "system", "content": TEXT_VALUE + '\nAnswer with a JSON object {"text": "..."} and nothing else.'},
         {"role": "user", "content": json.dumps(context)}],
        max_tokens=600,
    )
    m = re.search(r"\{.*\}", reply, re.S)
    value = json.loads(m.group(0))["text"] if m else reply.strip().strip('"')
    if not isinstance(value, str) or not value.strip() or len(value) > 2000:
        raise ValueError("Text helper returned no valid field value; nothing typed.")
    return value, {"model": settings.muse_model, "latency_ms": round((time.perf_counter() - started) * 1000)}


def reset_clone_state(site_url: str, task_id: str = "dashdish-1") -> None:
    """Same reset the REAL SDK performs: /config then /finish in the harness browser profile."""
    from browser_harness.helpers import cdp

    for path in (f"/config?run_id=0&task_id={task_id}&latency=0", "/finish"):
        target = cdp("Target.createTarget", url=site_url.rstrip("/") + path, background=True)["targetId"]
        time.sleep(1.5)
        cdp("Target.closeTarget", targetId=target)


def run(site: str, goal: str, max_steps: int | None = None) -> JevResult:
    from browser_agent.tasks import goal_with_hints, site_url

    _env()
    import jev_ultrafast.agent as jev_agent
    import jev_ultrafast.model as jev_model

    jev_model.field_text = _muse_field_text  # used via module attribute inside agent.py
    jev_agent.field_text = _muse_field_text
    if max_steps:
        jev_agent.MAX_STEPS = max_steps
    from jev_ultrafast import Agent

    res = JevResult(site=site, goal=goal)
    url = site_url(site)
    started = time.perf_counter()
    try:
        reset_clone_state(url, f"{site}-1")
        with Agent(url, [goal_with_hints(site, goal)]) as agent:
            state = agent.state
            for state in agent.run():
                pass
            res.status = state["status"] if state["status"] in ("done", "blocked") else "failed"
            res.history = list(state.get("history", []))
            res.steps = len(res.history)
            res.decisions = sum(1 for h in res.history) + (1 if res.status in ("done", "blocked") else 0)
            res.text_calls = sum(1 for h in res.history if h.get("text"))
            res.seconds_after_first_observation = round(state.get("elapsed_ms", 0) / 1000, 1)
            page = state.get("page") or {}
            res.final_url = page.get("url", "")
            res.final_text = page.get("text", "")
    except Exception as e:  # noqa: BLE001
        log.exception("jev run failed")
        res.error = f"{type(e).__name__}: {str(e)[:200]}"
    res.seconds = round(time.perf_counter() - started, 1)
    return res
