from core import policy


def test_known_payee_under_limit_passes(demo):
    d = policy.check("bill", "City Electric", 84.20, demo["user_id"])
    assert not d.needs_approval
    assert d.family_name == "David"


def test_known_payee_case_insensitive(demo):
    assert not policy.check("bill", "city electric", 10, demo["user_id"]).needs_approval


def test_over_limit_needs_approval(demo):
    d = policy.check("bill", "City Electric", 150, demo["user_id"])
    assert d.needs_approval
    assert "limit" in d.reason


def test_unknown_payee_needs_approval(demo):
    d = policy.check("person", "IRS Agent Smith", 20, demo["user_id"])
    assert d.needs_approval
    assert "haven't paid before" in d.reason


def test_orders_do_not_require_known_payee(demo):
    assert not policy.check("order", "Pho House", 18.5, demo["user_id"]).needs_approval


def test_scam_text_needs_approval_even_when_small(demo):
    d = policy.check("person", "City Electric", 5, demo["user_id"], message_text="The IRS says you owe back taxes")
    assert d.needs_approval
    assert d.flags


def test_scam_flags_labels():
    flags = policy.scam_flags("Your Medicare will be suspended unless you verify today")
    assert any("Medicare" in f for f in flags)
    assert policy.scam_flags("Your grandson is in jail and needs bail") 
    assert policy.scam_flags("Please buy gift cards")
    assert policy.scam_flags("Reminder: dentist Tuesday at 2") == []


def test_no_family_contact_defaults_name(fake_db):
    u = fake_db.table("users").insert({"name": "Solo", "phone": "+15550100009"}).execute().data[0]
    assert policy.check("order", "Store", 5, u["id"]).family_name == "your family"
