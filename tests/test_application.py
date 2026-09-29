"""Use cases against in-memory fakes: no database, no OpenAI, no network."""
import pytest

from jobhunter.application import collect, generation, ingest, jobs, mail, matching, runs, tracker, usage
from jobhunter.application.runs import RunContext
from jobhunter.domain.errors import BudgetExceeded, InvalidInput, RunBusy
from jobhunter.domain.jobs import fingerprint

from .fakes import FakeLLM, FakeRepos, make_ctx

FIT = {"fit_score": 82, "summary": "Strong Django match", "matched_requirements": ["Django"], "gaps": [],
       "dealbreakers": [], "relevant_bullet_ids": ["acme-2"], "eligible": True, "ineligible_reason": "",
       "remote_policy": "remote", "visa_sponsorship": "yes", "location_restrictions": [], "salary": "",
       "required_skills": ["Django", "Kubernetes"], "missing_skills": ["Kubernetes"], "seniority": "mid"}
GEN = {"summary": "Backend engineer for Acme.", "skills_priority": ["Django", "Kubernetes"],
       "experience": [{"id": "acme", "bullets": [{"source_id": "acme-2", "text": "Built DRF APIs (40k req/day)"}]}],
       "projects": [], "cover_letter": "Dear Acme, ..."}


@pytest.fixture
def world(cv, user):
    repos = FakeRepos()
    repos.users.add(**user)
    cv_row = repos.cvs.create(user_id=user["id"], name="Backend", cv=cv)
    repos.cvs.set_default(cv_row["id"])
    llm = FakeLLM({"job_fit": FIT, "tailored_application": GEN})
    ctx = make_ctx(repos, llm)
    return ctx, repos, llm


def job(**over):
    return {"key": "greenhouse:acme:1", "source": "greenhouse", "company": "acme", "title": "Backend Engineer",
            "location": "Remote", "url": "https://x", "description": "Python Django backend APIs", **over}


def run_for(ctx, kind="test"):
    return RunContext(ctx, ctx.repos.runs.create(kind, {}, "test")["id"])


def test_insert_job_dedupes_across_sources(world):
    ctx, repos, _ = world
    assert collect.insert_job(repos, job())
    assert collect.insert_job(repos, job(key="remotive:9", company="Acme")) is None  # same company+title


def test_match_scores_and_alerts(world, monkeypatch):
    ctx, repos, llm = world
    jid = collect.insert_job(repos, job())
    repos.jobs.update(jid, similarity=0.9)
    run = run_for(ctx, "match")
    monkeypatch.setattr(matching, "embed_filter", lambda *a, **k: (1, 1))  # similarity is SQL-side
    out = matching.match(run, {})
    stored = repos.jobs.get(jid)
    assert out["scored"] == 1 and stored["stage"] == "scored" and stored["fit_score"] == 82
    assert stored["cv_id"] is not None
    assert repos.notifications.all()[0]["title"] == "1 new top match"
    assert repos.usage.all(), "LLM usage is metered"


def test_precheck_skips_llm_for_no_sponsorship(world):
    ctx, repos, llm = world
    jid = collect.insert_job(repos, job(description="Sorry, we cannot sponsor visas."))
    repos.jobs.update(jid, similarity=0.9)
    [(row, res, err)] = matching.score(run_for(ctx), 10)
    assert repos.jobs.get(jid)["stage"] == "ineligible" and res["prechecked"]
    assert llm.calls == []


def test_generate_applies_truthfulness_guard_and_versions(world):
    ctx, repos, _ = world
    jid = collect.insert_job(repos, job())
    app, warnings = generation.generate_for_job(run_for(ctx), jid)
    assert app["version"] == 1 and app["result"]["skills_priority"] == ["Django"]
    assert any("Kubernetes" in w for w in warnings)
    assert repos.jobs.get(jid)["stage"] == "generated"
    assert "Daniel Example" in ctx.storage.files[app["cv_html_path"]]
    v2 = generation.save_edit(ctx, app["id"], cover_letter="Edited letter")
    assert v2["version"] == 2 and v2["cover_letter"] == "Edited letter"


def test_edit_cannot_smuggle_in_untraceable_bullets(world):
    ctx, repos, _ = world
    jid = collect.insert_job(repos, job())
    app, _ = generation.generate_for_job(run_for(ctx), jid)
    edited = {"experience": [{"id": "acme", "bullets": [{"source_id": "fake-99", "text": "Led 500 engineers"}]}]}
    v2 = generation.save_edit(ctx, app["id"], result=edited)
    assert v2["result"]["experience"] == [] and v2["warnings"]


def test_applied_creates_followup_and_closing_cancels_it(world):
    ctx, repos, _ = world
    jid = collect.insert_job(repos, job())
    tracker.set_stage(ctx, jid, "applied")
    [rem] = repos.reminders.all()
    assert rem["auto"] and not rem["done"]
    tracker.set_stage(ctx, jid, "rejected")
    assert repos.reminders.all()[0]["done"]
    assert [e["kind"] for e in repos.events.all()] == ["stage_change", "stage_change"]


