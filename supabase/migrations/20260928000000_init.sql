-- JobHunter schema. Only the FastAPI backend (service role / direct Postgres) touches these
-- tables. RLS is enabled everywhere with no policies: defence in depth, nothing is public.

create extension if not exists vector with schema extensions;

create or replace function public.set_updated_at() returns trigger
language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end $$;

-- ---------------------------------------------------------------- user & CVs
create table public.user_profile (
  id                  uuid primary key references auth.users (id) on delete cascade,
  first_name          text not null default '',
  last_name           text not null default '',
  full_name           text generated always as (trim(first_name || ' ' || last_name)) stored,
  preferred_name      text,
  pronouns            text,
  avatar_path         text,
  headline            text,
  bio                 text,
  email               text not null,
  phone               text,
  phone_country_code  text,
  city                text,
  state_region        text,
  country             text,
  timezone            text,
  linkedin_url        text,
  github_url          text,
  portfolio_url       text,
  other_links         jsonb not null default '[]',   -- [{label, url}]
  years_experience    numeric(4, 1),
  languages           jsonb not null default '[]',   -- [{language, proficiency}]
  target_roles        text[] not null default '{}',
  seniority           text,
  employment_types    text[] not null default '{}',
  needs_sponsorship   boolean not null default false,
  work_authorizations text[] not null default '{}',  -- countries/regions you can already work in
  acceptable_regions  text[] not null default '{}',
  remote_only         boolean not null default false,
  willing_to_relocate boolean not null default false,
  min_salary          integer,
  salary_currency     text,
  notice_period       text,
  email_signature     text,
  onboarded           boolean not null default false,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now()
);
create trigger user_profile_updated before update on public.user_profile
  for each row execute function public.set_updated_at();

create table public.cvs (
  id          bigint generated always as identity primary key,
  user_id     uuid not null references public.user_profile (id) on delete cascade,
  name        text not null,
  is_default  boolean not null default false,
  cv          jsonb not null,          -- master CV (Phase 1 YAML shape, minus contact block)
  raw_text    text,
  source_file text,                    -- storage path of the uploaded original
  embedding   vector(1536),
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);
create unique index cvs_one_default on public.cvs (user_id) where is_default;
create trigger cvs_updated before update on public.cvs
  for each row execute function public.set_updated_at();

-- ---------------------------------------------------------------- settings & sources
create table public.settings (
  id                 smallint primary key default 1 check (id = 1),
  filters            jsonb not null default '{"title_include": [], "title_exclude": [], "locations": []}',
  search_queries     text[] not null default '{}',
  aggregators        text[] not null default
    '{remotive,remoteok,arbeitnow,himalayas,jobicy,weworkremotely,hn_whoishiring}',
  matching           jsonb not null default
    '{"similarity_threshold": 0.25, "score_limit": 30, "min_fit_for_generate": 70, "alert_min_fit": 80}',
  schedule           jsonb not null default '{"enabled": true, "time": "07:30", "auto_match": true}',
  followup_days      integer not null default 7,
  monthly_budget_usd numeric(8, 2) not null default 20,
  updated_at         timestamptz not null default now()
);
insert into public.settings (id) values (1);
create trigger settings_updated before update on public.settings
  for each row execute function public.set_updated_at();

create table public.companies (
  id         bigint generated always as identity primary key,
  source     text not null check (source in ('greenhouse', 'lever', 'ashby', 'workable', 'smartrecruiters', 'recruitee')),
  token      text not null,
  name       text,
  domain     text,
  active     boolean not null default true,
  created_at timestamptz not null default now(),
  unique (source, token)
);

-- ---------------------------------------------------------------- jobs
create table public.jobs (
  id                bigint generated always as identity primary key,
  key               text not null unique,          -- source:company:external_id
  fingerprint       text,                          -- normalised company+title, cross-source dedup
  source            text not null,
  company           text not null default '',
  company_domain    text,
  title             text not null default '',
  location          text not null default '',
  url               text,
  description       text not null default '',
  posted_at         timestamptz,
  fetched_at        timestamptz not null default now(),
  remote_policy     text,                          -- remote | hybrid | onsite | unknown
  visa_sponsorship  text,                          -- yes | no | unknown
  salary            text,
  embedding         vector(1536),
  similarity        real,
  cv_id             bigint references public.cvs (id) on delete set null,
  fit_score         integer,
  fit               jsonb,
  stage             text not null default 'new' check (stage in (
                      'new', 'filtered_out', 'ineligible', 'scored', 'generated', 'approved',
                      'rejected', 'applied', 'interviewing', 'offer', 'closed')),
  feedback          text check (feedback in ('up', 'down')),
  feedback_reason   text,
  notes             text,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now()
);
create index jobs_stage_idx on public.jobs (stage);
create index jobs_fit_idx on public.jobs (fit_score desc nulls last);
create index jobs_fingerprint_idx on public.jobs (fingerprint);
create index jobs_fetched_idx on public.jobs (fetched_at desc);
create trigger jobs_updated before update on public.jobs
  for each row execute function public.set_updated_at();

