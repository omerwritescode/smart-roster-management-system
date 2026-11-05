-- Smart Roster Management System: database schema.
-- Run in the Supabase SQL editor, or with `python -m backend.db.migrate`.
-- Everything operational is data: brands, pods, processes, rules and shifts can
-- all be changed from the app without a code change.

-- ---------------------------------------------------------------- setup
create table pods (
  id text primary key default gen_random_uuid()::text,
  name text not null unique,
  lead_employee_id text,                 -- FK added below (employees references pods)
  created_at timestamptz not null default now()
);

create table employees (
  id text primary key default gen_random_uuid()::text,
  name text not null,
  title text not null default 'Associate',
  pod_id text references pods(id) on delete set null,
  weekly_off_policy text not null default 'solver'
    check (weekly_off_policy in ('solver','fixed','rotating')),
  fixed_off_weekdays int[] not null default '{}',   -- 0 = Monday ... 6 = Sunday
  rotation_weekdays int[] not null default '{}',    -- one weekday per week, cycled
  offs_per_week int not null default 1 check (offs_per_week between 0 and 3),
  max_consecutive_days int not null default 6 check (max_consecutive_days between 1 and 14),
  stretch_limit int not null default 125 check (stretch_limit between 100 and 200), -- % of a day on cover days
  active boolean not null default true,
  created_at timestamptz not null default now()
);
alter table pods
  add constraint pods_lead_fk foreign key (lead_employee_id) references employees(id) on delete set null;

create table brands (
  id text primary key default gen_random_uuid()::text,
  name text not null unique,
  pod_id text references pods(id) on delete set null,
  notes text not null default '',
  active boolean not null default true,
  created_at timestamptz not null default now()
);

create table processes (
  id text primary key default gen_random_uuid()::text,
  code text not null unique,
  name text not null,
  created_at timestamptz not null default now()
);

create table shifts (
  id text primary key default gen_random_uuid()::text,
  name text not null unique,
  start_time time not null,
  end_time time not null,
  created_at timestamptz not null default now()
);

create table public_holidays (
  id text primary key default gen_random_uuid()::text,
  date date not null unique,
  name text not null,
  kind text not null default 'public' check (kind in ('public','company')),
  created_at timestamptz not null default now()
);

create table app_settings (
  key text primary key,
  value jsonb not null
);

-- ---------------------------------------------------------------- brand rules
create table brand_processes (
  id text primary key default gen_random_uuid()::text,
  brand_id text not null references brands(id) on delete cascade,
  process_id text not null references processes(id) on delete restrict,
  calendar_type text not null default 'daily_except_holidays'
    check (calendar_type in ('all_days','daily_except_holidays','sundays_holidays_off','custom')),
  weekday_mask int[] not null default '{0,1,2,3,4,5,6}', -- used when calendar_type = 'custom'
  holidays_closed boolean not null default true,         -- used when calendar_type = 'custom'
  shift_id text not null references shifts(id) on delete restrict,
  active boolean not null default true,
  created_at timestamptz not null default now(),
  unique (brand_id, process_id)
);

-- Most specific rule wins: date, then weekday, then default.
create table coverage_rules (
  id text primary key default gen_random_uuid()::text,
  brand_process_id text not null references brand_processes(id) on delete cascade,
  rule_type text not null check (rule_type in ('default','weekday','date')),
  weekday int check (weekday between 0 and 6),
  date date,
  min_staff int not null check (min_staff between 0 and 50),
  note text not null default '',
  created_at timestamptz not null default now(),
  check (
    (rule_type = 'default' and weekday is null and date is null) or
    (rule_type = 'weekday' and weekday is not null and date is null) or
    (rule_type = 'date' and date is not null and weekday is null)
  )
);
create unique index coverage_default_uq on coverage_rules (brand_process_id) where rule_type = 'default';
create unique index coverage_weekday_uq on coverage_rules (brand_process_id, weekday) where rule_type = 'weekday';
create unique index coverage_date_uq on coverage_rules (brand_process_id, date) where rule_type = 'date';

-- ---------------------------------------------------------------- staffing
create table allocations (
  id text primary key default gen_random_uuid()::text,
  employee_id text not null references employees(id) on delete cascade,
  brand_process_id text not null references brand_processes(id) on delete cascade,
  role text not null default 'primary' check (role in ('primary','secondary','backup')),
  workload_share int not null default 100 check (workload_share between 1 and 200), -- % of a person's day
  effective_from date,
  effective_to date,
  created_at timestamptz not null default now(),
  unique (employee_id, brand_process_id, effective_from),
  check (effective_to is null or effective_from is null or effective_to >= effective_from)
);
create index allocations_bp_idx on allocations (brand_process_id);
create index allocations_emp_idx on allocations (employee_id);

-- ---------------------------------------------------------------- availability
create table leaves (
  id text primary key default gen_random_uuid()::text,
  employee_id text not null references employees(id) on delete cascade,
  leave_type text not null check (leave_type in ('planned','sick','comp_off','unavailable')),
  status text not null default 'pending' check (status in ('pending','approved','rejected')),
  start_date date not null,
  end_date date not null,
  reason text not null default '',
  decided_by text,
  decided_at timestamptz,
  created_at timestamptz not null default now(),
  check (end_date >= start_date)
);
create index leaves_emp_idx on leaves (employee_id, start_date);

