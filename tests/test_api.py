"""HTTP interface: auth on every route but /health, domain errors mapped to status codes."""
import time
from contextlib import contextmanager

import jwt
import pytest
from fastapi.testclient import TestClient

from jobhunter.config import Config
from jobhunter.interfaces.api.app import create_app

from .fakes import FakeRepos, make_ctx

SECRET = "test-secret-at-least-32-bytes-long!!"


class FakeContainer:
    def __init__(self):
        self.config = Config(database_url="postgresql://unused", supabase_jwt_secret=SECRET,
                             allowed_user_email="me@example.com")
        self.ctx = make_ctx(FakeRepos())

    @contextmanager
    def pooled(self):
        yield self.ctx

    session = pooled

    def close_pool(self):
        pass


def token(email="me@example.com", sub="u1", aud="authenticated", exp=None):
    return jwt.encode({"sub": sub, "email": email, "aud": aud, "exp": exp or int(time.time()) + 600}, SECRET,
                      algorithm="HS256")


@pytest.fixture
def client():
    container = FakeContainer()
    with TestClient(create_app(container, start_background=False)) as c:
        c.container = container
        yield c


def auth(t):
    return {"Authorization": f"Bearer {t}"}


def test_health_is_public(client):
    assert client.get("/health").json() == {"ok": True}


def test_missing_token_is_401(client):
    r = client.get("/jobs/1")
    assert r.status_code == 401 and r.headers["www-authenticate"] == "Bearer"


def test_expired_or_wrong_audience_is_401(client):
    assert client.get("/jobs/1", headers=auth(token(exp=int(time.time()) - 10))).status_code == 401
    assert client.get("/jobs/1", headers=auth(token(aud="anon"))).status_code == 401


def test_other_account_is_403(client):
    assert client.get("/jobs/1", headers=auth(token(email="intruder@example.com"))).status_code == 403


def test_valid_token_creates_profile_and_maps_not_found(client):
    r = client.get("/jobs/999", headers=auth(token()))
    assert r.status_code == 404 and "not found" in r.json()["detail"].lower()
    assert client.container.ctx.repos.users.get("u1")["email"] == "me@example.com"


def test_invalid_stage_is_422(client):
    repos = client.container.ctx.repos
    jid = repos.jobs.insert_if_new({"key": "k", "source": "s", "company": "c", "title": "t", "location": "",
                                    "description": ""}, "fp")
    r = client.patch(f"/jobs/{jid}", json={"stage": "bogus"}, headers=auth(token()))
    assert r.status_code == 422
