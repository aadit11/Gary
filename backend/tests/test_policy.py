from core import policy


def test_known_payee_under_limit_passes(demo):
    d = policy.check("bill", "City Electric", 84.20, demo["user_id"])
    assert not d.needs_approval
    assert d.recurring
    assert d.family_name == "David"


def test_known_payee_case_insensitive(demo):
    assert not policy.check("bill", "city electric", 10, demo["user_id"]).needs_approval


def test_over_limit_needs_approval(demo):
    d = policy.check("bill", "City Electric", 150, demo["user_id"])
    assert d.needs_approval
    assert "limit" in d.reason


def test_unknown_payee_needs_approval(demo):
    d = policy.check("person", "Aunt Rose", 10, demo["user_id"])
    assert d.needs_approval
    assert "haven't paid before" in d.reason


def test_scam_word_in_payee_name_is_flagged(demo):
    d = policy.check("person", "IRS Agent Smith", 20, demo["user_id"])
    assert d.needs_approval
    assert "tax agency" in d.reason
    assert d.flags


def test_orders_do_not_require_known_payee(demo):
    assert not policy.check("order", "Pho House", 18.5, demo["user_id"]).needs_approval


def test_orders_not_subject_to_hard_limit(demo):
    assert not policy.check("order", "Pho House", 45, demo["user_id"]).needs_approval


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


# --- hard limit and recurring ------------------------------------------------------------


def _add_known_person(fake_db, user_id, name):
    fake_db.table("known_payees").insert({"user_id": user_id, "name": name, "kind": "person"}).execute()


def test_known_person_over_hard_limit_needs_approval(demo, fake_db):
    _add_known_person(fake_db, demo["user_id"], "Sarah")
    d = policy.check("person", "Sarah", 25, demo["user_id"])
    assert d.needs_approval
    assert "one-time payment over your $20 limit" in d.reason
    assert not d.recurring


def test_known_person_under_hard_limit_passes(demo, fake_db):
    _add_known_person(fake_db, demo["user_id"], "Sarah")
    assert not policy.check("person", "Sarah", 15, demo["user_id"]).needs_approval


def test_known_biller_without_history_is_recurring(demo):
    assert policy.is_recurring_bill(demo["user_id"], "Sunrise Pharmacy", 23.50)


def test_recurring_within_tolerance_of_history(demo, fake_db):
    fake_db.table("bills").insert(
        {"user_id": demo["user_id"], "payee": "City Electric", "amount": 80.00, "status": "paid"}
    ).execute()
    d = policy.check("bill", "City Electric", 90.00, demo["user_id"])
    assert not d.needs_approval and d.recurring


def test_anomalous_amount_from_known_biller_needs_approval(demo, fake_db):
    fake_db.table("bills").insert(
        {"user_id": demo["user_id"], "payee": "City Electric", "amount": 40.00, "status": "paid"}
    ).execute()
    d = policy.check("bill", "City Electric", 84.20, demo["user_id"])
    assert d.needs_approval
    assert not d.recurring
    assert "$20 limit" in d.reason


def test_anomalous_but_small_bill_passes(demo, fake_db):
    fake_db.table("bills").insert(
        {"user_id": demo["user_id"], "payee": "Sunrise Pharmacy", "amount": 5.00, "status": "paid"}
    ).execute()
    assert not policy.check("bill", "Sunrise Pharmacy", 12.00, demo["user_id"]).needs_approval


def test_known_person_payee_is_not_a_recurring_bill(demo, fake_db):
    _add_known_person(fake_db, demo["user_id"], "Sarah")
    assert not policy.is_recurring_bill(demo["user_id"], "Sarah", 10)


def test_per_user_hard_limit_overrides_default(demo, fake_db):
    _add_known_person(fake_db, demo["user_id"], "Sarah")
    fake_db.table("users").update({"hard_limit": 50}).eq("id", demo["user_id"]).execute()
    assert policy.hard_limit_for(demo["user_id"]) == 50
    assert not policy.check("person", "Sarah", 40, demo["user_id"]).needs_approval
    d = policy.check("person", "Sarah", 60, demo["user_id"])
    assert d.needs_approval and "$50 limit" in d.reason


def test_hard_limit_defaults_from_settings(demo, monkeypatch):
    monkeypatch.setattr(policy.settings, "policy_hard_limit", 35.0)
    assert policy.hard_limit_for(demo["user_id"]) == 35.0
