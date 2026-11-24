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


def test_local_mode_needs_no_token_and_serves_files(tmp_path):
    from jobhunter.infrastructure.storage.local_storage import LocalStorage
    from jobhunter.interfaces.api.auth import LOCAL_USER_ID
    container = FakeContainer()
    container.config = Config(database_url="postgresql://unused", local_mode=True, allowed_user_email="me@example.com")
    container.ctx.storage = container.storage = LocalStorage(tmp_path, "http://api.test")
    key = container.storage.upload("1/v1/cv — final.html", "<h1>hi</h1>", "text/html")
    with TestClient(create_app(container, start_background=False)) as c:
        assert c.get("/jobs/999").status_code == 404  # reached the use case: no 401
        assert container.ctx.repos.users.get(LOCAL_USER_ID)["email"] == "me@example.com"
        assert container.storage.signed_url(key, download_name="CV.html") == f"http://api.test/files/{key}?download=CV.html"
        r = c.get(f"/files/{key}", params={"download": "Café CV.html"})
        assert r.status_code == 200 and r.text == "<h1>hi</h1>" and r.headers["content-type"].startswith("text/html")
        assert "filename*=UTF-8''Caf%C3%A9%20CV.html" in r.headers["content-disposition"]
        assert c.get("/files/..%2F..%2Fsecret").status_code == 404
        assert c.get("/files/missing.pdf").status_code == 404


def test_files_route_only_exists_in_local_mode(client):
    assert client.get("/files/anything", headers=auth(token())).status_code == 404


def test_invalid_stage_is_422(client):
    repos = client.container.ctx.repos
    jid = repos.jobs.insert_if_new({"key": "k", "source": "s", "company": "c", "title": "t", "location": "",
                                    "description": ""}, "fp")
    r = client.patch(f"/jobs/{jid}", json={"stage": "bogus"}, headers=auth(token()))
    assert r.status_code == 422


def test_database_outage_is_503_with_cors(client):
    from psycopg import OperationalError

    def boom(*a, **k):
        raise OperationalError("failed to resolve host 'x': getaddrinfo failed")
    client.container.ctx.repos.jobs.get = boom
    r = client.get("/jobs/1", headers={**auth(token()), "Origin": "http://localhost:3000"})
    assert r.status_code == 503
    assert r.headers.get("access-control-allow-origin") == "http://localhost:3000"


def test_startup_error_classification():
    from jobhunter.interfaces.api.app import _startup_error
    assert _startup_error(Exception("failed to resolve host 'h': [Errno 11002] getaddrinfo failed"))[0] is True
    assert _startup_error(Exception("FATAL: tenant/user postgres.x not found"))[0] is False
