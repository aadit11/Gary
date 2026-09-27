-- 0002_user_hard_limit.sql
-- Per-user hard limit for one-off (non-recurring) payments. NULL means use POLICY_HARD_LIMIT.
-- Apply in the Supabase SQL editor after 0001_init.sql.

alter table users add column if not exists hard_limit numeric(10,2)
  check (hard_limit is null or hard_limit >= 0);
