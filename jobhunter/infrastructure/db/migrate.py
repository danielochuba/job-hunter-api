"""Apply supabase/migrations/*.sql to a plain (non-Supabase) Postgres, e.g. the local Docker one.

The migrations are written for Supabase, so a few stand-ins are created first: an `extensions`
schema (pgvector lives there), a minimal `auth.users` and `storage.buckets`. The user_profile ->
auth.users foreign key is dropped afterwards, since there is no sign-in in LOCAL_MODE. Applied
files are recorded in public.schema_migrations, so re-running only applies new ones."""
from pathlib import Path

from .connection import connect

MIGRATIONS_DIR = Path(__file__).resolve().parents[3] / "supabase" / "migrations"
SHIM_MARK = "jobhunter-local-shim"

SHIM = f"""
create schema if not exists extensions;
create schema if not exists auth;
comment on schema auth is '{SHIM_MARK}';
create table if not exists auth.users (id uuid primary key);
create schema if not exists storage;
create table if not exists storage.buckets (id text primary key, name text, public boolean);
create table if not exists public.schema_migrations (
  version    text primary key,
  applied_at timestamptz not null default now()
);
"""


def _check_plain_postgres(conn):
    row = conn.execute("SELECT obj_description(oid, 'pg_namespace') AS mark FROM pg_namespace "
                       "WHERE nspname = 'auth'").fetchone()
    if row and row["mark"] != SHIM_MARK:
        raise RuntimeError("This database looks like a real Supabase project (it has its own auth schema). "
                           "Use `npx supabase db push` there instead.")


def migrate(database_url, migrations_dir=MIGRATIONS_DIR, log=print):
    files = sorted(Path(migrations_dir).glob("*.sql"))
    if not files:
        raise RuntimeError(f"No migrations found in {migrations_dir}")
    with connect(database_url) as conn:
        _check_plain_postgres(conn)
        conn.execute(SHIM)
        # Supabase puts `extensions` on the search path; queries rely on that for `::vector`.
        db = conn.execute("SELECT current_database() AS db").fetchone()["db"]
        conn.execute(f'ALTER DATABASE "{db}" SET search_path TO public, extensions')
        conn.execute("SET search_path TO public, extensions")
        done = {r["version"] for r in conn.execute("SELECT version FROM public.schema_migrations")}
        applied = 0
        for f in files:
            version = f.stem
            if version in done:
                continue
            log(f"applying {f.name}")
            with conn.transaction():
                conn.execute(f.read_text(encoding="utf-8"))
                conn.execute("INSERT INTO public.schema_migrations (version) VALUES (%s)", (version,))
            applied += 1
        conn.execute("ALTER TABLE IF EXISTS public.user_profile DROP CONSTRAINT IF EXISTS user_profile_id_fkey")
    log(f"{applied} migration(s) applied, {len(files) - applied} already up to date")
    return applied
