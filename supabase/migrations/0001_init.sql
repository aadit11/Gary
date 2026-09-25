-- 0001_init.sql
-- Full schema for Gary. Apply in the Supabase SQL editor (or `supabase db push`).
-- All tables use uuid primary keys and timestamptz created_at. Status-like columns are
-- text with CHECK constraints so they read well in the dashboard.

create extension if not exists "pgcrypto";

create table if not exists users (
  id          uuid primary key default gen_random_uuid(),
  name        text not null,
  phone       text not null unique,            -- E.164, e.g. +14155551234
  address     text not null default '',
  timezone    text not null default 'America/New_York',
  created_at  timestamptz not null default now()
);

create table if not exists family_contacts (
  id            uuid primary key default gen_random_uuid(),
  user_id       uuid not null references users(id) on delete cascade,
  name          text not null,
  phone         text not null,                 -- E.164
  relationship  text not null default '',
  can_approve   boolean not null default true,
  created_at    timestamptz not null default now()
);
create index if not exists family_contacts_user_idx on family_contacts(user_id);
create index if not exists family_contacts_phone_idx on family_contacts(phone);

create table if not exists known_payees (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid not null references users(id) on delete cascade,
  name        text not null,
  kind        text not null default 'biller' check (kind in ('biller','person','merchant')),
  created_at  timestamptz not null default now()
);
create index if not exists known_payees_user_idx on known_payees(user_id);

create table if not exists emails (
  id              uuid primary key default gen_random_uuid(),
  user_id         uuid not null references users(id) on delete cascade,
  gmail_id        text not null unique,
  sender          text not null default '',
  subject         text not null default '',
  snippet         text not null default '',     -- short preview only; never the full body
  received_at     timestamptz,
  classification  text not null default 'other' check (classification in ('bill','appointment','scam','other')),
  extracted       jsonb not null default '{}'::jsonb,   -- payee/amount/due_date or event fields or scam reasons
  created_at      timestamptz not null default now()
);
create index if not exists emails_user_class_idx on emails(user_id, classification);

create table if not exists bills (
  id               uuid primary key default gen_random_uuid(),
  user_id          uuid not null references users(id) on delete cascade,
  payee            text not null,
  amount           numeric(10,2) not null,
  due_date         date,
  status           text not null default 'due' check (status in ('due','paid','cancelled')),
  source_email_id  uuid references emails(id) on delete set null,
  confirmation_id  text,
  paid_at          timestamptz,
  created_at       timestamptz not null default now()
);
create index if not exists bills_user_status_idx on bills(user_id, status);

create table if not exists favorites (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid not null references users(id) on delete cascade,
  label       text not null,                   -- "my usual soup"
  vendor      text not null,
  items       jsonb not null default '[]'::jsonb,
  total       numeric(10,2),
  created_at  timestamptz not null default now()
);

create table if not exists orders (
  id            uuid primary key default gen_random_uuid(),
  user_id       uuid not null references users(id) on delete cascade,
  vendor        text not null,
  items         jsonb not null default '[]'::jsonb,
  total         numeric(10,2) not null,
  status        text not null default 'placed' check (status in ('placed','delivered','cancelled','failed')),
  external_id   text,                           -- mock order_id
  eta_minutes   integer,
  created_at    timestamptz not null default now()
);

create table if not exists service_bookings (
  id            uuid primary key default gen_random_uuid(),
  user_id       uuid not null references users(id) on delete cascade,
  category      text not null,                  -- plumber, electrician, handyman...
  provider      text not null,
  scheduled_at  timestamptz,
  price         numeric(10,2),
  status        text not null default 'booked' check (status in ('booked','completed','cancelled','failed')),
  external_id   text,
  calendar_event_id text,
  created_at    timestamptz not null default now()
);

create table if not exists rides (
  id            uuid primary key default gen_random_uuid(),
  user_id       uuid not null references users(id) on delete cascade,
  pickup        text not null,
  dropoff       text not null,
  pickup_at     timestamptz,
  price         numeric(10,2),
  status        text not null default 'booked' check (status in ('booked','driver_en_route','in_progress','completed','cancelled','failed')),
  external_id   text,
  driver        text,
  car           text,
  plate         text,
  eta_minutes   integer,
  created_at    timestamptz not null default now()
);

create table if not exists reminders (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid not null references users(id) on delete cascade,
  message     text not null,
  time_of_day time not null,                    -- in the user's timezone
  recurrence  text not null default 'daily' check (recurrence in ('once','daily','weekdays','weekly')),
  active      boolean not null default true,
  created_by  uuid references family_contacts(id) on delete set null,
  created_at  timestamptz not null default now()
);

create table if not exists reminder_logs (
  id            uuid primary key default gen_random_uuid(),
  reminder_id   uuid not null references reminders(id) on delete cascade,
  scheduled_for timestamptz not null,
  call_sid      text,
  answered      boolean,
  confirmed     boolean,
  attempt       integer not null default 1,
  family_alerted boolean not null default false,
  created_at    timestamptz not null default now()
);
create index if not exists reminder_logs_reminder_idx on reminder_logs(reminder_id, scheduled_for);

create table if not exists pending_actions (
  id           uuid primary key default gen_random_uuid(),
  user_id      uuid not null references users(id) on delete cascade,
  action_type  text not null,                   -- pay_bill, place_order, book_service, book_ride, pay_person
  payload      jsonb not null default '{}'::jsonb,
  expires_at   timestamptz not null,
  used_at      timestamptz,
  created_at   timestamptz not null default now()
);
create index if not exists pending_actions_user_idx on pending_actions(user_id, expires_at);

create table if not exists approvals (
  id                 uuid primary key default gen_random_uuid(),
  user_id            uuid not null references users(id) on delete cascade,
  family_contact_id  uuid references family_contacts(id) on delete set null,
  action             text not null,
  payload            jsonb not null default '{}'::jsonb,
  reason             text not null default '',
  status             text not null default 'pending' check (status in ('pending','approved','denied','expired')),
  resolved_at        timestamptz,
  created_at         timestamptz not null default now()
);
create index if not exists approvals_contact_status_idx on approvals(family_contact_id, status, created_at desc);

create table if not exists activity_log (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid not null references users(id) on delete cascade,
  kind        text not null,                    -- bill_paid, order_placed, approval_requested, reminder_confirmed...
  summary     text not null,
  data        jsonb not null default '{}'::jsonb,
  created_at  timestamptz not null default now()
);
create index if not exists activity_log_user_time_idx on activity_log(user_id, created_at desc);

create table if not exists calls (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid references users(id) on delete set null,
  direction   text not null check (direction in ('inbound','outbound')),
  reason      text not null default '',         -- inbound, reminder, morning_briefing
  twilio_sid  text unique,
  started_at  timestamptz not null default now(),
  ended_at    timestamptz
);
