-- How your location appears on generated CVs.
alter table public.user_profile
  add column cv_location text not null default 'full'
  check (cv_location in ('full', 'country', 'remote', 'hidden'));
