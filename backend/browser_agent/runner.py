"""BrowserJobRunner: runs browser-agent jobs on one worker thread and reports results.

    runner = BrowserJobRunner(); runner.start()
    job = runner.submit("dashdish", "Order ... and place the order", user_id=uid, on_done=callback)
    ...
    job = runner.run_now("dashdish", "...")   # blocking, for the CLI

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
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    status: str = "queued"  # queued | running | done | infeasible | failed
    result_text: str = ""
    error: str = ""
    steps: int = 0
    seconds: float = 0.0
    final_url: str = ""
    actions: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    on_done: Callable[["BrowserJob"], None] | None = None

    @property
    def ok(self) -> bool:
        return self.status == "done"


def _default_env_factory(site: str, goal: str, headless: bool) -> Any:
    from agisdk.REAL.browsergym.core.env import BrowserEnv

    from browser_agent.agent import ACTION_SET
    from browser_agent.tasks import FreeformCloneTask, goal_with_hints

    goal = goal_with_hints(site, goal)
    return BrowserEnv(
        FreeformCloneTask,
        task_kwargs={"site": site, "goal": goal},
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
    def __init__(self, env_factory: Callable | None = None, agent_factory: Callable | None = None):
        self._env_factory = env_factory or _default_env_factory
        self._agent_factory = agent_factory or _default_agent_factory
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
    def submit(self, site: str, goal: str, user_id: str | None = None, on_done: Callable | None = None) -> BrowserJob:
        job = BrowserJob(site=site, goal=goal, user_id=user_id, on_done=on_done)
        self._jobs[job.id] = job
        self.start()
        self._queue.put(job)
        return job

    def get(self, job_id: str) -> BrowserJob | None:
        return self._jobs.get(job_id)

    def run_now(self, site: str, goal: str, user_id: str | None = None, headless: bool | None = None,
                use_screenshot: bool | None = None, max_steps: int | None = None) -> BrowserJob:
        """Run a job on the calling thread (CLI and tests)."""
        job = BrowserJob(site=site, goal=goal, user_id=user_id)
        self._jobs[job.id] = job
        self._execute(job, headless=headless, use_screenshot=use_screenshot, max_steps=max_steps)
        return job

    # --- execution ---------------------------------------------------------
    def _execute(self, job: BrowserJob, headless: bool | None = None, use_screenshot: bool | None = None,
                 max_steps: int | None = None) -> None:
        from browser_agent.agent import terminal_message

        headless = settings.browser_headless if headless is None else headless
        use_screenshot = settings.browser_use_screenshot if use_screenshot is None else use_screenshot
        max_steps = max_steps or settings.browser_max_steps
        deadline = time.monotonic() + settings.browser_timeout_s

        job.status = "running"
        started = time.monotonic()
        if job.user_id:
            activity.log_event(job.user_id, "browser_job_started", f"{job.site}: {job.goal[:120]}", {"job_id": job.id})
        log.info("job %s start site=%s headless=%s screenshot=%s goal=%s", job.id, job.site, headless, use_screenshot, job.goal)

        env = None
        try:
            env = self._env_factory(job.site, job.goal, headless)
            agent = self._agent_factory(job.goal, use_screenshot, job.site) if self._agent_factory is _default_agent_factory else self._agent_factory(job.goal, use_screenshot)
            obs, _info = env.reset()
            for step in range(1, max_steps + 1):
                if time.monotonic() > deadline:
                    job.status, job.error = "failed", f"timed out after {settings.browser_timeout_s}s"
                    break
                action = agent.next_action(obs)
                job.actions.append(action)
                job.steps = step
                job.final_url = obs.get("url", "") if isinstance(obs, dict) else ""
                log.info("job %s step %d: %s", job.id, step, (agent.action_history[-1] if getattr(agent, "action_history", None) else action)[:220])
                term = terminal_message(action)
                if term:
                    kind, text = term
                    job.status = "done" if kind == "done" else "infeasible"
                    job.result_text = text
                    break
                obs, _reward, terminated, truncated, _info = env.step(action)
                if isinstance(obs, dict) and obs.get("last_action_error"):
                    log.info("job %s step %d error: %s", job.id, step, str(obs["last_action_error"])[:160])
                if terminated or truncated:
                    job.status, job.error = "failed", "environment ended the episode"
                    break
            else:
                job.status, job.error = "failed", f"no result after {max_steps} steps"
            if isinstance(obs, dict):
                job.final_url = obs.get("url", job.final_url)
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

        log.info("job %s %s in %.1fs / %d steps: %s", job.id, job.status, job.seconds, job.steps, job.result_text or job.error)
        if job.user_id:
            activity.log_event(job.user_id, "browser_job_finished", f"{job.site} {job.status}: {job.result_text or job.error}",
                               {"job_id": job.id, "steps": job.steps, "seconds": job.seconds, "final_url": job.final_url})
        if job.on_done:
            try:
                job.on_done(job)
            except Exception:  # noqa: BLE001
                log.exception("on_done failed for job %s", job.id)
