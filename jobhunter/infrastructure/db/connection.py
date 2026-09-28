"""Postgres (Supabase) connections via psycopg 3.

Autocommit: every statement is durable immediately, so runs can be polled while in progress.
`prepare_threshold=None` keeps Supabase's transaction pooler (port 6543) happy."""
import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

CONNECT_KWARGS = {"row_factory": dict_row, "autocommit": True, "prepare_threshold": None}


def connect(url):
    return psycopg.connect(url, **CONNECT_KWARGS)


def pool(url, min_size=1, max_size=6):
    return ConnectionPool(url, kwargs=CONNECT_KWARGS, min_size=min_size, max_size=max_size, open=True,
                          name="jobhunter")
