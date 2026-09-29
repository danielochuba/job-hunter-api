"""In-memory adapters for the ports, so use cases can be tested without Postgres, OpenAI or HTTP."""
import itertools
from contextlib import contextmanager
from datetime import datetime, timezone

from jobhunter.application.context import AppContext


def now():
    return datetime.now(timezone.utc)


class Table:
    def __init__(self):
        self.rows = {}
        self._ids = itertools.count(1)

    def add(self, **fields):
        rid = fields.pop("id", None) or next(self._ids)
        row = {"id": rid, "created_at": now(), **fields}
        self.rows[rid] = row
        return dict(row)

    def get(self, rid):
        row = self.rows.get(rid)
        return dict(row) if row else None

    def update(self, rid, **fields):
        if rid not in self.rows:
            return None
        self.rows[rid].update(fields)
        return dict(self.rows[rid])

    def all(self):
        return [dict(r) for r in self.rows.values()]


class FakeJobs(Table):
    def insert_if_new(self, job, fingerprint):
        if any(r["key"] == job["key"] or r["fingerprint"] == fingerprint for r in self.rows.values()):
            return None
        return self.add(**{"stage": "new", "fit": None, "fit_score": None, "cv_id": None, "similarity": None,
                           "feedback": None, "company_domain": None, "remote_policy": None, "salary": None,
                           **job, "fingerprint": fingerprint})["id"]

    def find_by_key_or_fingerprint(self, key, fp):
        return next((dict(r) for r in self.rows.values() if r["key"] == key or r["fingerprint"] == fp), None)

    def to_score(self, limit, job_ids=None):
        if job_ids:
            return [self.get(i) for i in job_ids]
        rows = [r for r in self.all() if r["stage"] == "new" and r["similarity"] is not None]
        return sorted(rows, key=lambda r: -r["similarity"])[:limit]

    def feedback_examples(self, limit=10):
        return [r for r in self.all() if r["feedback"]][:limit]

    def top_scored(self, min_fit, limit):
        return [r["id"] for r in self.all() if r["stage"] == "scored" and (r["fit_score"] or 0) >= min_fit][:limit]

    def board(self, stages):
        return [r for r in self.all() if r["stage"] in stages]


class FakeUsers(Table):
    def get(self, user_id=None):
        if user_id:
            return super().get(user_id)
        return next(iter(self.all()), None)

    def ensure(self, user_id, email):
        if user_id not in self.rows:
            self.add(id=user_id, email=email, first_name="", last_name="", full_name="")
        return self.get(user_id)


class FakeCVs(Table):
    def default(self):
        rows = sorted(self.all(), key=lambda r: not r.get("is_default"))
        return rows[0] if rows else None

    def any(self):
        return bool(self.rows)

    def create(self, **fields):
        return self.add(is_default=False, embedding=None, **fields)

    def set_default(self, cv_id):
        for r in self.rows.values():
            r["is_default"] = r["id"] == cv_id

    def list(self):
        return self.all()


class FakeSettings:
    def __init__(self):
        self.row = {"id": 1, "filters": {}, "search_queries": [], "aggregators": [], "followup_days": 7,
                    "matching": {"similarity_threshold": 0.25, "score_limit": 30, "min_fit_for_generate": 70,
                                 "alert_min_fit": 80},
                    "schedule": {"enabled": True, "time": "07:30", "auto_match": True}, "monthly_budget_usd": 20}

    def get(self):
        return dict(self.row)

    def update(self, **fields):
        self.row.update(fields)
        return self.get()


class FakeApplications(Table):
    def next_version(self, job_id):
        return 1 + max((r["version"] for r in self.rows.values() if r["job_id"] == job_id), default=0)

    def create(self, **fields):
        return self.add(**fields)

    def latest(self, job_id):
        rows = [r for r in self.all() if r["job_id"] == job_id]
        return max(rows, key=lambda r: r["version"]) if rows else None


class FakeEvents(Table):
    def add(self, job_id, kind, note=None):  # noqa: D401  (port signature)
        return super().add(job_id=job_id, kind=kind, note=note, at=now())


class FakeReminders(Table):
    def create(self, **fields):
        return self.add(done=False, notified=False, **fields)

    def has_open_auto(self, job_id):
        return any(r["job_id"] == job_id and r.get("auto") and not r["done"] for r in self.rows.values())

    def close_auto(self, job_id):
        for r in self.rows.values():
            if r["job_id"] == job_id and r.get("auto"):
                r["done"] = True


