"""Postgres adapters for the repository ports (application/ports.py). All SQL lives here."""
from psycopg import sql
from psycopg.types.json import Jsonb

# Everything except the (large) embedding vector.
JOB_COLS = ("id, key, fingerprint, source, company, company_domain, title, location, url, "
            "description, posted_at, fetched_at, remote_policy, visa_sponsorship, salary, similarity, "
            "cv_id, fit_score, fit, stage, feedback, feedback_reason, notes, created_at, updated_at")
JOB_LIST_COLS = ("id, source, company, company_domain, title, location, url, posted_at, fetched_at, "
                 "remote_policy, visa_sponsorship, salary, similarity, cv_id, fit_score, stage, feedback, "
                 "fit->>'summary' AS fit_summary, fit->>'ineligible_reason' AS ineligible_reason, updated_at")
CV_COLS = "id, user_id, name, is_default, cv, raw_text, source_file, created_at, updated_at"
RUN_COLS = ("id, kind, status, params, progress, error, trigger, started_at, finished_at, "
            "cardinality(log) AS log_lines")
JOB_SORTS = {"fit": "fit_score DESC NULLS LAST, similarity DESC NULLS LAST", "new": "fetched_at DESC",
             "posted": "posted_at DESC NULLS LAST", "similarity": "similarity DESC NULLS LAST",
             "updated": "updated_at DESC"}
# jsonb columns that hold arrays (plain Python lists are otherwise sent as Postgres arrays)
JSON_LIST_COLUMNS = {"other_links", "languages", "warnings"}


def vec(v):
    """pgvector text literal; avoids needing the pgvector adapter on the client."""
    return "[" + ",".join(f"{float(x):.7f}" for x in v) + "]"


def _adapt(col, v):
    if isinstance(v, dict) or (col in JSON_LIST_COLUMNS and isinstance(v, list)):
        return Jsonb(v)
    return v


class _Repo:
    table = ""

    def __init__(self, conn):
        self.conn = conn

    def _one(self, q, params=None):
        return self.conn.execute(q, params).fetchone()

    def _all(self, q, params=None):
        return self.conn.execute(q, params).fetchall()

    def _insert(self, **fields):
        q = sql.SQL("INSERT INTO {} ({}) VALUES ({}) RETURNING *").format(
            sql.Identifier(self.table), sql.SQL(", ").join(map(sql.Identifier, fields)),
            sql.SQL(", ").join(sql.Placeholder() * len(fields)))
        return self._one(q, [_adapt(k, v) for k, v in fields.items()])

    def _update(self, row_id, key="id", **fields):
        if not fields:
            return self._one(sql.SQL("SELECT * FROM {} WHERE {} = %s").format(
                sql.Identifier(self.table), sql.Identifier(key)), (row_id,))
        q = sql.SQL("UPDATE {} SET {} WHERE {} = %s RETURNING *").format(
            sql.Identifier(self.table),
            sql.SQL(", ").join(sql.SQL("{} = %s").format(sql.Identifier(k)) for k in fields),
            sql.Identifier(key))
        return self._one(q, [*(_adapt(k, v) for k, v in fields.items()), row_id])

    def _delete(self, row_id):
        self.conn.execute(sql.SQL("DELETE FROM {} WHERE id = %s").format(sql.Identifier(self.table)), (row_id,))


# ================================================================ jobs

