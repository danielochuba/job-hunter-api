-- More job sources + lead cache.

-- Posts/search results already examined (so the LLM never re-reads the same Reddit post or web page).
create table public.lead_cache (
  key  text primary key,
  jobs integer not null default 0,        -- how many job postings were extracted from it
  at   timestamptz not null default now()
);
alter table public.lead_cache enable row level security;

-- Enable the new sources (keyed ones are skipped automatically until their API key is set).
alter table public.settings alter column aggregators set default
  '{remotive,remoteok,arbeitnow,himalayas,jobicy,weworkremotely,hn_whoishiring,workingnomads,adzuna,google_jobs,reddit,web_search}';

update public.settings
set aggregators = aggregators || array(
  select s from unnest('{workingnomads,adzuna,google_jobs,reddit,web_search}'::text[]) s
  where s <> all (aggregators))
where id = 1;
