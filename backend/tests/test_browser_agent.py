import numpy as np

from browser_agent.agent import MuseSparkAgent, parse_action, parse_plan, terminal_message
from browser_agent.flows import FlowStore, name_pattern, step_to_action, to_named_step
from browser_agent.runner import BrowserJobRunner


def _obs(url="https://x/", err=""):
    return {
        "url": url,
        "axtree_object": {"nodes": [
            {"nodeId": "1", "browsergym_id": "1", "role": {"value": "RootWebArea"}, "name": {"value": "Home"}, "childIds": ["2"]},
            {"nodeId": "2", "browsergym_id": "5", "role": {"value": "button"}, "name": {"value": "Checkout $19.10"}, "childIds": []},
        ]},
        "extra_element_properties": {},
        "screenshot": np.zeros((10, 10, 3), dtype=np.uint8),
        "last_action_error": err,
    }


def test_parse_plan_multiline_and_terminal_cut():
    assert parse_plan('x\n```\nclick("1")\n# comment\nclick_named("button", "Checkout.*")\nsend_msg_to_user("DONE: ok")\nclick("9")\n```') == [
        'click("1")', 'click_named("button", "Checkout.*")', 'send_msg_to_user("DONE: ok")']
    assert parse_action('thinking\n```click("12")```') == 'click("12")'
    assert parse_plan("no code here") == []


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
    assert "Order soup" in text and "Accessibility Tree" in text and "Action Space" in text and "click_named" in text
    assert 'click("5")' in text and 'button "Checkout $19.10"' in text and "boom" in text
    assert any(p["type"] == "image_url" for p in msgs[1]["content"])
    a2 = MuseSparkAgent("x", use_screenshot=False, complete=lambda m: "")
    assert not any(p["type"] == "image_url" for p in a2.build_messages(_obs())[1]["content"])


def test_three_misses_gives_up():
    a = MuseSparkAgent("x", complete=lambda m: "I am not sure")
    assert a.next_plan(_obs()) == ["noop(500)"]
    assert a.next_plan(_obs()) == ["noop(500)"]
    assert a.next_plan(_obs())[0].startswith("report_infeasible(")


def test_name_pattern_wildcards_numbers():
    import re
    pat = name_pattern("Checkout $19.10")
    assert re.search(pat, "Checkout $23.37", re.I)
    assert not re.search(pat, "Place Order $23.37", re.I)
    assert re.search(name_pattern("Add to cart $13.11"), "Add to cart $14.00")
    assert name_pattern("") == ""


def test_named_steps_roundtrip():
    s = to_named_step('fill("55", "Souvla")', "textbox", "Search Dashdish")
    assert s == {"action": "fill", "role": "textbox", "name": "Search\\ Dashdish", "value": "Souvla"}
    assert step_to_action(s) == "fill_named('textbox', 'Search\\\\ Dashdish', 'Souvla')"
    c = to_named_step('click("5")', "button", "Checkout $19.10")
    assert step_to_action(c).startswith("click_named('button'")
    assert to_named_step('click_named("button", "^Place Order")', "", "") == {"action": "click", "role": "button", "name": "^Place Order"}
    assert to_named_step("noop()", "", "") is None
    assert to_named_step('click("5")', "", "") is None


def test_flow_store(tmp_path):
    fs = FlowStore(tmp_path)
    assert fs.load("dashdish", "usual") is None
    fs.save("dashdish", "My Usual!", "goal", [{"action": "click", "role": "button", "name": "x"}], "DONE")
    assert fs.load("dashdish", "my-usual")["steps"][0]["role"] == "button"


class FakeEnv:
    def __init__(self, fail_on=None):
        self.stepped = []
        self.closed = False
        self.fail_on = fail_on or set()

    def reset(self):
        return _obs("https://site/"), {}

    def step(self, action):
        self.stepped.append(action)
        err = "boom" if any(f in action for f in self.fail_on) else ""
        return _obs(f"https://site/step{len(self.stepped)}", err), 0, False, False, {}

    def close(self):
        self.closed = True


class FakeAgent:
    def __init__(self, plans):
        self.plans = iter(plans)
        self.action_history = []
        self.model_calls = 0
        self.last_reply = ""

    def next_plan(self, obs):
        self.model_calls += 1
        return next(self.plans)

    def record(self, action, obs, reason=""):
        self.action_history.append(action)

    def note(self, text):
        self.action_history.append(text)


