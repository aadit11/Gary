"""BrowserJobRunner: runs browser-agent jobs on one worker thread and reports results.

    runner = BrowserJobRunner(); runner.start()
    job = runner.submit("dashdish", "Order ... and place the order", user_id=uid, flow_key="usual", on_done=cb)
    job = runner.run_now("dashdish", "...")   # blocking, for the CLI

Per job: if a learned flow exists for (site, flow_key) it is replayed first (name-based actions,
no model); at the first failure, or when the replay ends, the model takes over from the live
page. The model returns short plans (several actions per call); each action is executed
separately so a failure re-plans immediately. On success with a flow_key, the executed actions
are saved as a new learned flow.

One browser at a time is plenty for the demo. Playwright's sync API is thread-bound, so every
job runs entirely on the thread that created its environment.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from config import settings
from core import activity

log = logging.getLogger(__name__)


@dataclass
class BrowserJob:
    site: str
    goal: str
    user_id: str | None = None
    flow_key: str | None = None
    replay: bool = True
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    status: str = "queued"  # queued | running | done | infeasible | failed
    result_text: str = ""
    error: str = ""
    steps: int = 0
    model_calls: int = 0
    replayed_steps: int = 0
    seconds: float = 0.0
    final_url: str = ""
    final_text: str = ""  # accessibility text of the last page, for independent verification
    actions: list[str] = field(default_factory=list)
    executed: list[dict] = field(default_factory=list)  # {"action", "role", "name", "ok"}
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    on_done: Callable[["BrowserJob"], None] | None = None

    @property
    def ok(self) -> bool:
        return self.status == "done"


def _default_env_factory(site: str, goal: str, headless: bool) -> Any:
    from agisdk.REAL.browsergym.core.env import BrowserEnv

    from browser_agent.actions import ACTION_SET
    from browser_agent.tasks import FreeformCloneTask, goal_with_hints

    return BrowserEnv(
        FreeformCloneTask,
        task_kwargs={"site": site, "goal": goal_with_hints(site, goal)},
        headless=headless,
        viewport={"width": 1280, "height": 900},
        record_video_dir=settings.browser_video_dir or None,
        action_mapping=ACTION_SET.to_python_code,
    )


def _default_agent_factory(goal: str, use_screenshot: bool, site: str = "dashdish") -> Any:
    from browser_agent.agent import MuseSparkAgent
    from browser_agent.tasks import goal_with_hints

    return MuseSparkAgent(goal_with_hints(site, goal), use_screenshot=use_screenshot)


class BrowserJobRunner:
    def __init__(self, env_factory: Callable | None = None, agent_factory: Callable | None = None, flow_store: Any = None):
        from browser_agent.flows import FlowStore

        self._env_factory = env_factory or _default_env_factory
        self._agent_factory = agent_factory or _default_agent_factory
        self._flows = flow_store or FlowStore()
        self._queue: queue.Queue = queue.Queue()
        self._jobs: dict[str, BrowserJob] = {}
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    # --- lifecycle -------------------------------------------------------
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._worker, name="browser-agent", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._queue.put(None)

    def _worker(self) -> None:
        while not self._stop.is_set():
            job = self._queue.get()
            if job is None:
                break
            self._execute(job)

    # --- API ---------------------------------------------------------------
    def submit(self, site: str, goal: str, user_id: str | None = None, on_done: Callable | None = None,
               flow_key: str | None = None, replay: bool = True) -> BrowserJob:
        job = BrowserJob(site=site, goal=goal, user_id=user_id, on_done=on_done, flow_key=flow_key, replay=replay)
        self._jobs[job.id] = job
        self.start()
        self._queue.put(job)
        return job

    def get(self, job_id: str) -> BrowserJob | None:
        return self._jobs.get(job_id)

    def run_now(self, site: str, goal: str, user_id: str | None = None, headless: bool | None = None,
                use_screenshot: bool | None = None, max_steps: int | None = None,
                flow_key: str | None = None, replay: bool = True) -> BrowserJob:
        """Run a job on the calling thread (CLI and tests)."""
        job = BrowserJob(site=site, goal=goal, user_id=user_id, flow_key=flow_key, replay=replay)
        self._jobs[job.id] = job
        self._execute(job, headless=headless, use_screenshot=use_screenshot, max_steps=max_steps)
        return job

    # --- execution ---------------------------------------------------------
    def _make_agent(self, job: BrowserJob, use_screenshot: bool) -> Any:
        if self._agent_factory is _default_agent_factory:
            return self._agent_factory(job.goal, use_screenshot, job.site)
        return self._agent_factory(job.goal, use_screenshot)

    def _do_step(self, env: Any, job: BrowserJob, action: str, obs_before: dict | None) -> tuple[dict, bool]:
        """Execute one action; returns (new obs, ok)."""
        from browser_agent.agent import action_bid, element_info

        role = name = ""
        bid = action_bid(action)
        if bid and obs_before:
            role, name = element_info(obs_before, bid)
        url_before = obs_before.get("url", "") if isinstance(obs_before, dict) else job.final_url
        obs, _reward, _terminated, _truncated, _info = env.step(action)
        job.steps += 1
        job.actions.append(action)
        err = str(obs.get("last_action_error") or "") if isinstance(obs, dict) else ""
        url_after = obs.get("url", "") if isinstance(obs, dict) else ""
        job.executed.append({"action": action, "role": role, "name": name, "ok": not err,
                             "url_before": url_before, "url_after": url_after})
        if isinstance(obs, dict):
            job.final_url = obs.get("url", job.final_url)
        if err:
            log.info("job %s step %d error: %s", job.id, job.steps, err[:160])
        return obs, not err

    def _replay(self, env: Any, job: BrowserJob, agent: Any, obs: dict, flow: dict) -> dict:
        """Replay learned steps; stops at the first failure. Returns the latest obs.

        If every step succeeds and BROWSER_REPLAY_VERIFY is off, the job is marked done with the
        flow's stored result text and no model call is made."""
        from browser_agent.flows import step_to_action

        steps = flow.get("steps") or []
        log.info("job %s replaying learned flow '%s' (%d steps)", job.id, job.flow_key, len(steps))
        for i, step in enumerate(steps, 1):
            action = step_to_action(step)
            obs, ok = self._do_step(env, job, action, None)
            log.info("job %s replay %d/%d: %s%s", job.id, i, len(steps), action[:120], "" if ok else "  (FAILED)")
            if not ok:
                agent.note(f"Replayed {i - 1} of {len(steps)} learned steps, then '{action}' failed; continue from the current page.")
                return obs
            job.replayed_steps = i
            agent.record(action, None, "replayed from learned flow")
        if not settings.browser_replay_verify and flow.get("result_text"):
            job.status = "done"
            job.result_text = flow["result_text"]
            log.info("job %s replay complete; finishing without model verification", job.id)
            return obs
        agent.note(f"Replayed all {len(steps)} learned steps successfully, including the final confirmation click. Look at the current page: if it shows the order/booking went through, reply with the DONE message immediately as your only action. Do not wait, noop, or click anything unless something is clearly wrong.")
        return obs

    def _execute(self, job: BrowserJob, headless: bool | None = None, use_screenshot: bool | None = None,
                 max_steps: int | None = None) -> None:
        from browser_agent.agent import first_sentence, terminal_message

        headless = settings.browser_headless if headless is None else headless
        use_screenshot = settings.browser_use_screenshot if use_screenshot is None else use_screenshot
        max_steps = max_steps or settings.browser_max_steps
        deadline = time.monotonic() + settings.browser_timeout_s

        job.status = "running"
        started = time.monotonic()
        if job.user_id:
            activity.log_event(job.user_id, "browser_job_started", f"{job.site}: {job.goal[:120]}", {"job_id": job.id})
        log.info("job %s start site=%s headless=%s screenshot=%s flow=%s goal=%s", job.id, job.site, headless, use_screenshot, job.flow_key, job.goal)

        env = None
        try:
            env = self._env_factory(job.site, job.goal, headless)
            agent = self._make_agent(job, use_screenshot)
            obs, _info = env.reset()

            flow = self._flows.load(job.site, job.flow_key) if (job.flow_key and job.replay) else None
            if flow:
                obs = self._replay(env, job, agent, obs, flow)

            while job.status == "running":
                if time.monotonic() > deadline:
                    job.status, job.error = "failed", f"timed out after {settings.browser_timeout_s}s"
                    break
                if job.steps >= max_steps:
                    job.status, job.error = "failed", f"no result after {max_steps} steps"
                    break
                plan = agent.next_plan(obs)
                job.model_calls = agent.model_calls
                log.info("job %s plan (%d): %s", job.id, len(plan), " | ".join(a[:60] for a in plan))
                reason = first_sentence(agent.last_reply)
                for action in plan:
                    term = terminal_message(action)
                    if term:
                        kind, text = term
                        job.status = "done" if kind == "done" else "infeasible"
                        job.result_text = text
                        job.actions.append(action)
                        break
                    if job.steps >= max_steps or time.monotonic() > deadline:
                        break
                    agent.record(action, obs, reason)
                    reason = ""
                    obs, ok = self._do_step(env, job, action, obs)
                    log.info("job %s step %d: %s%s", job.id, job.steps, action[:140], "" if ok else "  (FAILED, re-planning)")
                    if not ok:
                        break
            try:
                from browser_agent.agent import full_text

                job.final_text = full_text(obs) if isinstance(obs, dict) else ""
            except Exception:  # noqa: BLE001
                pass
        except Exception as e:  # noqa: BLE001
            log.exception("job %s crashed", job.id)
            job.status, job.error = "failed", f"{type(e).__name__}: {str(e)[:200]}"
        finally:
            if env is not None:
                try:
                    env.close()
                except Exception:  # noqa: BLE001
                    log.exception("env close failed")
            job.seconds = round(time.monotonic() - started, 1)

        if job.ok and job.flow_key:
            from browser_agent.flows import compress_executed

            steps, complete = compress_executed(job.executed)
            if not complete:
                log.warning("job %s: flow not saved (a step has no role/name)", job.id)
            if complete and steps:
                import re as _re

                result = _re.sub(r",?\s*order id\s*\S+", "", job.result_text, flags=_re.I).strip()
                p = self._flows.save(job.site, job.flow_key, job.goal, steps, result)
                log.info("job %s: learned flow saved (%d steps) -> %s", job.id, len(steps), p)

        log.info("job %s %s in %.1fs / %d steps / %d model calls / %d replayed: %s", job.id, job.status, job.seconds,
                 job.steps, job.model_calls, job.replayed_steps, job.result_text or job.error)
        if job.user_id:
            activity.log_event(job.user_id, "browser_job_finished", f"{job.site} {job.status}: {job.result_text or job.error}",
                               {"job_id": job.id, "steps": job.steps, "seconds": job.seconds, "model_calls": job.model_calls, "final_url": job.final_url})
        if job.on_done:
            try:
                job.on_done(job)
            except Exception:  # noqa: BLE001
                log.exception("on_done failed for job %s", job.id)