-- ---------------------------------------------------------------- generated documents
create table public.applications (
  id                bigint generated always as identity primary key,
  job_id            bigint not null references public.jobs (id) on delete cascade,
  cv_id             bigint references public.cvs (id) on delete set null,
  version           integer not null,
  result            jsonb not null,               -- validated generation output (editable)
  warnings          jsonb not null default '[]',
  cover_letter      text not null default '',
  cv_html_path      text,
  cv_pdf_path       text,
  cover_letter_path text,
  created_at        timestamptz not null default now(),
  unique (job_id, version)
);

-- ---------------------------------------------------------------- contacts & outreach
create table public.contacts (
  id             bigint generated always as identity primary key,
  job_id         bigint references public.jobs (id) on delete cascade,
  company_domain text,
  name           text,
  role           text,
  email          text not null,
  source         text not null check (source in ('job_post', 'hunter', 'website', 'pattern', 'manual')),
  confidence     integer not null default 50,
  created_at     timestamptz not null default now(),
  unique (job_id, email)
);

create table public.outreach (
  id               bigint generated always as identity primary key,
  job_id           bigint not null references public.jobs (id) on delete cascade,
  contact_id       bigint references public.contacts (id) on delete set null,
  to_email         text not null,
  subject          text not null default '',
  body             text not null default '',
  attach_cv        boolean not null default true,
  status           text not null default 'draft' check (status in ('draft', 'sent', 'replied', 'skipped')),
  gmail_thread_id  text,
  gmail_message_id text,
  sent_at          timestamptz,
  replied_at       timestamptz,
  reply_snippet    text,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now()
);
create trigger outreach_updated before update on public.outreach
  for each row execute function public.set_updated_at();

-- ---------------------------------------------------------------- tracker
create table public.events (
  id     bigint generated always as identity primary key,
  job_id bigint not null references public.jobs (id) on delete cascade,
  kind   text not null check (kind in ('stage_change', 'note', 'email_sent', 'reply', 'reminder_done', 'generated')),
  note   text,
  at     timestamptz not null default now()
);
create index events_job_idx on public.events (job_id, at desc);

create table public.reminders (
  id         bigint generated always as identity primary key,
  job_id     bigint references public.jobs (id) on delete cascade,
  due_at     timestamptz not null,
  note       text not null default '',
  done       boolean not null default false,
  auto       boolean not null default false,
  notified   boolean not null default false,
  created_at timestamptz not null default now()
);
create index reminders_due_idx on public.reminders (done, due_at);

create table public.prep (
  id         bigint generated always as identity primary key,
  job_id     bigint not null references public.jobs (id) on delete cascade,
  content    jsonb not null,
  created_at timestamptz not null default now()
);

-- ---------------------------------------------------------------- system
create table public.notifications (
  id         bigint generated always as identity primary key,
  kind       text not null,
  title      text not null,
  body       text not null default '',
  job_id     bigint references public.jobs (id) on delete cascade,
  read       boolean not null default false,
  created_at timestamptz not null default now()
);
create index notifications_unread_idx on public.notifications (read, created_at desc);

create table public.integrations (
  provider      text primary key,                -- 'gmail'
  email         text,
  token         jsonb,                           -- OAuth credentials; never leaves the API
  pending_state text,
  updated_at    timestamptz not null default now()
);

create table public.runs (
  id          bigint generated always as identity primary key,
  kind        text not null,
  status      text not null default 'queued' check (status in ('queued', 'running', 'succeeded', 'failed')),
  params      jsonb not null default '{}',
  progress    jsonb not null default '{"done": 0, "total": 0}',
  result      jsonb,
  log         text[] not null default '{}',
  error       text,
  trigger     text not null default 'api',         -- api | cli | schedule
  started_at  timestamptz not null default now(),
  finished_at timestamptz
);
create index runs_started_idx on public.runs (started_at desc);

create table public.llm_usage (
  id            bigint generated always as identity primary key,
  run_id        bigint references public.runs (id) on delete set null,
  purpose       text not null,
  model         text not null,
  input_tokens  integer not null default 0,
  output_tokens integer not null default 0,
  cost_usd      numeric(12, 6) not null default 0,
  at            timestamptz not null default now()
);
create index llm_usage_at_idx on public.llm_usage (at desc);

-- ---------------------------------------------------------------- RLS: on, no policies
do $$
declare t text;
begin
  foreach t in array array['user_profile', 'cvs', 'settings', 'companies', 'jobs', 'applications',
    'contacts', 'outreach', 'events', 'reminders', 'prep', 'notifications', 'integrations', 'runs',
    'llm_usage']
  loop
    execute format('alter table public.%I enable row level security', t);
  end loop;
end $$;

-- ---------------------------------------------------------------- storage
insert into storage.buckets (id, name, public)
values ('applications', 'applications', false)
on conflict (id) do nothing;