class FakeNotifications(Table):
    def create(self, kind, title, body, job_id):
        return self.add(kind=kind, title=title, body=body, job_id=job_id, read=False)


class FakeRuns(Table):
    def active_of_kind(self, kind):
        return next((r for r in self.all() if r["kind"] == kind and r["status"] in ("queued", "running")), None)

    def create(self, kind, params, trigger):
        return self.add(kind=kind, params=params, trigger=trigger, status="queued", log=[], progress={})

    def append_log(self, run_id, line):
        self.rows[run_id]["log"].append(line)


class FakeUsage(Table):
    def record(self, run_id, purpose, model, tin, tout, cost):
        self.add(run_id=run_id, purpose=purpose, model=model, input_tokens=tin, output_tokens=tout, cost_usd=cost)

    def spent_since(self, start):
        return sum(r["cost_usd"] for r in self.rows.values())

    def run_cost(self, run_id):
        return sum(r["cost_usd"] for r in self.rows.values() if r["run_id"] == run_id)


class FakeLeads:
    def __init__(self):
        self.marked = {}

    def seen(self, keys):
        return {k for k in keys if k in self.marked}

    def mark(self, key, jobs):
        self.marked[key] = jobs


class FakeAnswers(Table):
    def create(self, **fields):
        return self.add(**fields)

    def for_job(self, job_id):
        return [r for r in self.all() if r["job_id"] == job_id]

    def delete(self, answer_id):
        self.rows.pop(answer_id, None)


class FakeCompanies:
    def by_source(self, active_only=True):
        return {}


class FakeRepos:
    def __init__(self):
        self.jobs = FakeJobs()
        self.users = FakeUsers()
        self.cvs = FakeCVs()
        self.settings = FakeSettings()
        self.applications = FakeApplications()
        self.events = FakeEvents()
        self.reminders = FakeReminders()
        self.notifications = FakeNotifications()
        self.runs = FakeRuns()
        self.usage = FakeUsage()
        self.leads = FakeLeads()
        self.companies = FakeCompanies()
        self.answers = FakeAnswers()

    @contextmanager
    def transaction(self):
        yield


class FakeLLM:
    """Duck-typed LLM: canned responses keyed by schema name; embeddings from keyword overlap."""
    fast_model = "gpt-5-mini"
    strong_model = "gpt-5"

    def __init__(self, responses=None, on_usage=None):
        self.responses = responses or {}
        self.calls = []
        self.on_usage = on_usage

    def embed(self, texts, purpose="embed"):
        vocab = ["python", "django", "backend", "node", "java", "sales"]
        if self.on_usage:
            self.on_usage(purpose, "text-embedding-3-small", 10 * len(texts), 0)
        return [[float(t.lower().count(w)) + 0.01 for w in vocab] for t in texts]

    def structured(self, model, system, user, schema, name, purpose=None, effort=None):
        self.calls.append((name, user))
        if self.on_usage:
            self.on_usage(purpose or name, model, 1000, 200)
        r = self.responses[name]
        return r(user) if callable(r) else r


class FakeStorage:
    def __init__(self):
        self.files = {}

    def upload(self, path, data, content_type):
        self.files[path] = data
        return path

    def download(self, path):
        return self.files[path]

    def signed_url(self, path, expires_in=300, download_name=None):
        return f"https://signed.example/{path}"


class FakeRenderer:
    def cv_html(self, context):
        bullets = [b for e in context["experience"] for b in e["bullets"]]
        return f"<h1>{context['cv'].get('name')}</h1>" + "".join(f"<li>{b}</li>" for b in bullets)

    def pdf(self, html):
        return None


class Null:
    enabled = False
    company_sources = ()
    aggregators = ()
    supported = (".txt", ".json", ".yaml", ".md")

    def __getattr__(self, name):
        return lambda *a, **k: None


def make_ctx(repos=None, llm=None):
    repos = repos or FakeRepos()
    llm = llm or FakeLLM()

    def factory(on_usage=None):
        llm.on_usage = on_usage
        return llm
    return AppContext(repos=repos, storage=FakeStorage(), sources=Null(), web=Null(), finder=Null(), mailer=Null(),
                      notifier=Null(), renderer=FakeRenderer(), extractor=Null(), llm_factory=factory,
                      desktop_notifications=False)
