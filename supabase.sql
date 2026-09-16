-- Run once in your own Supabase SQL editor. No public table access.
create table if not exists public.basis_records (
    kind text not null,
    id text not null,
    created_at timestamptz not null default now(),
    payload jsonb not null,
    primary key (kind, id)
);
alter table public.basis_records enable row level security;
revoke all on public.basis_records from anon, authenticated;
grant select, insert on public.basis_records to service_role;
revoke update, delete on public.basis_records from service_role;
-- Deliberately no anonymous/authenticated RLS policies. Only the app's
-- server-side service key may read/append. Application records are immutable.