class PgJobRepo(_Repo):
    table = "jobs"

    def insert_if_new(self, job, fingerprint):
        row = self._one("""
            INSERT INTO jobs (key, fingerprint, source, company, company_domain, title, location, url,
                              description, posted_at, remote_policy, salary)
            SELECT %(key)s, %(fp)s, %(source)s, %(company)s, %(company_domain)s, %(title)s, %(location)s,
                   %(url)s, %(description)s, %(posted_at)s, %(remote_policy)s, %(salary)s
            WHERE NOT EXISTS (SELECT 1 FROM jobs WHERE fingerprint = %(fp)s)
            ON CONFLICT (key) DO NOTHING
            RETURNING id""", {"company_domain": None, "remote_policy": None, "salary": None, "posted_at": None,
                              "url": None, "location": "", "description": "", **job, "fp": fingerprint})
        return row["id"] if row else None

    def find_by_key_or_fingerprint(self, key, fingerprint):
        return self._one(f"SELECT {JOB_COLS} FROM jobs WHERE key = %s OR fingerprint = %s LIMIT 1", (key, fingerprint))

    def get(self, job_id):
        return self._one(f"SELECT {JOB_COLS} FROM jobs WHERE id = %s", (job_id,))

    def update(self, job_id, **fields):
        self._update(job_id, **fields)
        return self.get(job_id)

    def list(self, *, stage=None, min_fit=None, source=None, q=None, feedback=None, since=None,
             sort="fit", limit=50, offset=0):
        where, params = [], []
        if stage:
            where.append("stage = ANY(%s)")
            params.append(list(stage) if isinstance(stage, (list, tuple)) else stage.split(","))
        for col, op, val in (("fit_score", ">=", min_fit), ("source", "=", source), ("feedback", "=", feedback),
                             ("fetched_at", ">=", since)):
            if val is not None and val != "":
                where.append(f"{col} {op} %s")
                params.append(val)
        if q:
            where.append("(title ILIKE %s OR company ILIKE %s OR location ILIKE %s)")
            params += [f"%{q}%"] * 3
        clause = ("WHERE " + " AND ".join(where)) if where else ""
        total = self._one(f"SELECT count(*) AS n FROM jobs {clause}", params)["n"]
        rows = self._all(f"SELECT {JOB_LIST_COLS} FROM jobs {clause} ORDER BY {JOB_SORTS.get(sort, JOB_SORTS['fit'])} "
                         "LIMIT %s OFFSET %s", [*params, limit, offset])
        return rows, total

    def sources(self):
        return self._all("SELECT source, count(*) AS n FROM jobs GROUP BY source ORDER BY n DESC")

    def needing_embedding(self, job_ids=None, limit=500):
        if job_ids:
            return self._all("SELECT id, title, company, description FROM jobs WHERE id = ANY(%s) AND embedding IS NULL",
                             (list(job_ids),))
        return self._all("SELECT id, title, company, description FROM jobs WHERE stage = 'new' AND embedding IS NULL "
                         "ORDER BY id LIMIT %s", (limit,))

    def set_embedding(self, job_id, embedding):
        self.conn.execute("UPDATE jobs SET embedding = %s::vector WHERE id = %s", (vec(embedding), job_id))

    def similarity_candidates(self, job_ids):
        """Best CV per job plus similarity to the liked/disliked centroids (feedback learning)."""
        return self._all("""
            WITH up AS (SELECT avg(embedding) AS v FROM jobs WHERE feedback = 'up' AND embedding IS NOT NULL),
                 dn AS (SELECT avg(embedding) AS v FROM jobs WHERE feedback = 'down' AND embedding IS NOT NULL),
                 best AS (
                   SELECT DISTINCT ON (j.id) j.id, c.id AS cv_id, 1 - (j.embedding <=> c.embedding) AS sim
                   FROM jobs j CROSS JOIN cvs c
                   WHERE j.id = ANY(%s) AND j.embedding IS NOT NULL AND c.embedding IS NOT NULL
                   ORDER BY j.id, (j.embedding <=> c.embedding))
            SELECT b.id, b.cv_id, b.sim,
                   CASE WHEN up.v IS NULL THEN NULL ELSE 1 - (j.embedding <=> up.v) END AS up_sim,
                   CASE WHEN dn.v IS NULL THEN NULL ELSE 1 - (j.embedding <=> dn.v) END AS dn_sim
            FROM best b JOIN jobs j ON j.id = b.id CROSS JOIN up CROSS JOIN dn""", (list(job_ids),))

    def to_score(self, limit, job_ids=None):
        if job_ids:
            return self._all(f"SELECT {JOB_COLS} FROM jobs WHERE id = ANY(%s)", (list(job_ids),))
        return self._all(f"SELECT {JOB_COLS} FROM jobs WHERE stage = 'new' AND similarity IS NOT NULL "
                         "ORDER BY similarity DESC LIMIT %s", (limit,))

    def top_scored(self, min_fit, limit):
        return [r["id"] for r in self._all("SELECT id FROM jobs WHERE stage = 'scored' AND fit_score >= %s "
                                           "ORDER BY fit_score DESC LIMIT %s", (min_fit, limit))]

    def feedback_examples(self, limit=10):
        return self._all("SELECT title, company, location, feedback, feedback_reason FROM jobs "
                         "WHERE feedback IS NOT NULL ORDER BY updated_at DESC LIMIT %s", (limit,))

    def counts(self, job_id):
        return self._one("""SELECT
            (SELECT count(*) FROM applications WHERE job_id = %(id)s) AS applications,
            (SELECT count(*) FROM contacts WHERE job_id = %(id)s) AS contacts,
            (SELECT count(*) FROM outreach WHERE job_id = %(id)s) AS outreach,
            (SELECT count(*) FROM prep WHERE job_id = %(id)s) AS prep""", {"id": job_id})

    def stage_counts(self):
        return {r["stage"]: r["n"] for r in self._all("SELECT stage, count(*) AS n FROM jobs GROUP BY stage")}

    def board(self, stages):
        return self._all("""
            SELECT j.id, j.title, j.company, j.company_domain, j.location, j.fit_score, j.stage, j.updated_at,
                   (SELECT min(due_at) FROM reminders r WHERE r.job_id = j.id AND NOT r.done) AS next_due,
                   (SELECT max(at) FROM events e WHERE e.job_id = j.id) AS last_activity,
                   (SELECT status FROM outreach o WHERE o.job_id = j.id ORDER BY o.updated_at DESC LIMIT 1) AS email_status
            FROM jobs j WHERE j.stage = ANY(%s) ORDER BY j.updated_at DESC""", (list(stages),))

    def skill_counts(self, field, min_fit, limit):
        if field not in ("missing_skills", "required_skills"):
            raise ValueError(field)
        return self._all(f"""
            SELECT min(s) AS skill, count(*) AS jobs, round(avg(fit_score)) AS avg_fit,
                   (array_agg(json_build_object('id', id, 'title', title, 'company', company, 'fit_score', fit_score)
                              ORDER BY fit_score DESC))[1:5] AS examples
            FROM jobs, jsonb_array_elements_text(coalesce(fit->'{field}', '[]')) AS s
            WHERE fit_score >= %s AND stage <> 'ineligible'
            GROUP BY lower(s) ORDER BY count(*) DESC, avg(fit_score) DESC LIMIT %s""", (min_fit, limit))

    def count_fit_at_least(self, min_fit):
        return self._one("SELECT count(*) AS n FROM jobs WHERE fit_score >= %s AND stage <> 'ineligible'",
                         (min_fit,))["n"]

    def dashboard(self):
        kpis = self._one("""SELECT
            (SELECT count(*) FROM jobs WHERE fetched_at > now() - interval '24 hours') AS new_today,
            (SELECT count(*) FROM jobs WHERE fetched_at > now() - interval '7 days') AS new_week,
            (SELECT count(*) FROM jobs WHERE stage IN ('scored', 'generated') AND fit_score >= 75) AS strong_matches,
            (SELECT round(avg(fit_score)) FROM jobs WHERE stage IN ('scored', 'generated')) AS avg_fit,
            (SELECT count(*) FROM reminders WHERE NOT done AND due_at <= now() + interval '1 day') AS reminders_due,
            (SELECT count(*) FROM outreach WHERE status = 'replied') AS replies,
            (SELECT count(*) FROM outreach WHERE status IN ('sent', 'replied')) AS emails_sent,
            (SELECT count(*) FROM notifications WHERE NOT read) AS unread""")
        daily = self._all("""
            SELECT to_char(d, 'YYYY-MM-DD') AS day, coalesce(n, 0) AS jobs
            FROM generate_series(current_date - 13, current_date, interval '1 day') d
            LEFT JOIN (SELECT date_trunc('day', fetched_at) AS day, count(*) AS n FROM jobs
                       WHERE fetched_at > current_date - 14 GROUP BY 1) j ON j.day = d
            ORDER BY d""")
        by_source = self._all("SELECT source, count(*) AS n FROM jobs WHERE fetched_at > current_date - 14 "
                              "GROUP BY source ORDER BY n DESC")
        top = self._all(f"SELECT {JOB_LIST_COLS} FROM jobs WHERE stage IN ('scored', 'generated') "
                        "ORDER BY fit_score DESC NULLS LAST LIMIT 8")
        return {"kpis": kpis, "daily": daily, "by_source": by_source, "top": top}


