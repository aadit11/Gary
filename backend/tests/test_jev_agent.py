import json

from browser_agent.jev_agent import JevAgent, element_table


def _obs():
    return {
        "url": "https://s/",
        "axtree_object": {"nodes": [
            {"browsergym_id": "1", "role": {"value": "RootWebArea"}, "name": {"value": "Home"}},
            {"browsergym_id": "55", "role": {"value": "textbox"}, "name": {"value": "Search Dashdish"}, "value": {"value": ""}},
            {"browsergym_id": "60", "role": {"value": "combobox"}, "name": {"value": "City"}},
            {"browsergym_id": "974", "role": {"value": "heading"}, "name": {"value": "Wingstop"}},
            {"browsergym_id": "355", "role": {"value": "button"}, "name": {"value": "Add"}},
            {"browsergym_id": "356", "role": {"value": "button"}, "name": {"value": ""}},   # unlabeled: dropped
            {"browsergym_id": "700", "role": {"value": "StaticText"}, "name": {"value": "$12.96"}},
        ]},
        "extra_element_properties": {},
        "last_action_error": "",
    }


def test_element_table_keeps_labelled_interactive_only():
    bids = [e["bid"] for e in element_table(_obs())]
    assert bids == ["55", "60", "974", "355"]


def _agent(answers, lookup=False):
    calls = []
    def post(url, key, body):
        calls.append(body)
        return {"answers": answers, "model": "jev-test"}
    a = JevAgent("Look up Wingstop on DoorDash.", lookup=lookup, restaurant="Wingstop", post=post,
                 text_fn=lambda goal, field, page: "Wingstop", done_fn=lambda goal, page: "DONE: Ordered wings, $12.96")
    return a, calls


def test_click_and_type_and_enter_mapping():
    a, calls = _agent({"operation": {"choice": "TYPE_TEXT", "probabilities": {"TYPE_TEXT": 0.9, "CLICK": 0.1}},
                       "type_text_target": {"choice": "55"}, "click_target": {"choice": "974"}})
    assert a.next_plan(_obs()) == ['fill("55", "Wingstop")']
    assert "operation" in calls[0]["questions"] and "click_target" in calls[0]["questions"] and "type_text_target" in calls[0]["questions"]
    assert calls[0]["state"]["elements"][0]["label"] == "Search Dashdish"
    a, _ = _agent({"operation": {"choice": "PRESS_ENTER", "probabilities": {}}, "press_enter_target": {"choice": "55"}})
    assert a.next_plan(_obs()) == ['press("55", "Enter")']
    a, _ = _agent({"operation": {"choice": "CLICK", "probabilities": {}}, "click_target": {"choice": "974"}})
    assert a.next_plan(_obs()) == ['click("974")']


def test_lookup_done_ops_and_order_done():
    a, calls = _agent({"operation": {"choice": "DONE_OPEN", "probabilities": {}}}, lookup=True)
    assert a.next_plan(_obs()) == ['send_msg_to_user("DONE: OPEN. Wingstop can take a delivery order.")']
    assert "DONE_OPEN" in calls[0]["questions"]["operation"]["criteria"] and "DONE" not in calls[0]["questions"]["operation"]["criteria"]
    a, _ = _agent({"operation": {"choice": "DONE", "probabilities": {}}})
    assert json.loads(a.next_plan(_obs())[0][len("send_msg_to_user("):-1]) == "DONE: Ordered wings, $12.96"


def test_anti_loop_takes_runner_up():
    a, _ = _agent({"operation": {"choice": "SCROLL_DOWN", "probabilities": {"SCROLL_DOWN": 0.6, "CLICK": 0.4}}, "click_target": {"choice": "355"}})
    for _ in range(2):
        act = a.next_plan(_obs())[0]; a.record(act, _obs())
    assert a.next_plan(_obs()) == ['click("355")']


def test_request_failure_is_graceful():
    def boom(url, key, body): raise RuntimeError("down")
    a = JevAgent("x", post=boom, text_fn=lambda *_: "", done_fn=lambda *_: "")
    assert a.next_plan(_obs()) == ["noop(800)"]
    a.next_plan(_obs())
    assert a.next_plan(_obs())[0].startswith("report_infeasible")
