"""Pydantic models for the tables core/ reads. Fields mirror supabase/migrations/0001_init.sql."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class User(BaseModel):
    id: str
    name: str
    phone: str
    address: str = ""
    timezone: str = "America/New_York"


class FamilyContact(BaseModel):
    id: str
    user_id: str
    name: str
    phone: str
    relationship: str = ""
    can_approve: bool = True


class KnownPayee(BaseModel):
    id: str
    user_id: str
    name: str
    kind: Literal["biller", "person", "merchant"] = "biller"


class Email(BaseModel):
    id: str
    user_id: str
    gmail_id: str
    sender: str = ""
    subject: str = ""
    snippet: str = ""
    received_at: datetime | None = None
    classification: Literal["bill", "appointment", "scam", "other"] = "other"
    extracted: dict[str, Any] = Field(default_factory=dict)


class Bill(BaseModel):
    id: str
    user_id: str
    payee: str
    amount: float
    due_date: date | None = None
    status: Literal["due", "paid", "cancelled"] = "due"
    source_email_id: str | None = None
    confirmation_id: str | None = None


class PendingAction(BaseModel):
    id: str
    user_id: str
    action_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    expires_at: datetime
    used_at: datetime | None = None


class Approval(BaseModel):
    id: str
    user_id: str
    family_contact_id: str | None = None
    action: str
    payload: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""
    status: Literal["pending", "approved", "denied", "expired"] = "pending"
    resolved_at: datetime | None = None


class ActivityEvent(BaseModel):
    id: str
    user_id: str
    kind: str
    summary: str
    data: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None
