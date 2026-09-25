from config import settings
from voice import twilio_routes


def test_stream_url_swaps_scheme(monkeypatch):
    monkeypatch.setattr(settings, "public_base_url", "https://abc.ngrok-free.dev/")
    assert twilio_routes.stream_url() == "wss://abc.ngrok-free.dev/voice/stream"


def test_twiml_has_stream_and_parameters(monkeypatch):
    monkeypatch.setattr(settings, "public_base_url", "https://abc.ngrok-free.dev")
    xml = twilio_routes.twiml_stream({"user_id": "u1", "reason": "reminder", "reminder_text": "Take your <pill> & rest"}).body.decode()
    assert '<Connect><Stream url="wss://abc.ngrok-free.dev/voice/stream">' in xml
    assert '<Parameter name="user_id" value="u1"/>' in xml
    assert "&lt;pill&gt; &amp; rest" in xml


def test_agent_settings_shape():
    from voice import agent_settings

    s = agent_settings.build_settings([{"name": "f", "description": "d", "parameters": {"type": "object", "properties": {}, "required": []}}], "prompt", "hi")
    assert s["type"] == "Settings"
    assert s["audio"]["input"] == {"encoding": "mulaw", "sample_rate": 8000}
    assert s["audio"]["output"]["container"] == "none"
    assert s["agent"]["listen"]["provider"]["model"].startswith("flux")
    assert s["agent"]["think"]["functions"][0]["name"] == "f"
    assert s["agent"]["greeting"] == "hi"


def test_prompts_render():
    from voice import agent_settings

    p = agent_settings.load_prompt("reminder", user_name="Margaret", reminder_text="take your pills")
    assert "Margaret" in p and "take your pills" in p and "{" not in p
    assert "{" not in agent_settings.load_prompt("inbound", user_name="Margaret")
    assert agent_settings.servers_for("reminder") == ["checkins"]
