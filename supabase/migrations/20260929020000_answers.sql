-- Custom written answers for application forms ("Message to the recruiter", "Why us?", ...).
create table public.answers (
  id         bigint generated always as identity primary key,
  job_id     bigint not null references public.jobs (id) on delete cascade,
  question   text not null,
  max_words  integer not null default 150,
  tone       text not null default 'direct',
  emphasis   text,
  answer     text not null,
  evidence   jsonb not null default '[]',   -- CV bullet ids the answer draws on
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index answers_job_idx on public.answers (job_id, created_at desc);
create trigger answers_updated before update on public.answers
  for each row execute function public.set_updated_at();
alter table public.answers enable row level security;