def test_approve_is_implicit_positive_feedback(world):
    ctx, repos, _ = world
    jid = collect.insert_job(repos, job())
    jobs.update(ctx, jid, stage="approved")
    assert repos.jobs.get(jid)["feedback"] == "up"


def test_invalid_stage_rejected(world):
    ctx, repos, _ = world
    jid = collect.insert_job(repos, job())
    with pytest.raises(InvalidInput):
        tracker.set_stage(ctx, jid, "hired!!")


def test_runs_lifecycle_busy_and_budget(world):
    ctx, repos, _ = world
    rid = runs.create(ctx, "collect")
    with pytest.raises(RunBusy):
        runs.create(ctx, "collect")
    runs.execute(ctx, rid, lambda run, p: {"ok": 1})
    assert repos.runs.get(rid)["status"] == "succeeded"
    failing = runs.create(ctx, "collect")
    runs.execute(ctx, failing, lambda run, p: 1 / 0)
    assert repos.runs.get(failing)["status"] == "failed"
    repos.usage.record(None, "x", "gpt-5", 0, 0, 25.0)
    with pytest.raises(BudgetExceeded):
        runs.create(ctx, "match")
    with pytest.raises(BudgetExceeded):
        usage.metered_llm(ctx)


def test_ingest_structured_yaml_skips_llm(cv):
    import yaml
    parsed = ingest.structured_input("master_cv.yaml", yaml.safe_dump({"name": "Ada Lovelace", **cv}))
    assert parsed["experience"][0]["id"] == "acme"
    assert ingest.structured_input("cv.md", "# not structured") is None


def test_mail_reply_detection():
    msg = {"from": "jane@acme.io", "internal_ms": 2000}
    assert mail.is_reply(msg, "me@gmail.com", 1000)
    assert not mail.is_reply({**msg, "from": "me@gmail.com"}, "me@gmail.com", 1000)
    assert not mail.is_reply(msg, "me@gmail.com", 3000)


def test_import_fingerprint_matches_existing(world):
    ctx, repos, _ = world
    collect.insert_job(repos, job())
    existing = repos.jobs.find_by_key_or_fingerprint("import:x", fingerprint("acme", "Backend Engineer"))
    assert existing["key"] == "greenhouse:acme:1"


def test_collect_turns_leads_into_jobs_and_caches_them(world):
    ctx, repos, llm = world

    class Sources:
        aggregators = ("reddit",)

        def collect(self, companies, queries, aggregators, keep, on_source=None, context=None):
            lead = {"lead": True, "key": "reddit:1", "source": "reddit", "url": "https://reddit.com/1",
                    "text": "[Hiring] Two roles: Backend Engineer and Designer", "fetch": False}
            assert keep(lead)
            yield lead, None
    ctx.sources = Sources()
    llm.responses["lead_jobs"] = {"jobs": [
        {"title": "Backend Engineer", "company": "Acme", "location": "Remote", "remote_policy": "remote", "salary": "",
         "description": "Python APIs", "apply_url": "", "company_website": "https://acme.io"},
        {"title": "Designer", "company": "Acme", "location": "Remote", "remote_policy": "remote", "salary": "",
         "description": "Figma", "apply_url": "", "company_website": ""}]}
    repos.settings.update(aggregators=["reddit"], filters={"title_exclude": ["designer"]})
    out = collect.collect(run_for(ctx, "collect"), {})
    assert out["new"] == 1  # the designer role is filtered out after extraction
    [j] = repos.jobs.all()
    assert (j["title"], j["company_domain"], j["key"]) == ("Backend Engineer", "acme.io", "reddit:1#0")
    assert repos.leads.marked == {"reddit:1": 2}
    calls = len(llm.calls)
    collect.collect(run_for(ctx, "collect"), {})  # same lead again: cached, no LLM call
    assert len(llm.calls) == calls


def test_form_answer_is_grounded_and_saved(world):
    from jobhunter.application import answers
    ctx, repos, llm = world
    jid = collect.insert_job(repos, job(description="No cover letter template. Tell us what you have built."))
    llm.responses["form_answer"] = {"answer": "  I built DRF APIs serving 40k requests a day. ",
                                    "bullet_ids_used": ["acme-2", "invented-9"]}
    row = answers.generate(ctx, jid, "Message to the recruiter", max_words=120, tone="direct", emphasis="APIs")
    assert row["answer"] == "I built DRF APIs serving 40k requests a day."
    assert row["evidence"] == ["acme-2"]  # unknown bullet ids are dropped
    name, prompt = llm.calls[-1]
    assert name == "form_answer" and "No cover letter template" in prompt and "at most 120 words" in prompt
    [listed] = answers.list_for_job(ctx, jid)
    assert listed["evidence_text"][0]["text"].startswith("Designed REST APIs")
    with pytest.raises(InvalidInput):
        answers.generate(ctx, jid, "   ")
    with pytest.raises(InvalidInput):
        answers.generate(ctx, jid, "Why us?", tone="sarcastic")