# ================================================================ user & CVs

class PgUserRepo(_Repo):
    table = "user_profile"

    def get(self, user_id=None):
        if user_id:
            return self._one("SELECT * FROM user_profile WHERE id = %s", (user_id,))
        return self._one("SELECT * FROM user_profile ORDER BY created_at LIMIT 1")

    def ensure(self, user_id, email):
        self.conn.execute("INSERT INTO user_profile (id, email) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING",
                          (user_id, email))
        return self.get(user_id)

    def update(self, user_id, **fields):
        return self._update(user_id, **fields)


class PgCVRepo(_Repo):
    table = "cvs"

    def list(self):
        return self._all("""
            SELECT c.id, c.name, c.is_default, c.source_file, c.created_at, c.updated_at,
                   (c.embedding IS NOT NULL) AS embedded,
                   (SELECT count(*) FROM jobs j WHERE j.cv_id = c.id) AS matched_jobs,
                   jsonb_array_length(coalesce(c.cv->'experience', '[]')) AS roles
            FROM cvs c ORDER BY c.is_default DESC, c.updated_at DESC""")

    def get(self, cv_id):
        return self._one(f"SELECT {CV_COLS} FROM cvs WHERE id = %s", (cv_id,))

    def default(self):
        return self._one(f"SELECT {CV_COLS} FROM cvs ORDER BY is_default DESC, updated_at DESC LIMIT 1")

    def any(self):
        return bool(self._one("SELECT 1 AS x FROM cvs LIMIT 1"))

    def create(self, **fields):
        return self._insert(**fields)

    def update(self, cv_id, **fields):
        return self._update(cv_id, **fields)

    def delete(self, cv_id):
        self._delete(cv_id)

    def set_default(self, cv_id):
        with self.conn.transaction():
            self.conn.execute("UPDATE cvs SET is_default = false WHERE is_default")
            self.conn.execute("UPDATE cvs SET is_default = true WHERE id = %s", (cv_id,))

    def clear_embedding(self, cv_id):
        self.conn.execute("UPDATE cvs SET embedding = NULL WHERE id = %s", (cv_id,))

    def missing_embeddings(self):
        return self._all("SELECT id, cv FROM cvs WHERE embedding IS NULL")

    def set_embedding(self, cv_id, embedding):
        self.conn.execute("UPDATE cvs SET embedding = %s::vector WHERE id = %s", (vec(embedding), cv_id))

    def any_embedded(self):
        return bool(self._one("SELECT 1 AS x FROM cvs WHERE embedding IS NOT NULL LIMIT 1"))


