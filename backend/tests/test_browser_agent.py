import numpy as np

from browser_agent import agent as agent_mod
from browser_agent.agent import MuseSparkAgent, parse_action, terminal_message
from browser_agent.runner import BrowserJobRunner


def _obs(url="https://x/", err=""):
    return {
        "url": url,
        "axtree_object": {"nodes": [{"nodeId": "1", "role": {"value": "RootWebArea"}, "name": {"value": "Home"}, "childIds": []}]},
        "extra_element_properties": {},
        "screenshot": np.zeros((10, 10, 3), dtype=np.uint8),
        "last_action_error": err,
    }


def test_parse_action_takes_last_fenced_block():
    assert parse_action('thinking\n```click("12")```') == 'click("12")'
    assert parse_action('```python\nfill("3", "a")\n```\nmore\n```\nclick("4")\n```') == 'click("4")'
    assert parse_action("no code here") is None


def test_terminal_message():
    assert terminal_message('send_msg_to_user("DONE: ordered soup, $18.50")') == ("done", "DONE: ordered soup, $18.50")
    assert terminal_message("report_infeasible('closed')") == ("infeasible", "closed")
    assert terminal_message('click("1")') is None


def test_prompt_contains_goal_tree_actions_and_history():
    replies = iter(['```click("5")```', '```click("6")```'])
    a = MuseSparkAgent("Order soup", use_screenshot=True, complete=lambda m: next(replies))
    assert a.next_action(_obs()) == 'click("5")'
    msgs = a.build_messages(_obs(err="boom"))
    text = "\n".join(p["text"] for p in msgs[1]["content"] if p["type"] == "text")
    assert "Order soup" in text and "Accessibility Tree" in text and "Action Space" in text
    assert 'click("5")' in text and "boom" in text
    assert any(p["type"] == "image_url" for p in msgs[1]["content"])
    a2 = MuseSparkAgent("x", use_screenshot=False, complete=lambda m: "")
    assert not any(p["type"] == "image_url" for p in a2.build_messages(_obs())[1]["content"])


def test_three_misses_gives_up():
    a = MuseSparkAgent("x", complete=lambda m: "I am not sure")
    assert a.next_action(_obs()) == "noop(500)"
    assert a.next_action(_obs()) == "noop(500)"
    assert a.next_action(_obs()).startswith("report_infeasible(")


class FakeEnv:
    def __init__(self):
        self.stepped = []
        self.closed = False

    def reset(self):
        return _obs("https://site/"), {}

    def step(self, action):
        self.stepped.append(action)
        return _obs(f"https://site/step{len(self.stepped)}"), 0, False, False, {}

    def close(self):
        self.closed = True


class FakeAgent:
    def __init__(self, script):
        self.script = iter(script)

    def next_action(self, obs):
        return next(self.script)


def test_runner_runs_to_done_and_calls_on_done(demo):
    env = FakeEnv()
    runner = BrowserJobRunner(
        env_factory=lambda site, goal, headless: env,
        agent_factory=lambda goal, ss: FakeAgent(['click("1")', 'click("2")', 'send_msg_to_user("DONE: placed, $10")']),
    )
    seen = []
    job = runner.run_now("dashdish", "order x", user_id=demo["user_id"])
    assert job.status == "done" and job.result_text == "DONE: placed, $10"
    assert job.steps == 3 and env.stepped == ['click("1")', 'click("2")'] and env.closed
    assert job.final_url == "https://site/step2" and job.seconds >= 0

    job2 = runner.submit("dashdish", "order y", on_done=seen.append)
    runner._queue.join if False else None
    import time
    for _ in range(50):
        if job2.status in ("done", "failed", "infeasible"):
            break
        time.sleep(0.05)
    assert seen and seen[0].id == job2.id
    runner.stop()


def test_runner_step_limit_and_crash():
    runner = BrowserJobRunner(env_factory=lambda s, g, h: FakeEnv(), agent_factory=lambda g, ss: FakeAgent(['click("1")'] * 50))
    job = runner.run_now("dashdish", "x", max_steps=3)
    assert job.status == "failed" and "3 steps" in job.error and job.steps == 3

    def boom(s, g, h):
        raise RuntimeError("no browser")

    job = BrowserJobRunner(env_factory=boom, agent_factory=lambda g, ss: FakeAgent([])).run_now("dashdish", "x")
    assert job.status == "failed" and "no browser" in job.error