def test_runner_executes_plans_and_replans_on_failure(demo, tmp_path):
    env = FakeEnv(fail_on={"click(\"2\")"})
    runner = BrowserJobRunner(
        env_factory=lambda site, goal, headless: env,
        agent_factory=lambda goal, ss: FakeAgent([
            ['click("1")', 'click("2")', 'click("3")'],           # 2 fails -> re-plan, 3 never runs
            ['click_named("button", "Checkout.*")', 'send_msg_to_user("DONE: placed, $10")'],
        ]),
        flow_store=FlowStore(tmp_path),
    )
    job = runner.run_now("dashdish", "order x", user_id=demo["user_id"])
    assert job.status == "done" and job.result_text == "DONE: placed, $10"
    assert env.stepped == ['click("1")', 'click("2")', 'click_named("button", "Checkout.*")']
    assert job.steps == 3 and job.model_calls == 2 and env.closed


def test_runner_learns_and_replays_flow(demo, tmp_path):
    fs = FlowStore(tmp_path)
    env1 = FakeEnv()
    r1 = BrowserJobRunner(env_factory=lambda s, g, h: env1,
                          agent_factory=lambda g, ss: FakeAgent([['click("5")', 'send_msg_to_user("DONE: ok")']]), flow_store=fs)
    job1 = r1.run_now("dashdish", "order", flow_key="usual")
    assert job1.ok and fs.load("dashdish", "usual")["steps"] == [{"action": "click", "role": "button", "name": "Checkout\\ .*"}]

    env2 = FakeEnv()
    r2 = BrowserJobRunner(env_factory=lambda s, g, h: env2,
                          agent_factory=lambda g, ss: FakeAgent([['send_msg_to_user("DONE: again")']]), flow_store=fs)
    job2 = r2.run_now("dashdish", "order", flow_key="usual")
    assert job2.ok and job2.replayed_steps == 1 and job2.model_calls == 1
    assert env2.stepped == ["click_named('button', 'Checkout\\\\ .*')"]

    env3 = FakeEnv(fail_on={"click_named"})
    r3 = BrowserJobRunner(env_factory=lambda s, g, h: env3,
                          agent_factory=lambda g, ss: FakeAgent([['click("5")', 'send_msg_to_user("DONE: recovered")']]), flow_store=fs)
    job3 = r3.run_now("dashdish", "order", flow_key="usual")
    assert job3.ok and job3.replayed_steps == 0 and job3.result_text == "DONE: recovered"


def test_runner_step_limit_and_crash():
    runner = BrowserJobRunner(env_factory=lambda s, g, h: FakeEnv(), agent_factory=lambda g, ss: FakeAgent([['click("1")']] * 50))
    job = runner.run_now("dashdish", "x", max_steps=3)
    assert job.status == "failed" and "3 steps" in job.error and job.steps == 3

    def boom(s, g, h):
        raise RuntimeError("no browser")

    job = BrowserJobRunner(env_factory=boom, agent_factory=lambda g, ss: FakeAgent([])).run_now("dashdish", "x")
    assert job.status == "failed" and "no browser" in job.error


def test_compress_executed_collapses_navigation_prefix():
    from browser_agent.flows import compress_executed
    ex = [
        {"action": 'fill("55", "Souvla")', "role": "textbox", "name": "Search", "ok": True, "url_before": "https://s/", "url_after": "https://s/"},
        {"action": 'press("55", "Enter")', "role": "textbox", "name": "Search", "ok": True, "url_before": "https://s/", "url_after": "https://s/search?q=Souvla"},
        {"action": 'click("972")', "role": "image", "name": "Image Souvla", "ok": True, "url_before": "https://s/search?q=Souvla", "url_after": "https://s/store/1"},
        {"action": "scroll(0, 600)", "role": "", "name": "", "ok": True, "url_before": "https://s/store/1", "url_after": "https://s/store/1"},
        {"action": 'click("355")', "role": "button", "name": "Add", "ok": True, "url_before": "https://s/store/1", "url_after": "https://s/store/1"},
        {"action": 'click_named("button", "Checkout.*")', "role": "", "name": "", "ok": False, "url_before": "https://s/store/1", "url_after": "https://s/store/1"},
        {"action": 'click_named("button", "^Place Order")', "role": "", "name": "", "ok": True, "url_before": "https://s/store/1", "url_after": "https://s/checkout"},
        {"action": "noop()", "role": "", "name": "", "ok": True, "url_before": "https://s/checkout", "url_after": "https://s/checkout"},
    ]
    steps, complete = compress_executed(ex)
    assert complete
    assert steps == [
        {"action": "goto", "args": ["https://s/store/1"]},
        {"action": "click", "role": "button", "name": "Add"},
        {"action": "click", "role": "button", "name": "^Place Order"},
    ]