# ================================================================ settings & companies

class PgSettingsRepo(_Repo):
    table = "settings"

    def get(self):
        return self._one("SELECT * FROM settings WHERE id = 1")

    def update(self, **fields):
        return self._update(1, **fields)


class PgCompanyRepo(_Repo):
    table = "companies"

    def list(self):
        return self._all("SELECT c.*, (SELECT count(*) FROM jobs j WHERE j.key LIKE c.source || ':' || c.token || ':%%') "
                         "AS jobs FROM companies c ORDER BY c.created_at DESC", ())

    def by_source(self, active_only=True):
        out = {}
        for r in self._all("SELECT source, token FROM companies" + (" WHERE active" if active_only else "")):
            out.setdefault(r["source"], []).append(r["token"])
        return out

    def upsert(self, source, token, name, domain):
        return self._one("""INSERT INTO companies (source, token, name, domain) VALUES (%s, %s, %s, %s)
                            ON CONFLICT (source, token) DO UPDATE SET name = coalesce(EXCLUDED.name, companies.name),
                            domain = coalesce(EXCLUDED.domain, companies.domain), active = true RETURNING *""",
                         (source, token, name, domain))

    def update(self, company_id, **fields):
        return self._update(company_id, **fields)

    def delete(self, company_id):
        self._delete(company_id)

    def domain_for(self, company):
        row = self._one("SELECT domain FROM companies WHERE (token = %s OR lower(name) = lower(%s)) "
                        "AND domain IS NOT NULL LIMIT 1", (company, company))
        return row["domain"] if row else None


