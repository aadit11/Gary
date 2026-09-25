import json

from mcp_servers.money import list_bills_due


def test_list_bills_due_reads_seeded_bills(demo):
    out = json.loads(list_bills_due(demo["user_id"]))
    assert "$84.20" in out["say"] and "City Electric" in out["say"]
    assert "Friday, October 2" in out["say"]
    assert len(out["data"]["bills"]) == 2
    assert "{" not in out["say"]


def test_list_bills_due_none(fake_db):
    u = fake_db.table("users").insert({"name": "Nobody", "phone": "+15550100010"}).execute().data[0]
    out = json.loads(list_bills_due(u["id"]))
    assert "don't have any bills" in out["say"]