create table preferences (
  id text primary key default gen_random_uuid()::text,
  employee_id text not null references employees(id) on delete cascade,
  pref_type text not null check (pref_type in ('off_weekday','off_date','avoid_shift')),
  weekday int check (weekday between 0 and 6),
  date date,
  shift_id text references shifts(id) on delete cascade,
  weight int not null default 3 check (weight between 1 and 5),
  created_at timestamptz not null default now()
);

-- ---------------------------------------------------------------- roster
create table rosters (
  id text primary key default gen_random_uuid()::text,
  month date not null,               -- first day of the month
  version int not null,
  status text not null default 'draft'
    check (status in ('draft','pod_review','ops_review','published','superseded','rejected')),
  plan_label text not null default 'coverage_first',
  parent_id text references rosters(id) on delete set null,
  score numeric,
  metrics jsonb not null default '{}',
  solver jsonb not null default '{}',
  summary text not null default '',
  created_by text not null default 'system',
  created_at timestamptz not null default now(),
  published_at timestamptz,
  unique (month, version)
);

create table roster_days (
  roster_id text not null references rosters(id) on delete cascade,
  employee_id text not null references employees(id) on delete cascade,
  date date not null,
  status text not null
    check (status in ('work','weekly_off','holiday','leave','comp_off','unavailable','idle')),
  source text not null default 'solver' check (source in ('solver','manual','repair')),
  locked boolean not null default false,
  note text not null default '',
  primary key (roster_id, employee_id, date)
);

create table roster_assignments (
  roster_id text not null references rosters(id) on delete cascade,
  employee_id text not null references employees(id) on delete cascade,
  brand_process_id text not null references brand_processes(id) on delete cascade,
  shift_id text not null references shifts(id) on delete restrict,
  date date not null,
  is_cover boolean not null default false,
  share int not null default 100,
  primary key (roster_id, employee_id, brand_process_id, date)
);
create index roster_assignments_date_idx on roster_assignments (roster_id, date);

-- ---------------------------------------------------------------- tracking
create table issues (
  id bigint generated always as identity primary key,
  roster_id text not null references rosters(id) on delete cascade,
  key text not null,
  code text not null,
  severity text not null check (severity in ('blocker','warning','info')),
  category text not null,
  date date,
  employee_id text,
  brand_process_id text,
  brand_id text,
  message text not null,
  suggestion text not null default '',
  facts jsonb not null default '{}',
  unique (roster_id, key)
);

-- Overrides live apart from issues because issues are recomputed by the validator.
create table issue_overrides (
  roster_id text not null references rosters(id) on delete cascade,
  key text not null,
  reason text not null check (length(trim(reason)) >= 5),
  overridden_by text not null,
  overridden_at timestamptz not null default now(),
  primary key (roster_id, key)
);

create table ai_explanations (
  facts_hash text primary key,
  text text not null,
  source text not null check (source in ('gemini','template')),
  model text,
  created_at timestamptz not null default now()
);

create table approvals (
  id bigint generated always as identity primary key,
  roster_id text not null references rosters(id) on delete cascade,
  stage text not null check (stage in ('pod_review','ops_review','publish')),
  pod_id text references pods(id) on delete set null,
  actor text not null,
  decision text not null check (decision in ('submitted','approved','rejected','published')),
  note text not null default '',
  created_at timestamptz not null default now()
);

create table comp_off_ledger (
  id bigint generated always as identity primary key,
  employee_id text not null references employees(id) on delete cascade,
  delta int not null,
  entry_date date not null,
  reason text not null,
  roster_id text references rosters(id) on delete set null,
  leave_id text references leaves(id) on delete set null,
  created_at timestamptz not null default now()
);
create unique index comp_off_earned_uq on comp_off_ledger (employee_id, entry_date) where delta > 0 and roster_id is not null;

create table notifications (
  id bigint generated always as identity primary key,
  roster_id text references rosters(id) on delete cascade,
  employee_id text references employees(id) on delete cascade,
  kind text not null,
  title text not null,
  body text not null default '',
  payload jsonb not null default '{}',
  read_at timestamptz,
  created_at timestamptz not null default now()
);
create index notifications_recent_idx on notifications (created_at desc);

create table audit_log (
  id bigint generated always as identity primary key,
  actor text not null,
  role text not null,
  action text not null,
  entity text not null,
  entity_id text,
  details jsonb not null default '{}',
  created_at timestamptz not null default now()
);
create index audit_recent_idx on audit_log (created_at desc);

-- The browser never talks to the database. Row level security with no policies
-- means Supabase's public API keys cannot read or write these tables; the API
-- connects as the table owner, which bypasses RLS.
do $$
declare t text;
begin
  for t in select tablename from pg_tables where schemaname = 'public' loop
    execute format('alter table public.%I enable row level security', t);
  end loop;
end $$;