# ================================================================ documents, contacts, outreach

class PgApplicationRepo(_Repo):
    table = "applications"

    def get(self, app_id):
        return self._one("SELECT * FROM applications WHERE id = %s", (app_id,))

    def for_job(self, job_id):
        return self._all("SELECT a.*, c.name AS cv_name FROM applications a LEFT JOIN cvs c ON c.id = a.cv_id "
                         "WHERE a.job_id = %s ORDER BY version DESC", (job_id,))

    def latest(self, job_id):
        return self._one("SELECT * FROM applications WHERE job_id = %s ORDER BY version DESC LIMIT 1", (job_id,))

    def next_version(self, job_id):
        return self._one("SELECT coalesce(max(version), 0) + 1 AS v FROM applications WHERE job_id = %s",
                         (job_id,))["v"]

    def create(self, **fields):
        return self._insert(**fields)


class PgContactRepo(_Repo):
    table = "contacts"

    def for_job(self, job_id):
        return self._all("SELECT * FROM contacts WHERE job_id = %s ORDER BY confidence DESC, created_at", (job_id,))

    def get(self, contact_id):
        return self._one("SELECT * FROM contacts WHERE id = %s", (contact_id,))

    def upsert(self, job_id, domain, c):
        row = self._one("""
            INSERT INTO contacts (job_id, company_domain, name, role, email, source, confidence)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (job_id, email) DO UPDATE SET confidence = GREATEST(contacts.confidence, EXCLUDED.confidence)
            RETURNING (xmax = 0) AS inserted""",
                        (job_id, domain, c.get("name"), c.get("role"), c["email"], c["source"], c["confidence"]))
        return bool(row and row["inserted"])

    def add_manual(self, job_id, domain, email, name, role):
        return self._one("""INSERT INTO contacts (job_id, company_domain, name, role, email, source, confidence)
                            VALUES (%s, %s, %s, %s, %s, 'manual', 100)
                            ON CONFLICT (job_id, email) DO UPDATE SET name = EXCLUDED.name, role = EXCLUDED.role,
                            source = 'manual', confidence = 100 RETURNING *""", (job_id, domain, name, role, email))

    def delete(self, contact_id):
        self._delete(contact_id)


class PgOutreachRepo(_Repo):
    table = "outreach"

    def get(self, outreach_id):
        return self._one("SELECT * FROM outreach WHERE id = %s", (outreach_id,))

    def for_job(self, job_id):
        return self._all("SELECT o.*, c.name AS contact_name, c.role AS contact_role FROM outreach o "
                         "LEFT JOIN contacts c ON c.id = o.contact_id WHERE o.job_id = %s ORDER BY o.created_at DESC",
                         (job_id,))

    def create(self, **fields):
        return self._insert(**fields)

    def update(self, outreach_id, **fields):
        return self._update(outreach_id, **fields)

    def delete(self, outreach_id):
        self._delete(outreach_id)

    def awaiting_reply(self):
        return self._all("SELECT * FROM outreach WHERE status = 'sent' AND gmail_thread_id IS NOT NULL")

    def recent_replies(self, limit=5):
        return self._all("""SELECT o.id, o.job_id, o.to_email, o.replied_at, o.reply_snippet, j.title, j.company
                            FROM outreach o JOIN jobs j ON j.id = o.job_id WHERE o.status = 'replied'
                            ORDER BY o.replied_at DESC LIMIT %s""", (limit,))


# ================================================================ tracker

