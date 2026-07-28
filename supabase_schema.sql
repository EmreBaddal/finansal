-- Aylooper Finans ücretsiz Supabase veritabanı şeması
-- Supabase > SQL Editor > New query alanına tamamını yapıştırıp Run'a basın.

create extension if not exists pgcrypto;

create table if not exists public.watchlist (
  symbol text primary key,
  sort_order integer not null default 9999,
  added_at timestamptz not null default now()
);

create table if not exists public.journal_entries (
  id uuid primary key default gen_random_uuid(),
  symbol text not null,
  title text not null,
  content text not null,
  entry_type text not null default 'Analiz',
  price_at_entry numeric,
  target_price numeric,
  stop_price numeric,
  status text not null default 'Açık',
  tags text[] not null default '{}',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists journal_entries_symbol_created_idx
  on public.journal_entries (symbol, created_at desc);

create table if not exists public.price_alerts (
  id uuid primary key default gen_random_uuid(),
  symbol text not null,
  label text not null default 'Fiyat alarmı',
  target_price numeric not null check (target_price > 0),
  condition text not null check (condition in ('above', 'below')),
  is_active boolean not null default true,
  repeat_mode text not null default 'once' check (repeat_mode in ('once', 'cross')),
  last_checked_price numeric,
  last_triggered_at timestamptz,
  journal_entry_id uuid references public.journal_entries(id) on delete set null,
  notify_ntfy boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists price_alerts_active_symbol_idx
  on public.price_alerts (is_active, symbol);

create table if not exists public.alert_history (
  id uuid primary key default gen_random_uuid(),
  alert_id uuid references public.price_alerts(id) on delete set null,
  symbol text not null,
  label text not null default 'Fiyat alarmı',
  target_price numeric not null,
  triggered_price numeric not null,
  condition text not null,
  triggered_at timestamptz not null default now(),
  notification_status text not null default 'not_sent',
  message text not null default ''
);

create index if not exists alert_history_symbol_triggered_idx
  on public.alert_history (symbol, triggered_at desc);

-- updated_at kolonlarını otomatik güncelle.
create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists journal_entries_set_updated_at on public.journal_entries;
create trigger journal_entries_set_updated_at
before update on public.journal_entries
for each row execute function public.set_updated_at();

drop trigger if exists price_alerts_set_updated_at on public.price_alerts;
create trigger price_alerts_set_updated_at
before update on public.price_alerts
for each row execute function public.set_updated_at();

-- Veriler doğrudan tarayıcıdan değil, Streamlit sunucusundan service role ile erişilir.
-- Bu nedenle RLS açık kalır ve anon kullanıcı için politika tanımlanmaz.
alter table public.watchlist enable row level security;
alter table public.journal_entries enable row level security;
alter table public.price_alerts enable row level security;
alter table public.alert_history enable row level security;