class PgEventRepo(_Repo):
    table = "events"

    def add(self, job_id, kind, note=None):
        return self._insert(job_id=job_id, kind=kind, note=note)

    def for_job(self, job_id):
        return self._all("SELECT * FROM events WHERE job_id = %s ORDER BY at DESC", (job_id,))

    def recent(self, limit=12):
        return self._all("SELECT e.*, j.title, j.company FROM events e JOIN jobs j ON j.id = e.job_id "
                         "ORDER BY e.at DESC LIMIT %s", (limit,))


class PgReminderRepo(_Repo):
    table = "reminders"

    def list(self, include_done=False):
        where = "" if include_done else "WHERE NOT r.done"
        return self._all(f"SELECT r.*, j.title, j.company FROM reminders r LEFT JOIN jobs j ON j.id = r.job_id "
                         f"{where} ORDER BY r.done, r.due_at")

    def next_for_job(self, job_id):
        return self._one("SELECT id, due_at, note FROM reminders WHERE job_id = %s AND NOT done "
                         "ORDER BY due_at LIMIT 1", (job_id,))

    def create(self, **fields):
        return self._insert(**fields)

    def update(self, reminder_id, **fields):
        return self._update(reminder_id, **fields)

    def delete(self, reminder_id):
        self._delete(reminder_id)

    def has_open_auto(self, job_id):
        return bool(self._one("SELECT 1 AS x FROM reminders WHERE job_id = %s AND auto AND NOT done", (job_id,)))

    def close_auto(self, job_id):
        self.conn.execute("UPDATE reminders SET done = true WHERE job_id = %s AND auto AND NOT done", (job_id,))

    def due_unnotified(self):
        return self._all("""SELECT r.id, r.note, r.job_id, j.company, j.title FROM reminders r
                            LEFT JOIN jobs j ON j.id = r.job_id
                            WHERE NOT r.done AND NOT r.notified AND r.due_at <= now()""")

    def mark_notified(self, reminder_id):
        self.conn.execute("UPDATE reminders SET notified = true WHERE id = %s", (reminder_id,))


class PgPrepRepo(_Repo):
    table = "prep"

    def create(self, job_id, content):
        return self._insert(job_id=job_id, content=content)

    def latest(self, job_id):
        return self._one("SELECT * FROM prep WHERE job_id = %s ORDER BY created_at DESC LIMIT 1", (job_id,))


# ================================================================ system

class PgNotificationRepo(_Repo):
    table = "notifications"

    def create(self, kind, title, body, job_id):
        return self._insert(kind=kind, title=title, body=body or "", job_id=job_id)

    def list(self, unread, limit):
        where = "WHERE NOT read" if unread else ""
        return self._all(f"SELECT * FROM notifications {where} ORDER BY created_at DESC LIMIT %s", (limit,))

    def unread_count(self):
        return self._one("SELECT count(*) AS n FROM notifications WHERE NOT read")["n"]

    def mark_read(self, ids=None):
        if ids:
            self.conn.execute("UPDATE notifications SET read = true WHERE id = ANY(%s)", (list(ids),))
        else:
            self.conn.execute("UPDATE notifications SET read = true WHERE NOT read")


class PgIntegrationRepo(_Repo):
    table = "integrations"

    def get(self, provider):
        return self._one("SELECT * FROM integrations WHERE provider = %s", (provider,))

    def set_pending_state(self, provider, state):
        self.conn.execute("""INSERT INTO integrations (provider, pending_state) VALUES (%s, %s)
                             ON CONFLICT (provider) DO UPDATE SET pending_state = EXCLUDED.pending_state,
                             updated_at = now()""", (provider, state))

    def save_token(self, provider, token, email):
        self.conn.execute("""INSERT INTO integrations (provider, token, email) VALUES (%s, %s, %s)
                             ON CONFLICT (provider) DO UPDATE SET token = EXCLUDED.token, email = EXCLUDED.email,
                             pending_state = NULL, updated_at = now()""",
                          (provider, Jsonb(token) if token is not None else None, email))

    def update_token(self, provider, token):
        self.conn.execute("UPDATE integrations SET token = %s, updated_at = now() WHERE provider = %s",
                          (Jsonb(token), provider))


class PgRunRepo(_Repo):
    table = "runs"

    def active_of_kind(self, kind):
        return self._one("SELECT id FROM runs WHERE kind = %s AND status IN ('queued', 'running') "
                         "AND started_at > now() - interval '2 hours'", (kind,))

    def create(self, kind, params, trigger):
        return self._insert(kind=kind, params=params or {}, trigger=trigger)

    def update(self, run_id, **fields):
        return self._update(run_id, **fields)

    def append_log(self, run_id, line):
        self.conn.execute("UPDATE runs SET log = array_append(log, %s) WHERE id = %s", (line, run_id))

    def get(self, run_id):
        return self._one("SELECT * FROM runs WHERE id = %s", (run_id,))

    def list(self, limit, kind=None):
        if kind:
            return self._all(f"SELECT {RUN_COLS} FROM runs WHERE kind = %s ORDER BY started_at DESC LIMIT %s",
                             (kind, limit))
        return self._all(f"SELECT {RUN_COLS} FROM runs ORDER BY started_at DESC LIMIT %s", (limit,))

    def active(self):
        return self._all(f"SELECT {RUN_COLS} FROM runs WHERE status IN ('queued', 'running') ORDER BY started_at")

    def mark_interrupted(self):
        self.conn.execute("UPDATE runs SET status = 'failed', error = 'Interrupted (API restarted)', "
                          "finished_at = now() WHERE status IN ('queued', 'running')")


class PgUsageRepo(_Repo):
    table = "llm_usage"

    def record(self, run_id, purpose, model, tin, tout, cost):
        self._insert(run_id=run_id, purpose=purpose, model=model, input_tokens=tin, output_tokens=tout, cost_usd=cost)

    def spent_since(self, start):
        return float(self._one("SELECT coalesce(sum(cost_usd), 0) AS s FROM llm_usage WHERE at >= %s", (start,))["s"])

    def run_cost(self, run_id):
        return float(self._one("SELECT coalesce(sum(cost_usd), 0) AS c FROM llm_usage WHERE run_id = %s",
                               (run_id,))["c"])

    def report(self, start, end):
        rng = (start, end)
        grouped = ("sum(cost_usd)::float AS cost, count(*) AS calls, sum(input_tokens) AS input_tokens, "
                   "sum(output_tokens) AS output_tokens")
        return {
            "total": self._one("""SELECT coalesce(sum(cost_usd), 0)::float AS cost,
                                  coalesce(sum(input_tokens), 0) AS input_tokens,
                                  coalesce(sum(output_tokens), 0) AS output_tokens, count(*) AS calls
                                  FROM llm_usage WHERE at >= %s AND at < %s""", rng),
            "by_purpose": self._all(f"SELECT purpose, {grouped} FROM llm_usage WHERE at >= %s AND at < %s "
                                    "GROUP BY purpose ORDER BY cost DESC", rng),
            "by_model": self._all(f"SELECT model, {grouped} FROM llm_usage WHERE at >= %s AND at < %s "
                                  "GROUP BY model ORDER BY cost DESC", rng),
            "by_day": self._all("""SELECT to_char(date_trunc('day', at), 'YYYY-MM-DD') AS day, sum(cost_usd)::float AS cost
                                   FROM llm_usage WHERE at >= %s AND at < %s GROUP BY 1 ORDER BY 1""", rng),
        }


# ================================================================ unit of work

class PgRepositories:
    def __init__(self, conn):
        self.conn = conn
        self.jobs = PgJobRepo(conn)
        self.users = PgUserRepo(conn)
        self.cvs = PgCVRepo(conn)
        self.settings = PgSettingsRepo(conn)
        self.companies = PgCompanyRepo(conn)
        self.applications = PgApplicationRepo(conn)
        self.contacts = PgContactRepo(conn)
        self.outreach = PgOutreachRepo(conn)
        self.events = PgEventRepo(conn)
        self.reminders = PgReminderRepo(conn)
        self.prep = PgPrepRepo(conn)
        self.notifications = PgNotificationRepo(conn)
        self.integrations = PgIntegrationRepo(conn)
        self.runs = PgRunRepo(conn)
        self.usage = PgUsageRepo(conn)

    def transaction(self):
        return self.conn.transaction()
